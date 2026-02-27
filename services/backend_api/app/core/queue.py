from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _backoff_seconds(attempts: int) -> int:
    base = 5 * (2 ** max(0, attempts - 1))
    capped = min(base, 600)
    jitter = random.randint(0, max(1, int(capped * 0.2)))
    return min(600, capped + jitter)


async def ensure_job_queue_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_queue (
              id UUID PRIMARY KEY,
              job_type TEXT NOT NULL,
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','dead')) DEFAULT 'queued',
              attempts INT NOT NULL DEFAULT 0,
              max_attempts INT NOT NULL DEFAULT 5,
              run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
              locked_at TIMESTAMPTZ NULL,
              locked_by TEXT NULL,
              last_error TEXT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_job_queue_status_runafter ON job_queue (status, run_after);
            CREATE INDEX IF NOT EXISTS idx_job_queue_locked_at ON job_queue (locked_at);
            CREATE INDEX IF NOT EXISTS idx_job_queue_job_type ON job_queue (job_type);

            CREATE TABLE IF NOT EXISTS ingestion_runs (
              source TEXT PRIMARY KEY,
              last_success_at TIMESTAMPTZ NULL,
              last_error TEXT NULL,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )


async def enqueue(
    pool: asyncpg.Pool,
    job_type: str,
    payload: dict[str, Any],
    run_after: datetime | None,
    max_attempts: int = 5,
) -> UUID:
    job_id = uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO job_queue (id, job_type, payload, status, attempts, max_attempts, run_after, created_at, updated_at)
            VALUES ($1, $2, $3::jsonb, 'queued', 0, $4, COALESCE($5, now()), now(), now())
            """,
            job_id,
            job_type,
            payload,
            max_attempts,
            run_after,
        )
    return job_id


async def claim_next(pool: asyncpg.Pool, worker_id: str) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            WITH candidate AS (
              SELECT id
              FROM job_queue
              WHERE status = 'queued'
                AND run_after <= now()
              ORDER BY run_after ASC, created_at ASC
              FOR UPDATE SKIP LOCKED
              LIMIT 1
            )
            UPDATE job_queue j
            SET status='running',
                locked_at=now(),
                locked_by=$1,
                attempts=attempts+1,
                updated_at=now()
            FROM candidate
            WHERE j.id = candidate.id
            RETURNING j.*
            """,
            worker_id,
        )
    return dict(row) if row else None


async def mark_succeeded(pool: asyncpg.Pool, job_id: UUID) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE job_queue
            SET status='succeeded', locked_at=NULL, locked_by=NULL, updated_at=now()
            WHERE id=$1
            """,
            job_id,
        )


async def mark_failed(pool: asyncpg.Pool, job_id: UUID, error: str, retry: bool) -> None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT attempts, max_attempts FROM job_queue WHERE id=$1", job_id)
        if not row:
            return
        attempts = int(row['attempts'])
        max_attempts = int(row['max_attempts'])
        will_retry = retry and attempts < max_attempts
        if will_retry:
            delay_s = _backoff_seconds(attempts)
            run_after = utcnow() + timedelta(seconds=delay_s)
            await conn.execute(
                """
                UPDATE job_queue
                SET status='queued', run_after=$2, locked_at=NULL, locked_by=NULL, last_error=$3, updated_at=now()
                WHERE id=$1
                """,
                job_id,
                run_after,
                error[:4000],
            )
        else:
            await conn.execute(
                """
                UPDATE job_queue
                SET status='dead', locked_at=NULL, locked_by=NULL, last_error=$2, updated_at=now()
                WHERE id=$1
                """,
                job_id,
                error[:4000],
            )


async def release_stale_locks(pool: asyncpg.Pool, stale_minutes: int = 15) -> int:
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE job_queue
            SET status='queued', run_after=now(), locked_at=NULL, locked_by=NULL, updated_at=now()
            WHERE status='running'
              AND locked_at IS NOT NULL
              AND locked_at < now() - make_interval(mins => $1)
            """,
            stale_minutes,
        )
    return int(result.split()[-1])


async def stats(pool: asyncpg.Pool) -> dict[str, Any]:
    async with pool.acquire() as conn:
        counts = await conn.fetch("SELECT status, count(*)::int AS count FROM job_queue GROUP BY status")
        oldest = await conn.fetchrow("SELECT run_after FROM job_queue WHERE status='queued' ORDER BY run_after ASC LIMIT 1")
        last_dead = await conn.fetchrow(
            "SELECT last_error FROM job_queue WHERE status='dead' ORDER BY updated_at DESC LIMIT 1"
        )
    return {
        'counts': {row['status']: row['count'] for row in counts},
        'oldest_queued_run_after': oldest['run_after'].isoformat() if oldest and oldest['run_after'] else None,
        'last_dead_error': (last_dead['last_error'] or '')[:200] if last_dead else None,
    }
