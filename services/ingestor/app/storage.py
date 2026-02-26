from __future__ import annotations

import json
from typing import Any

import asyncpg


class IngestStorage:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool: asyncpg.Pool | None = None

    @property
    def _pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise RuntimeError('Storage not connected. Call connect() first.')
        return self.pool

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.database_url)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def get_cursor(self, source: str) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow('SELECT cursor FROM ingestion_state WHERE source=$1', source)
            return dict(row['cursor']) if row else {}

    async def upsert_cursor(self, source: str, cursor: dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ingestion_state (source, cursor, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (source) DO UPDATE SET cursor=EXCLUDED.cursor, updated_at=NOW()
                """,
                source,
                json.dumps(cursor),
            )

    async def insert_event(self, event: dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO events (
                    source, source_event_id, title, description, url, event_type, severity,
                    confidence, country, region, occurred_at, ingested_at, geom, raw
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7,
                    $8, $9, $10, $11, NOW(), ST_SetSRID(ST_MakePoint($12, $13), 4326)::geography, $14::jsonb
                )
                ON CONFLICT (source, source_event_id) DO NOTHING
                """,
                event['source'], event['source_event_id'], event['title'], event.get('description'), event['url'], event['event_type'],
                event['severity'], event['confidence'], event.get('country'), event.get('region'), event['occurred_at'], event['lon'], event['lat'], json.dumps(event.get('raw', {})),
            )

    async def list_ingestion_state(self) -> dict[str, str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch('SELECT source, updated_at FROM ingestion_state')
        return {r['source']: r['updated_at'].isoformat() for r in rows}
