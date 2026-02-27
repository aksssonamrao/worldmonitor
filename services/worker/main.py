from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timezone

import asyncpg

from app.core.queue import (
    claim_next,
    ensure_job_queue_schema,
    mark_failed,
    mark_succeeded,
    release_stale_locks,
)
from app.domains.ingestion.ingest_common import IngestStorage
from app.domains.ingestion.runner import ingest_gdelt, ingest_reliefweb, ingest_rss

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('worker')


async def _record_ingestion_success(pool: asyncpg.Pool, source: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ingestion_runs (source, last_success_at, last_error, updated_at)
            VALUES ($1, now(), NULL, now())
            ON CONFLICT (source) DO UPDATE
            SET last_success_at=EXCLUDED.last_success_at, last_error=NULL, updated_at=now()
            """,
            source,
        )


async def _record_ingestion_error(pool: asyncpg.Pool, source: str, error: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ingestion_runs (source, last_success_at, last_error, updated_at)
            VALUES ($1, NULL, $2, now())
            ON CONFLICT (source) DO UPDATE
            SET last_error=EXCLUDED.last_error, updated_at=now()
            """,
            source,
            error[:2000],
        )


async def _cache_cleanup(pool: asyncpg.Pool) -> None:
    retention_days = int(os.getenv('ROUTE_SCORE_CACHE_RETENTION_DAYS', '30'))
    async with pool.acquire() as conn:
        await conn.execute(
            """
            DELETE FROM route_score_cache
            WHERE created_at < now() - make_interval(days => $1)
            """,
            retention_days,
        )


async def handle_job(pool: asyncpg.Pool, job: dict) -> None:
    job_type = job['job_type']
    payload = job.get('payload') or {}

    if job_type == 'ingest_gdelt':
        storage = IngestStorage(os.environ['DATABASE_URL'])
        await storage.connect()
        try:
            inserted = await ingest_gdelt(storage)
            await _record_ingestion_success(pool, 'gdelt')
            logger.info('ingest_gdelt inserted=%s payload=%s', inserted, payload)
        finally:
            await storage.close()
    elif job_type == 'ingest_reliefweb':
        storage = IngestStorage(os.environ['DATABASE_URL'])
        await storage.connect()
        try:
            inserted = await ingest_reliefweb(storage)
            await _record_ingestion_success(pool, 'reliefweb')
            logger.info('ingest_reliefweb inserted=%s payload=%s', inserted, payload)
        finally:
            await storage.close()
    elif job_type == 'ingest_rss':
        storage = IngestStorage(os.environ['DATABASE_URL'])
        await storage.connect()
        try:
            inserted = await ingest_rss(storage)
            await _record_ingestion_success(pool, 'rss')
            logger.info('ingest_rss inserted=%s payload=%s', inserted, payload)
        finally:
            await storage.close()
    elif job_type == 'cache_cleanup':
        await _cache_cleanup(pool)
        logger.info('cache_cleanup complete payload=%s', payload)
    else:
        raise RuntimeError(f'Unknown job_type: {job_type}')


async def run() -> None:
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise RuntimeError('DATABASE_URL must be set')
    pool = await asyncpg.create_pool(database_url)
    await ensure_job_queue_schema(pool)
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    logger.info('worker started id=%s', worker_id)
    last_reap = datetime.now(timezone.utc)
    try:
        while True:
            if (datetime.now(timezone.utc) - last_reap).total_seconds() >= 60:
                released = await release_stale_locks(pool)
                if released:
                    logger.info('released stale jobs=%s', released)
                last_reap = datetime.now(timezone.utc)

            job = await claim_next(pool, worker_id)
            if not job:
                await asyncio.sleep(0.75)
                continue

            job_id = job['id']
            logger.info('claimed job id=%s type=%s attempt=%s', job_id, job['job_type'], job['attempts'])
            try:
                await handle_job(pool, job)
                await mark_succeeded(pool, job_id)
                logger.info('job succeeded id=%s', job_id)
            except Exception as exc:  # noqa: BLE001
                if job['job_type'].startswith('ingest_'):
                    await _record_ingestion_error(pool, job['job_type'].replace('ingest_', ''), str(exc))
                logger.exception('job failed id=%s type=%s', job_id, job['job_type'])
                await mark_failed(pool, job_id, str(exc), retry=True)
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(run())
