from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import asyncpg

from app.core.queue import enqueue, ensure_job_queue_schema


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {'1', 'true', 'yes', 'on'}


async def run() -> None:
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        raise RuntimeError('DATABASE_URL must be set')

    ingest_interval_min = int(os.getenv('INGEST_INTERVAL_MINUTES', '15'))
    gdelt_enabled = _env_bool('GDELT_ENABLED', True)
    reliefweb_enabled = _env_bool('RELIEFWEB_ENABLED', True)
    rss_enabled = _env_bool('RSS_ENABLED', False)

    pool = await asyncpg.create_pool(database_url)
    await ensure_job_queue_schema(pool)

    last_cleanup_hour = None
    try:
        while True:
            now = datetime.now(timezone.utc)
            if gdelt_enabled:
                await enqueue(pool, 'ingest_gdelt', {'scheduled_at': now.isoformat()}, now)
            if reliefweb_enabled:
                await enqueue(pool, 'ingest_reliefweb', {'scheduled_at': now.isoformat()}, now)
            if rss_enabled:
                await enqueue(pool, 'ingest_rss', {'scheduled_at': now.isoformat()}, now)

            hour_key = now.strftime('%Y%m%d%H')
            if hour_key != last_cleanup_hour:
                await enqueue(pool, 'cache_cleanup', {'scheduled_at': now.isoformat()}, now)
                last_cleanup_hour = hour_key

            await asyncio.sleep(max(30, ingest_interval_min * 60))
    finally:
        await pool.close()


if __name__ == '__main__':
    asyncio.run(run())
