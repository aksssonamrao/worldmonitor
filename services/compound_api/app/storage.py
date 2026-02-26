from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from typing import Any


class Storage:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def _exec(self, sql: str) -> str:
        env = os.environ.copy()
        env['DATABASE_URL'] = self.database_url
        proc = subprocess.run(['psql', self.database_url, '-t', '-A', '-c', sql], capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or 'psql query failed')
        return proc.stdout.strip()

    def insert_run(self, run_id: str, bbox: list[float], timesteps: list[int]) -> None:
        self._exec(f"INSERT INTO hazard_runs (run_id,bbox,timesteps,status,started_at,points_requested,points_fetched,cache_hits) VALUES ('{run_id}','{json.dumps(bbox)}'::jsonb,'{json.dumps(timesteps)}'::jsonb,'RUNNING',NOW(),0,0,0) ON CONFLICT (run_id) DO UPDATE SET status='RUNNING',started_at=NOW(),finished_at=NULL,error=NULL")

    def complete_run(self, run_id: str, status: str, stats: dict[str, Any], error: str | None = None) -> None:
        err = (error or '').replace("'", "''")
        error_sql = 'NULL' if not error else "'" + err + "'"
        self._exec(f"UPDATE hazard_runs SET status='{status}',finished_at=NOW(),points_requested={int(stats.get('points_requested',0))},points_fetched={int(stats.get('points_fetched',0))},cache_hits={int(stats.get('cache_hits',0))},error={error_sql} WHERE run_id='{run_id}'")

    def clear_hazards(self, run_id: str) -> None:
        self._exec(f"DELETE FROM hazards WHERE run_id='{run_id}'")

    def upsert_sample(self, lat: float, lon: float, record: dict[str, Any]) -> None:
        ts = record['forecast_ts'].isoformat()
        self._exec(
            f"""
            INSERT INTO weather_samples (lat,lon,forecast_ts,fetched_at,wind_kph,precip_mm_hr,temp_c,humidity)
            VALUES ({lat},{lon},'{ts}',NOW(),{record['wind_kph']},{record['precip_mm_hr']},{record['temp_c']},{record.get('humidity','NULL')})
            ON CONFLICT (lat,lon,forecast_ts) DO UPDATE SET fetched_at=EXCLUDED.fetched_at,wind_kph=EXCLUDED.wind_kph,precip_mm_hr=EXCLUDED.precip_mm_hr,temp_c=EXCLUDED.temp_c,humidity=EXCLUDED.humidity
            """
        )

    def get_sample(self, lat: float, lon: float, forecast_ts: datetime, ttl_min: int) -> dict[str, Any] | None:
        ts = forecast_ts.isoformat()
        out = self._exec(f"SELECT row_to_json(t) FROM (SELECT forecast_ts,wind_kph,precip_mm_hr,temp_c,humidity FROM weather_samples WHERE lat={lat} AND lon={lon} AND forecast_ts='{ts}' AND fetched_at >= NOW() - interval '{ttl_min} minutes' LIMIT 1) t")
        if not out:
            return None
        row = json.loads(out)
        row['forecast_ts'] = datetime.fromisoformat(row['forecast_ts'].replace('Z', '+00:00'))
        return row

    def insert_hazard(self, run_id: str, timestep: int, hazard_type: str, prob: float, forecast_ts: datetime, bbox: list[float], thresholds: dict[str, float], wkt: str) -> None:
        wkt_esc = wkt.replace("'", "''")
        self._exec(f"INSERT INTO hazards (id,run_id,timestep,forecast_ts,type,hazard_prob,provider,bbox,thresholds,generated_at,geom) VALUES (gen_random_uuid(),'{run_id}',{timestep},'{forecast_ts.isoformat()}','{hazard_type}',{prob},'google_weather','{json.dumps(bbox)}'::jsonb,'{json.dumps(thresholds)}'::jsonb,NOW(),ST_GeogFromText('{wkt_esc}'))")

    def list_hazards(self, run_id: str, timestep: int) -> list[dict[str, Any]]:
        out = self._exec(f"SELECT COALESCE(json_agg(row_to_json(t)),'[]'::json) FROM (SELECT type,hazard_prob,forecast_ts,provider,generated_at,ST_AsGeoJSON(geom::geometry)::json as geometry FROM hazards WHERE run_id='{run_id}' AND timestep={timestep} ORDER BY generated_at DESC) t")
        rows = json.loads(out or '[]')
        for r in rows:
            r['forecast_ts'] = datetime.fromisoformat(r['forecast_ts'].replace('Z', '+00:00'))
            r['generated_at'] = datetime.fromisoformat(r['generated_at'].replace('Z', '+00:00'))
        return rows

    def latest_run(self) -> dict[str, Any] | None:
        out = self._exec("SELECT row_to_json(t) FROM (SELECT run_id,bbox,timesteps,status,started_at,finished_at,points_requested,points_fetched,cache_hits,error FROM hazard_runs ORDER BY started_at DESC LIMIT 1) t")
        return json.loads(out) if out else None
