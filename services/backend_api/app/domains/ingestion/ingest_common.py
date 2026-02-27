from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from app.domains.ingestion.providers.common import EventSourceCreate, compute_geohash, compute_simhash64, hamming_distance, incident_key, normalize_text, time_bucket

SOURCE_PREFERENCE = {'reliefweb': 5, 'usgs': 4, 'planned': 3, 'rss': 2, 'gdelt': 1}


def pick_incident_candidate(simhash: int, candidates: list[asyncpg.Record], max_distance: int):
    best_id = None
    best_dist = 999
    for row in candidates:
        dist = hamming_distance(simhash, int(row['representative_simhash64']))
        if dist < best_dist:
            best_dist = dist
            best_id = row['id']
    if best_id is None or best_dist > max_distance:
        return None
    return best_id


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

    async def upsert_event_source_and_incident(
        self,
        event: EventSourceCreate,
        *,
        geohash_precision: int,
        bucket_minutes: int,
        dedup_window_hours: int,
        simhash_strong_max_dist: int,
    ) -> None:
        normalized = normalize_text(event.title, event.description)
        simhash = compute_simhash64(normalized)
        geoh = compute_geohash(event.lat, event.lon, geohash_precision)
        published_at = event.published_at
        occurred_at = event.occurred_at
        bucket = time_bucket(occurred_at or published_at, bucket_minutes)

        async with self._pool.acquire() as conn:
            source_row = await conn.fetchrow(
                """
                INSERT INTO event_sources (
                    source, source_event_id, title, description, url, published_at, occurred_at,
                    country, event_type, subtype, severity, confidence, geom, geohash, time_bucket,
                    normalized_text, simhash64, raw
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7,
                    $8, $9, $10, $11, $12, ST_SetSRID(ST_MakePoint($13, $14), 4326)::geography,
                    $15, $16, $17, $18, $19::jsonb
                )
                ON CONFLICT (source, source_event_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        occurred_at = EXCLUDED.occurred_at,
                        severity = EXCLUDED.severity,
                        confidence = EXCLUDED.confidence,
                        raw = EXCLUDED.raw
                RETURNING id
                """,
                event.source, event.source_event_id, event.title, event.description, event.url, published_at, occurred_at,
                event.country, event.event_type, event.subtype, event.severity, event.confidence, event.lon, event.lat,
                geoh, bucket, normalized, simhash, json.dumps(event.raw),
            )
            source_id = source_row['id']
            window_start = bucket - timedelta(hours=dedup_window_hours)
            window_end = bucket + timedelta(hours=dedup_window_hours)
            candidates = await conn.fetch(
                """
                SELECT id, representative_simhash64
                FROM incidents
                WHERE event_type = $1
                  AND time_bucket BETWEEN $2 AND $3
                  AND geohash = $4
                """,
                event.event_type, window_start, window_end, geoh,
            )
            best_id = pick_incident_candidate(simhash, candidates, simhash_strong_max_dist)

            if best_id is None:
                key = incident_key(event.event_type, event.subtype, geoh, bucket, normalized)
                existing = await conn.fetchrow('SELECT id FROM incidents WHERE incident_key=$1', key)
                if existing:
                    incident_id = existing['id']
                else:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO incidents (
                            canonical_title, canonical_summary, event_type, subtype, severity, confidence,
                            country, start_at, end_at, geom, geohash, time_bucket, incident_key, representative_simhash64
                        ) VALUES (
                            $1, NULL, $2, $3, $4, $5,
                            $6, $7, $8, ST_SetSRID(ST_MakePoint($9, $10), 4326)::geography,
                            $11, $12, $13, $14
                        ) RETURNING id
                        """,
                        event.title, event.event_type, event.subtype, event.severity, event.confidence,
                        event.country, occurred_at or published_at, (event.raw or {}).get('end_at'), event.lon, event.lat,
                        geoh, bucket, key, simhash,
                    )
                    incident_id = row['id']
            else:
                incident_id = best_id

            await conn.execute(
                """
                INSERT INTO incident_sources (incident_id, event_source_id)
                VALUES ($1, $2)
                ON CONFLICT DO NOTHING
                """,
                incident_id, source_id,
            )
            await self._recompute_incident(conn, incident_id)

    async def _recompute_incident(self, conn: asyncpg.Connection, incident_id) -> None:
        rows = await conn.fetch(
            """
            SELECT es.*, ST_Y(es.geom::geometry) AS lat, ST_X(es.geom::geometry) AS lon
            FROM incident_sources s
            JOIN event_sources es ON es.id = s.event_source_id
            WHERE s.incident_id = $1
            """,
            incident_id,
        )
        if not rows:
            return
        best_title_row = max(rows, key=lambda r: (SOURCE_PREFERENCE.get(r['source'], 0), r['confidence'], len(r['title'] or '')))
        severity = max(float(r['severity']) for r in rows)
        confidence = max(float(r['confidence']) for r in rows)
        start_at = min((r['occurred_at'] or r['published_at']) for r in rows)
        end_candidates = [(r['occurred_at'] or r['published_at']) for r in rows if (r['occurred_at'] or r['published_at']) is not None]
        end_at = max(end_candidates) if end_candidates else None
        centroid = await conn.fetchrow(
            """
            SELECT ST_AsText(ST_Centroid(ST_Collect(es.geom::geometry))) AS wkt
            FROM incident_sources s
            JOIN event_sources es ON es.id = s.event_source_id
            WHERE s.incident_id = $1
            """,
            incident_id,
        )
        await conn.execute(
            """
            UPDATE incidents
            SET canonical_title = $2,
                severity = $3,
                confidence = $4,
                start_at = $5,
                end_at = $6,
                representative_simhash64 = $7,
                country = COALESCE($8, country),
                geom = ST_GeogFromText($9),
                updated_at = NOW()
            WHERE id = $1
            """,
            incident_id, best_title_row['title'], severity, confidence, start_at, end_at,
            int(best_title_row['simhash64']), best_title_row['country'], centroid['wkt'],
        )


    async def upsert_provider_cache(self, provider: str, cache_key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO provider_cache (provider, cache_key, payload_json, fetched_at, ttl_seconds)
                VALUES ($1, $2, $3::jsonb, NOW(), $4)
                ON CONFLICT (provider, cache_key)
                DO UPDATE SET payload_json=EXCLUDED.payload_json, fetched_at=NOW(), ttl_seconds=EXCLUDED.ttl_seconds
                """,
                provider, cache_key, json.dumps(payload), ttl_seconds,
            )

    async def get_provider_cache(self, provider: str, cache_key: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT payload_json, fetched_at, ttl_seconds
                FROM provider_cache
                WHERE provider = $1 AND cache_key = $2
                """,
                provider, cache_key,
            )
        if row is None:
            return None
        return {'payload_json': row['payload_json'], 'fetched_at': row['fetched_at'], 'ttl_seconds': row['ttl_seconds']}

    async def get_provider_status(self, provider: str) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT provider, last_success_at, last_error_at, last_error, consecutive_failures, circuit_open_until
                FROM provider_status
                WHERE provider = $1
                """,
                provider,
            )
        if row is None:
            return {'provider': provider, 'consecutive_failures': 0, 'circuit_open_until': None}
        return dict(row)

    async def mark_provider_success(self, provider: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO provider_status(provider, last_success_at, consecutive_failures, circuit_open_until, last_error)
                VALUES ($1, NOW(), 0, NULL, NULL)
                ON CONFLICT (provider) DO UPDATE SET
                  last_success_at=NOW(),
                  consecutive_failures=0,
                  circuit_open_until=NULL,
                  last_error=NULL
                """,
                provider,
            )

    async def mark_provider_failure(self, provider: str, error: str, circuit_open_until: datetime | None) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO provider_status(provider, last_error_at, last_error, consecutive_failures, circuit_open_until)
                VALUES ($1, NOW(), $2, 1, $3)
                ON CONFLICT (provider) DO UPDATE SET
                  last_error_at=NOW(),
                  last_error=EXCLUDED.last_error,
                  consecutive_failures=provider_status.consecutive_failures + 1,
                  circuit_open_until=$3
                RETURNING consecutive_failures
                """,
                provider, error[:2000], circuit_open_until,
            )
        return int(row['consecutive_failures'])

    async def update_provider_circuit_open_until(self, provider: str, circuit_open_until: datetime | None) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE provider_status
                SET circuit_open_until = $2
                WHERE provider = $1
                """,
                provider,
                circuit_open_until,
            )

    async def list_ingestion_state(self) -> dict[str, str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch('SELECT source, updated_at FROM ingestion_state')
        return {r['source']: r['updated_at'].isoformat() for r in rows}
