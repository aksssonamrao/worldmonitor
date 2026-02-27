from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import cos, radians

from fastapi import HTTPException


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _circle_wkt(lon: float, lat: float, radius_deg: float, segments: int = 12) -> str:
    from math import pi, sin, cos

    pts = []
    for i in range(segments + 1):
        a = 2 * pi * i / segments
        pts.append(f"{lon + radius_deg * cos(a)} {lat + radius_deg * sin(a)}")
    return f"POLYGON(({','.join(pts)}))"


class HazardGenerator:
    def __init__(self, settings, storage, weather_client):
        self.settings = settings
        self.storage = storage
        self.weather_client = weather_client

    def _grid_points(self, bbox: list[float]) -> tuple[list[tuple[float, float]], float]:
        min_lon, min_lat, max_lon, max_lat = bbox
        area = (max_lon - min_lon) * (max_lat - min_lat)
        if area > self.settings.max_bbox_area_deg2:
            raise HTTPException(status_code=400, detail='bbox too large')

        spacing_km = self.settings.hazard_grid_km
        max_iterations = 50
        for iteration in range(max_iterations):
            mean_lat = (min_lat + max_lat) / 2
            lat_deg = spacing_km / 111.0
            lon_deg = spacing_km / (111.0 * max(0.1, cos(radians(mean_lat))))
            points = []
            lat = min_lat
            while lat <= max_lat + 1e-9:
                lon = min_lon
                while lon <= max_lon + 1e-9:
                    points.append((round(lat, 4), round(lon, 4)))
                    lon += lon_deg
                lat += lat_deg
            if len(points) <= self.settings.hazard_max_points:
                return points, spacing_km
            spacing_km *= 1.25
        raise RuntimeError(
            f'_grid_points exceeded {max_iterations} iterations without reducing points '
            f'below hazard_max_points={self.settings.hazard_max_points}; '
            f'final spacing_km={spacing_km:.2f}'
        )

    async def generate(self, run_id: str, bbox: list[float], timesteps: list[int], hazard_types: list[str]):
        await self.storage.insert_run(run_id, bbox, timesteps)
        stats = {'points_requested': 0, 'points_fetched': 0, 'cache_hits': 0}
        polygons_written: dict[str, int] = defaultdict(int)
        now = datetime.now(timezone.utc)
        points, spacing_km = self._grid_points(bbox)
        stats['points_requested'] = len(points)

        try:
            samples_by_hour = defaultdict(list)
            base_hour = now.replace(minute=0, second=0, microsecond=0)
            expected_tss = [base_hour + timedelta(hours=h) for h in range(self.settings.forecast_hours + 1)]
            for lat, lon in points:
                # Check cache for all expected forecast timestamps BEFORE calling the API.
                cached_for_point: dict = {}
                for ts in expected_tss:
                    sample = await self.storage.get_sample(lat, lon, ts, self.settings.hazard_cache_ttl_min)
                    if sample:
                        cached_for_point[ts] = sample

                if len(cached_for_point) == len(expected_tss):
                    # All needed samples are already cached; skip the upstream API call.
                    stats['cache_hits'] += len(cached_for_point)
                    for ts, rec in cached_for_point.items():
                        samples_by_hour[ts].append((lat, lon, rec))
                else:
                    # Some samples are missing; fetch from the upstream API and cache results.
                    weather_result = await self.weather_client.fetch_hourly(lat, lon, self.settings.forecast_hours)
                    fetched_records = weather_result['rows']
                    if fetched_records:
                        stats['points_fetched'] += 1
                    for record in fetched_records:
                        ts = record['forecast_ts']
                        if ts in cached_for_point:
                            # This timestamp was already in cache (partial coverage); prefer cached copy.
                            stats['cache_hits'] += 1
                            samples_by_hour[ts].append((lat, lon, cached_for_point[ts]))
                        else:
                            await self.storage.upsert_sample(lat, lon, record)
                            samples_by_hour[ts].append((lat, lon, record))

            await self.storage.clear_hazards(run_id)
            for timestep in timesteps:
                target_ts = now + timedelta(hours=timestep)
                if not samples_by_hour:
                    continue
                target_key = min(samples_by_hour.keys(), key=lambda ts: abs((ts - target_ts).total_seconds()))
                for hazard_type in hazard_types:
                    probs = []
                    for lat, lon, rec in samples_by_hour[target_key]:
                        prob = 0.0
                        if hazard_type == 'WIND' and rec['wind_kph'] >= self.settings.wind_threshold_kph:
                            prob = clamp((rec['wind_kph'] - self.settings.wind_threshold_kph) / (self.settings.wind_max_kph - self.settings.wind_threshold_kph))
                        if hazard_type == 'RAIN' and rec['precip_mm_hr'] >= self.settings.rain_threshold_mm_hr:
                            prob = clamp((rec['precip_mm_hr'] - self.settings.rain_threshold_mm_hr) / (self.settings.rain_max_mm_hr - self.settings.rain_threshold_mm_hr))
                        if hazard_type == 'HEAT' and rec['temp_c'] >= self.settings.heat_threshold_c:
                            prob = clamp((rec['temp_c'] - self.settings.heat_threshold_c) / (self.settings.heat_max_c - self.settings.heat_threshold_c))
                        if prob > 0:
                            probs.append(prob)
                            wkt = _circle_wkt(lon, lat, (spacing_km / 2) / 111.0)
                            await self.storage.insert_hazard(
                                run_id, timestep, hazard_type, prob, target_key, bbox,
                                {
                                    'WIND_THRESHOLD_KPH': self.settings.wind_threshold_kph,
                                    'RAIN_THRESHOLD_MM_HR': self.settings.rain_threshold_mm_hr,
                                    'HEAT_THRESHOLD_C': self.settings.heat_threshold_c,
                                },
                                wkt,
                            )
                            polygons_written[f'{hazard_type}:{timestep}'] += 1

            await self.storage.complete_run(run_id, 'SUCCESS', stats)
            return {'run_id': run_id, 'status': 'SUCCESS', **stats, 'polygons_written_per_type_timestep': polygons_written}
        except Exception as exc:
            await self.storage.complete_run(run_id, 'FAILED', stats, str(exc))
            return {'run_id': run_id, 'status': 'FAILED', **stats, 'error': str(exc), 'degraded': True}
