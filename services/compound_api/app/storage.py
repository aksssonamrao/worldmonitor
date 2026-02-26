from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


class Storage:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(self.database_url)

    async def close(self) -> None:
        if self._pool:
            try:
                await self._pool.close()
            except Exception:
                logger.exception('Error closing storage pool')
            self._pool = None

    async def insert_run(self, run_id: str, bbox: list[float], timesteps: list[int]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO hazard_runs
                    (run_id, bbox, timesteps, status, started_at,
                     points_requested, points_fetched, cache_hits)
                VALUES ($1, $2::jsonb, $3::jsonb, 'RUNNING', NOW(), 0, 0, 0)
                ON CONFLICT (run_id) DO UPDATE
                    SET status = 'RUNNING', started_at = NOW(),
                        finished_at = NULL, error = NULL
                """,
                run_id, json.dumps(bbox), json.dumps(timesteps),
            )

    async def complete_run(self, run_id: str, status: str, stats: dict[str, Any], error: str | None = None) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE hazard_runs
                SET status = $1, finished_at = NOW(),
                    points_requested = $2, points_fetched = $3, cache_hits = $4,
                    error = $5
                WHERE run_id = $6
                """,
                status,
                int(stats.get('points_requested', 0)),
                int(stats.get('points_fetched', 0)),
                int(stats.get('cache_hits', 0)),
                error,
                run_id,
            )

    async def clear_hazards(self, run_id: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute('DELETE FROM hazards WHERE run_id = $1', run_id)

    async def upsert_sample(self, lat: float, lon: float, record: dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO weather_samples
                    (lat, lon, forecast_ts, fetched_at, wind_kph, precip_mm_hr, temp_c, humidity)
                VALUES ($1, $2, $3, NOW(), $4, $5, $6, $7)
                ON CONFLICT (lat, lon, forecast_ts) DO UPDATE
                    SET fetched_at = EXCLUDED.fetched_at,
                        wind_kph = EXCLUDED.wind_kph,
                        precip_mm_hr = EXCLUDED.precip_mm_hr,
                        temp_c = EXCLUDED.temp_c,
                        humidity = EXCLUDED.humidity
                """,
                lat, lon, record['forecast_ts'],
                record['wind_kph'], record['precip_mm_hr'], record['temp_c'],
                record.get('humidity'),
            )

    async def get_sample(self, lat: float, lon: float, forecast_ts: datetime, ttl_min: int) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT forecast_ts, wind_kph, precip_mm_hr, temp_c, humidity
                FROM weather_samples
                WHERE lat = $1 AND lon = $2 AND forecast_ts = $3
                  AND fetched_at >= NOW() - make_interval(mins => $4)
                LIMIT 1
                """,
                lat, lon, forecast_ts, str(ttl_min),
            )
        if row is None:
            return None
        return {
            'forecast_ts': row['forecast_ts'],
            'wind_kph': row['wind_kph'],
            'precip_mm_hr': row['precip_mm_hr'],
            'temp_c': row['temp_c'],
            'humidity': row['humidity'],
        }

    async def insert_hazard(
        self,
        run_id: str,
        timestep: int,
        hazard_type: str,
        prob: float,
        forecast_ts: datetime,
        bbox: list[float],
        thresholds: dict[str, float],
        wkt: str,
    ) -> None:
        if not isinstance(wkt, str) or not wkt.strip():
            raise ValueError('wkt must be a non-empty string')
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO hazards
                        (id, run_id, timestep, forecast_ts, type, hazard_prob,
                         provider, bbox, thresholds, generated_at, geom)
                    VALUES (
                        gen_random_uuid(), $1, $2, $3, $4, $5,
                        'google_weather', $6::jsonb, $7::jsonb,
                        NOW(), ST_GeogFromText($8)
                    )
                    """,
                    run_id, timestep, forecast_ts, hazard_type, prob,
                    json.dumps(bbox), json.dumps(thresholds), wkt,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to insert hazard for run_id '{run_id}', timestep {timestep}: {exc}"
                ) from exc

    async def list_hazards(self, run_id: str, timestep: int) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT type, hazard_prob, forecast_ts, provider, generated_at,
                       ST_AsGeoJSON(geom::geometry)::json AS geometry
                FROM hazards
                WHERE run_id = $1 AND timestep = $2
                ORDER BY generated_at DESC
                """,
                run_id, timestep,
            )
        result = []
        for r in rows:
            item = dict(r)
            item['geometry'] = json.loads(item['geometry']) if isinstance(item['geometry'], str) else item['geometry']
            result.append(item)
        return result

    async def latest_run(self) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT run_id, bbox, timesteps, status, started_at, finished_at,
                       points_requested, points_fetched, cache_hits, error
                FROM hazard_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
        if row is None:
            return None
        return dict(row)
