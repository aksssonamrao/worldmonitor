from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import asyncpg


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
              run_id UUID PRIMARY KEY,
              status TEXT NOT NULL CHECK (status IN ('queued','running','failed','succeeded')),
              request JSONB NOT NULL DEFAULT '{}'::jsonb,
              outputs JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS agent_run_steps (
              id BIGSERIAL PRIMARY KEY,
              run_id UUID NOT NULL REFERENCES agent_runs(run_id) ON DELETE CASCADE,
              step_name TEXT NOT NULL,
              status TEXT NOT NULL CHECK (status IN ('running','failed','completed')),
              output JSONB NOT NULL DEFAULT '{}'::jsonb,
              error TEXT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS idx_agent_run_steps_run_id ON agent_run_steps(run_id, id);
            """
        )


async def create_run(pool: asyncpg.Pool, request: dict[str, Any]) -> str:
    run_id = str(uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO agent_runs (run_id, status, request, outputs, created_at, updated_at) VALUES ($1::uuid, 'queued', $2::jsonb, '{}'::jsonb, now(), now())",
            run_id,
            json.dumps(request),
        )
    return run_id


async def update_run_status(pool: asyncpg.Pool, run_id: str, status: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE agent_runs SET status=$2, updated_at=now() WHERE run_id=$1::uuid", run_id, status)


async def upsert_output(pool: asyncpg.Pool, run_id: str, key: str, value: dict[str, Any]) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE agent_runs
            SET outputs = jsonb_set(outputs, $2::text[], $3::jsonb, true), updated_at=now()
            WHERE run_id=$1::uuid
            """,
            run_id,
            [key],
            json.dumps(value),
        )


async def create_step(pool: asyncpg.Pool, run_id: str, step_name: str) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO agent_run_steps (run_id, step_name, status, output, created_at, updated_at) VALUES ($1::uuid, $2, 'running', '{}'::jsonb, now(), now()) RETURNING id",
            run_id,
            step_name,
        )
    return int(row['id'])


async def finish_step(pool: asyncpg.Pool, step_id: int, status: str, output: dict[str, Any] | None = None, error: str | None = None) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE agent_run_steps SET status=$2, output=$3::jsonb, error=$4, updated_at=now() WHERE id=$1",
            step_id,
            status,
            json.dumps(output or {}),
            error,
        )


async def get_run(pool: asyncpg.Pool, run_id: str) -> dict[str, Any] | None:
    async with pool.acquire() as conn:
        run = await conn.fetchrow("SELECT run_id::text, status, request, outputs, created_at, updated_at FROM agent_runs WHERE run_id=$1::uuid", run_id)
        if not run:
            return None
        steps = await conn.fetch(
            "SELECT id, step_name, status, output, error, created_at, updated_at FROM agent_run_steps WHERE run_id=$1::uuid ORDER BY id ASC",
            run_id,
        )
    return {
        'run_id': run['run_id'],
        'status': run['status'],
        'request': dict(run['request']),
        'outputs': dict(run['outputs']),
        'steps': [
            {
                'id': int(item['id']),
                'step_name': item['step_name'],
                'status': item['status'],
                'output': dict(item['output']),
                'error': item['error'],
            }
            for item in steps
        ],
    }
