from __future__ import annotations

import json
import logging
import hashlib
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

    def _normalize_route_payload(self, payload: Any) -> dict[str, Any] | None:
        if payload is None:
            return None
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            return None

        if isinstance(payload.get('geometry'), str):
            payload['geometry'] = json.loads(payload['geometry'])

        segment_scores = payload.get('segment_scores')
        if isinstance(segment_scores, list):
            for segment in segment_scores:
                if isinstance(segment, dict) and isinstance(segment.get('geometry'), str):
                    segment['geometry'] = json.loads(segment['geometry'])

        top_evidence = payload.get('top_evidence')
        if isinstance(top_evidence, dict):
            for bucket in ('events', 'alerts', 'hazards'):
                entries = top_evidence.get(bucket)
                if isinstance(entries, list):
                    for item in entries:
                        if isinstance(item, dict) and isinstance(item.get('geometry'), str):
                            item['geometry'] = json.loads(item['geometry'])
        return payload

    async def get_route_score_cache(self, route_hash: str, time_bucket: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT payload
                FROM route_score_cache
                WHERE route_hash = $1 AND time_bucket = $2
                """,
                route_hash,
                time_bucket,
            )
        if not row:
            return None
        return self._normalize_route_payload(row['payload'])

    async def set_route_score_cache(self, route_hash: str, time_bucket: str, payload: dict[str, Any]) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO route_score_cache (route_hash, time_bucket, payload, created_at)
                VALUES ($1, $2, $3::jsonb, NOW())
                ON CONFLICT (route_hash, time_bucket)
                DO UPDATE SET payload = EXCLUDED.payload, created_at = NOW()
                """,
                route_hash,
                time_bucket,
                json.dumps(payload),
            )

    async def score_route_corridor(
        self,
        geometry: dict[str, Any],
        lookback_hours: int,
        run_id: str,
        timestep: int,
        depart_time: datetime,
        arrive_by: datetime,
        buffer_meters: float = 15000,
    ) -> dict[str, Any]:
        route_json = json.dumps(geometry, sort_keys=True)
        cache_material = {
            'geometry': geometry,
            'lookback_hours': lookback_hours,
            'run_id': run_id,
            'timestep': timestep,
            'buffer_meters': buffer_meters,
            'depart_time': depart_time.isoformat(),
            'arrive_by': arrive_by.isoformat(),
        }
        route_hash = hashlib.sha256(json.dumps(cache_material, sort_keys=True).encode('utf-8')).hexdigest()
        time_bucket = datetime.utcnow().strftime('%Y%m%d%H')
        cached = await self.get_route_score_cache(route_hash, time_bucket)
        if cached:
            return cached

        async with self._pool.acquire() as conn:
            events = await conn.fetch(
                """
                WITH route AS (
                    SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 4326)::geography AS geom
                )
                SELECT id, title, event_type, severity, confidence, url, occurred_at,
                       ST_AsGeoJSON(geom::geometry)::json AS geometry,
                       ST_Distance(e.geom, r.geom) AS distance_m
                FROM events e
                CROSS JOIN route r
                WHERE e.occurred_at >= NOW() - make_interval(hours => $2)
                  AND ST_Intersects(ST_Buffer(r.geom, $3), e.geom)
                ORDER BY distance_m ASC
                LIMIT 25
                """,
                route_json,
                lookback_hours,
                buffer_meters,
            )
            hazards = await conn.fetch(
                """
                WITH route AS (
                    SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 4326)::geography AS geom
                )
                SELECT h.id, h.type, h.hazard_prob,
                       ST_AsGeoJSON(h.geom::geometry)::json AS geometry
                FROM hazards h
                CROSS JOIN route r
                WHERE h.run_id = $2 AND h.timestep = $3
                  AND ST_Intersects(ST_Buffer(r.geom, $4), h.geom)
                LIMIT 25
                """,
                route_json,
                run_id,
                timestep,
                buffer_meters,
            )
            alerts = await conn.fetch(
                """
                WITH route AS (
                    SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 4326)::geography AS geom
                )
                SELECT c.event_id, c.score, c.hazard_type, c.hazard_prob,
                       e.title, e.url,
                       ST_AsGeoJSON(c.geom::geometry)::json AS geometry
                FROM compound_alerts c
                JOIN events e ON e.id = c.event_id
                CROSS JOIN route r
                WHERE c.run_id = $2 AND c.timestep = $3
                  AND ST_Intersects(ST_Buffer(r.geom, $4), c.geom)
                ORDER BY c.score DESC
                LIMIT 25
                """,
                route_json,
                run_id,
                timestep,
                buffer_meters,
            )
            segs = await conn.fetch(
                """
                WITH route AS (
                    SELECT ST_SetSRID(ST_GeomFromGeoJSON($1), 4326)::geography AS geom
                ),
                points AS (
                    SELECT i,
                           ST_LineInterpolatePoint((r.geom::geometry), i / 20.0)::geography AS a,
                           ST_LineInterpolatePoint((r.geom::geometry), (i+1) / 20.0)::geography AS b
                    FROM route r, generate_series(0, 19) i
                ),
                segments AS (
                    SELECT
                        i,
                        ST_MakeLine(a::geometry, b::geometry)::geography AS segment_line,
                        ST_Buffer(ST_MakeLine(a::geometry, b::geometry)::geography, $4) AS segment_buffer
                    FROM points
                ),
                hazard_stats AS (
                    SELECT s.i, AVG(h.hazard_prob) * 100.0 AS hazard_avg
                    FROM segments s
                    LEFT JOIN hazards h ON h.run_id = $2
                        AND h.timestep = $3
                        AND ST_Intersects(s.segment_buffer, h.geom)
                    GROUP BY s.i
                ),
                event_stats AS (
                    SELECT s.i, AVG(e.severity * e.confidence) * 100.0 AS event_avg
                    FROM segments s
                    LEFT JOIN events e ON e.occurred_at >= NOW() - make_interval(hours => $5)
                        AND ST_Intersects(s.segment_buffer, e.geom)
                    GROUP BY s.i
                )
                SELECT s.i,
                    LEAST(100.0,
                        COALESCE(hs.hazard_avg, 0) * 0.6 +
                        COALESCE(es.event_avg, 0) * 0.4
                    ) AS score,
                    ST_AsGeoJSON(s.segment_line::geometry)::json AS geometry
                FROM segments s
                LEFT JOIN hazard_stats hs ON hs.i = s.i
                LEFT JOIN event_stats es ON es.i = s.i
                ORDER BY s.i ASC
                """,
                route_json,
                run_id,
                timestep,
                buffer_meters,
                lookback_hours,
            )

        weather_score = min(100.0, sum(float(h['hazard_prob']) for h in hazards) * 12.0)
        news_score = min(100.0, sum(float(e['severity']) * float(e['confidence']) for e in events) * 10.0)
        compound_score = min(100.0, sum(float(a['score']) for a in alerts) / max(1, len(alerts))) if alerts else 0.0
        total = min(100.0, weather_score * 0.4 + news_score * 0.3 + compound_score * 0.3)
        payload = {
            'total_risk': round(total, 3),
            'summary_risk': {
                'weather': round(weather_score, 3),
                'news': round(news_score, 3),
                'compound': round(compound_score, 3),
                'total': round(total, 3),
            },
            'segment_scores': [
                {
                    'segment_index': row['i'],
                    'score': float(row['score']),
                    'weather': float(row['score']) * 0.6,
                    'news': float(row['score']) * 0.25,
                    'compound': float(row['score']) * 0.15,
                    'geometry': row['geometry'],
                }
                for row in segs
            ],
            'top_evidence': {
                'events': [dict(id=str(r['id']), title=r['title'], event_type=r['event_type'], severity=r['severity'], confidence=r['confidence'], url=r['url'], occurred_at=r['occurred_at'].isoformat(), geometry=r['geometry']) for r in events[:10]],
                'alerts': [dict(id=str(r['event_id']), title=r['title'], score=r['score'], hazard_type=r['hazard_type'], hazard_prob=r['hazard_prob'], url=r['url'], geometry=r['geometry']) for r in alerts[:10]],
                'hazards': [dict(id=str(r['id']), type=r['type'], hazard_prob=r['hazard_prob'], geometry=r['geometry']) for r in hazards[:10]],
            },
        }
        await self.set_route_score_cache(route_hash, time_bucket, payload)
        return payload

    async def create_aoi(self, name: str, geometry: dict[str, Any], country_tags: list[str] | None = None) -> dict[str, Any]:
        country_tags = [tag.upper() for tag in (country_tags or [])]
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO aois (name, geom, country_tags)
                VALUES ($1, ST_SetSRID(ST_GeomFromGeoJSON($2), 4326)::geography, $3::text[])
                RETURNING id, name, country_tags, created_at, ST_AsGeoJSON(geom::geometry)::json AS geometry
                """,
                name,
                json.dumps(geometry),
                country_tags,
            )
        return dict(row)

    async def list_aois(self) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT a.id, a.name, a.country_tags, a.created_at,
                       ST_AsGeoJSON(a.geom::geometry)::json AS geometry,
                       s.captured_at AS last_updated,
                       COALESCE((s.summary_json->>'risk_score')::double precision, 0) AS current_risk_score
                FROM aois a
                LEFT JOIN LATERAL (
                    SELECT captured_at, summary_json
                    FROM aoi_snapshots
                    WHERE aoi_id = a.id
                    ORDER BY captured_at DESC
                    LIMIT 1
                ) s ON true
                ORDER BY a.created_at DESC
                """
            )
        return [dict(r) for r in rows]

    async def get_aoi(self, aoi_id: str) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, country_tags, created_at, ST_AsGeoJSON(geom::geometry)::json AS geometry
                FROM aois
                WHERE id = $1::uuid
                """,
                aoi_id,
            )
        return dict(row) if row else None

    async def delete_aoi(self, aoi_id: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute('DELETE FROM aois WHERE id = $1::uuid', aoi_id)
        return result.endswith('1')

    async def create_aoi_snapshot(self, aoi_id: str, run_id: str, timestep: int = 0) -> dict[str, Any]:
        async with self._pool.acquire() as conn:
            aoi = await conn.fetchrow('SELECT id, geom FROM aois WHERE id = $1::uuid', aoi_id)
            if not aoi:
                raise ValueError('aoi not found')

            event_rows = await conn.fetch(
                """
                SELECT e.id, e.title, e.event_type, e.severity, e.confidence, e.occurred_at
                FROM events e
                WHERE e.occurred_at >= NOW() - make_interval(hours => 168)
                  AND ST_Intersects(e.geom, $1)
                ORDER BY e.occurred_at DESC
                """,
                aoi['geom'],
            )
            hazard_rows = await conn.fetch(
                """
                SELECT type, hazard_prob
                FROM hazards
                WHERE run_id = $1 AND timestep = $2
                  AND ST_Intersects(geom, $3)
                """,
                run_id,
                timestep,
                aoi['geom'],
            )
            alert_rows = await conn.fetch(
                """
                SELECT c.event_id, c.score
                FROM compound_alerts c
                WHERE c.run_id = $1 AND c.timestep = $2
                  AND ST_Intersects(c.geom, $3)
                ORDER BY c.score DESC
                LIMIT 10
                """,
                run_id,
                timestep,
                aoi['geom'],
            )

            event_counts: dict[str, int] = {}
            for row in event_rows:
                event_counts[row['event_type']] = event_counts.get(row['event_type'], 0) + 1

            hazard_counts: dict[str, int] = {}
            max_intensity = 0.0
            hazard_score = 0.0
            for row in hazard_rows:
                hazard_counts[row['type']] = hazard_counts.get(row['type'], 0) + 1
                max_intensity = max(max_intensity, float(row['hazard_prob']))
                hazard_score += float(row['hazard_prob'])

            summary_json = {
                'event_counts_by_type': event_counts,
                'top_events': [
                    {
                        'id': str(row['id']),
                        'title': row['title'],
                        'event_type': row['event_type'],
                        'occurred_at': row['occurred_at'].isoformat(),
                    }
                    for row in event_rows[:10]
                ],
                'hazard_summary': {
                    'top_hazard_types': sorted(hazard_counts.items(), key=lambda item: item[1], reverse=True)[:5],
                    'max_intensity': max_intensity,
                },
                'top_compound_alerts': [
                    {'id': str(row['event_id']), 'score': float(row['score'])}
                    for row in alert_rows
                ],
                'risk_score': round(min(100.0, (hazard_score * 25.0) + (len(alert_rows) * 2.0)), 3),
            }
            digest = hashlib.sha256(json.dumps(summary_json, sort_keys=True).encode('utf-8')).hexdigest()
            new_snapshot = await conn.fetchrow(
                """
                INSERT INTO aoi_snapshots (aoi_id, run_id, timestep, captured_at, summary_json, hash)
                VALUES ($1::uuid, $2, $3, NOW(), $4::jsonb, $5)
                RETURNING id, aoi_id, run_id, timestep, captured_at, summary_json, hash
                """,
                aoi_id,
                run_id,
                timestep,
                json.dumps(summary_json),
                digest,
            )

            prev = await conn.fetchrow(
                """
                SELECT id, summary_json
                FROM aoi_snapshots
                WHERE aoi_id = $1::uuid AND id != $2::uuid
                ORDER BY captured_at DESC
                LIMIT 1
                """,
                aoi_id,
                new_snapshot['id'],
            )

            if prev:
                prev_summary = prev['summary_json']
                prev_events = {item['id'] for item in prev_summary.get('top_events', [])}
                curr_events = {item['id'] for item in summary_json.get('top_events', [])}
                prev_alerts = {item['id'] for item in prev_summary.get('top_compound_alerts', [])}
                curr_alerts = {item['id'] for item in summary_json.get('top_compound_alerts', [])}
                prev_count = sum((prev_summary.get('event_counts_by_type') or {}).values())
                curr_count = sum(event_counts.values())
                delta_json = {
                    'new_events': sorted(curr_events - prev_events),
                    'resolved_events': sorted(prev_events - curr_events),
                    'event_count_change': curr_count - prev_count,
                    'risk_change': round(summary_json['risk_score'] - float(prev_summary.get('risk_score', 0.0)), 3),
                    'new_alerts': sorted(curr_alerts - prev_alerts),
                    'resolved_alerts': sorted(prev_alerts - curr_alerts),
                }
                await conn.execute(
                    """
                    INSERT INTO aoi_deltas (aoi_id, from_snapshot_id, to_snapshot_id, delta_json)
                    VALUES ($1::uuid, $2::uuid, $3::uuid, $4::jsonb)
                    """,
                    aoi_id,
                    prev['id'],
                    new_snapshot['id'],
                    json.dumps(delta_json),
                )

        return dict(new_snapshot)

    async def list_aoi_changes(self, aoi_id: str, since_hours: int) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT d.id, d.aoi_id, d.from_snapshot_id, d.to_snapshot_id, d.created_at, d.delta_json,
                       s.summary_json AS to_summary
                FROM aoi_deltas d
                JOIN aoi_snapshots s ON s.id = d.to_snapshot_id
                WHERE d.aoi_id = $1::uuid
                  AND d.created_at >= NOW() - make_interval(hours => $2)
                ORDER BY d.created_at DESC
                """,
                aoi_id,
                since_hours,
            )
        output = []
        for row in rows:
            delta = dict(row['delta_json'])
            delta['human_readable'] = {
                'summary': f"{len(delta.get('new_events', []))} new events, {len(delta.get('resolved_events', []))} resolved, risk Δ {delta.get('risk_change', 0)}",
                'top_hazard_types': row['to_summary'].get('hazard_summary', {}).get('top_hazard_types', []),
            }
            output.append(
                {
                    'id': str(row['id']),
                    'aoi_id': str(row['aoi_id']),
                    'from_snapshot_id': str(row['from_snapshot_id']),
                    'to_snapshot_id': str(row['to_snapshot_id']),
                    'created_at': row['created_at'],
                    'delta': delta,
                }
            )
        return output

    async def refresh_all_aoi_snapshots(self, run_id: str, timestep: int = 0) -> list[dict[str, Any]]:
        aois = await self.list_aois()
        snapshots: list[dict[str, Any]] = []
        for aoi in aois:
            try:
                snapshots.append(await self.create_aoi_snapshot(str(aoi['id']), run_id=run_id, timestep=timestep))
            except Exception:
                logger.exception('Failed to create snapshot for aoi_id=%s', aoi['id'])
        return snapshots
