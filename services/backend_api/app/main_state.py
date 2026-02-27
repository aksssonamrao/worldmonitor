from __future__ import annotations

import asyncpg

_db_pool: asyncpg.Pool | None = None


def set_db_pool(pool: asyncpg.Pool) -> None:
    global _db_pool
    _db_pool = pool


def get_db_pool() -> asyncpg.Pool:
    if _db_pool is None:
        raise RuntimeError('Database pool is not initialized')
    return _db_pool
