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

    async def list_events(self, since_hours: int, event_types: list[str] | None = None, bbox: list[float] | None = None) -> list[dict[str, Any]]:
        filters = ["occurred_at >= NOW() - make_interval(hours => $1)"]
        params: list[Any] = [since_hours]
        if event_types:
            params.append(event_types)
            filters.append(f"event_type = ANY(${len(params)})")
        if bbox:
            params.extend(bbox)
            start = len(params) - 3
            filters.append(
                f"ST_Intersects(geom, ST_MakeEnvelope(${start}, ${start+1}, ${start+2}, ${start+3}, 4326)::geography)"
            )
        where = ' AND '.join(filters)
        query = f"""
            SELECT id, source, source_event_id, title, description, url, event_type, severity, confidence,
                   country, region, occurred_at, ingested_at, raw,
                   ST_AsGeoJSON(geom::geometry)::json AS geometry
            FROM events
            WHERE {where}
            ORDER BY occurred_at DESC
            LIMIT 500
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        out = []
        for row in rows:
            item = dict(row)
            item['geometry'] = json.loads(item['geometry']) if isinstance(item['geometry'], str) else item['geometry']
            out.append(item)
        return out

    async def get_event(self, event_id: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, source, source_event_id, title, description, url, event_type, severity, confidence,
                       country, region, occurred_at, ingested_at, raw,
                       ST_AsGeoJSON(geom::geometry)::json AS geometry
                FROM events
                WHERE id = $1::uuid
                """,
                event_id,
            )
        if row is None:
            return None
        item = dict(row)
        item['geometry'] = json.loads(item['geometry']) if isinstance(item['geometry'], str) else item['geometry']
        return item

    async def list_ingestion_state(self) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT source, cursor, updated_at FROM ingestion_state")
        return {row['source']: {'cursor': row['cursor'], 'updated_at': row['updated_at'].isoformat()} for row in rows}

    async def detect_compound_alerts(
        self,
        run_id: str,
        timestep: int,
        lookback_hours: int,
        score_threshold: float,
        event_weights: dict[str, float],
        bbox: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        bbox_filter = ''
        params: list[Any] = [run_id, timestep, lookback_hours]
        if bbox:
            params.extend(bbox)
            idx = len(params) - 3
            bbox_filter = f" AND ST_Intersects(e.geom, ST_MakeEnvelope(${idx}, ${idx+1}, ${idx+2}, ${idx+3}, 4326)::geography)"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT e.id as event_id, e.title, e.url, e.event_type, e.severity, e.confidence,
                       e.country, e.occurred_at,
                       h.type as hazard_type, h.hazard_prob, h.forecast_ts,
                       ST_AsGeoJSON(e.geom::geometry)::json AS geometry
                FROM events e
                JOIN hazards h ON h.run_id = $1 AND h.timestep = $2
                WHERE e.occurred_at >= NOW() - make_interval(hours => $3)
                  AND ST_Intersects(h.geom, e.geom)
                  {bbox_filter}
                """,
                *params,
            )

            best_by_event: dict[str, dict[str, Any]] = {}
            for row in rows:
                event_type = row['event_type']
                base = row['severity'] * row['confidence'] * row['hazard_prob']
                score = max(0.0, min(100.0, base * event_weights.get(event_type, 1.0) * 100.0))
                payload = {
                    'event_id': str(row['event_id']),
                    'title': row['title'],
                    'url': row['url'],
                    'event_type': event_type,
                    'hazard_type': row['hazard_type'],
                    'hazard_prob': row['hazard_prob'],
                    'forecast_ts': row['forecast_ts'],
                    'score': score,
                    'country': row['country'],
                    'occurred_at': row['occurred_at'],
                    'geometry': row['geometry'],
                    'details': {
                        'base': base,
                        'event_weight': event_weights.get(event_type, 1.0),
                        'severity': row['severity'],
                        'confidence': row['confidence'],
                        'hazard_prob': row['hazard_prob'],
                        'other_hazards': [],
                    },
                }
                current = best_by_event.get(payload['event_id'])
                if current is None or payload['score'] > current['score']:
                    if current is not None:
                        payload['details']['other_hazards'] = current['details']['other_hazards'] + [
                            {'hazard_type': current['hazard_type'], 'hazard_prob': current['hazard_prob'], 'score': current['score']}
                        ]
                    best_by_event[payload['event_id']] = payload
                else:
                    current['details']['other_hazards'].append({'hazard_type': payload['hazard_type'], 'hazard_prob': payload['hazard_prob'], 'score': payload['score']})

            results = [item for item in best_by_event.values() if item['score'] >= score_threshold]
            async with conn.transaction():
                await conn.execute('DELETE FROM compound_alerts WHERE run_id = $1 AND timestep = $2', run_id, timestep)
                for alert in results:
                    geometry = alert.get('geometry')
                    if geometry is None:
                        raise RuntimeError(f"Missing geometry for alert event_id={alert.get('event_id')}")
                    try:
                        geometry_json = json.dumps(geometry)
                    except (TypeError, ValueError) as exc:
                        raise RuntimeError(f"Invalid geometry for alert event_id={alert.get('event_id')}: {exc}") from exc
                    await conn.execute(
                        """
                        INSERT INTO compound_alerts (run_id, timestep, score, event_id, hazard_type, hazard_prob, forecast_ts, geom, details)
                        VALUES ($1, $2, $3, $4::uuid, $5, $6, $7, ST_SetSRID(ST_GeomFromGeoJSON($8), 4326)::geography, $9::jsonb)
                        ON CONFLICT (run_id, timestep, event_id)
                        DO UPDATE SET score = EXCLUDED.score, hazard_type = EXCLUDED.hazard_type,
                                      hazard_prob = EXCLUDED.hazard_prob, forecast_ts = EXCLUDED.forecast_ts,
                                      geom = EXCLUDED.geom, details = EXCLUDED.details, created_at = NOW()
                        """,
                        run_id,
                        timestep,
                        alert['score'],
                        alert['event_id'],
                        alert['hazard_type'],
                        alert['hazard_prob'],
                        alert['forecast_ts'],
                        geometry_json,
                        json.dumps(alert['details']),
                    )
        return sorted(results, key=lambda x: x['score'], reverse=True)
