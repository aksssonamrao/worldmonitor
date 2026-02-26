from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.hazards.generator import HazardGenerator
from app.main import app


class FakeStorage:
    def __init__(self):
        self.hazards = []
        self.runs = []
        self.samples = {}

    async def insert_run(self, run_id, bbox, timesteps):
        self.runs.append({'run_id': run_id, 'bbox': bbox, 'timesteps': timesteps, 'status': 'RUNNING', 'started_at': datetime.now(timezone.utc), 'finished_at': None, 'points_requested': 0, 'points_fetched': 0, 'cache_hits': 0, 'error': None})

    async def complete_run(self, run_id, status, stats, error=None):
        run = self.latest_run_sync()
        run.update({'status': status, 'finished_at': datetime.now(timezone.utc), **stats, 'error': error})

    async def clear_hazards(self, run_id):
        self.hazards = [h for h in self.hazards if h['run_id'] != run_id]

    async def upsert_sample(self, lat, lon, record):
        self.samples[(lat, lon, record['forecast_ts'])] = (datetime.now(timezone.utc), record)

    async def get_sample(self, lat, lon, ts, ttl_min):
        item = self.samples.get((lat, lon, ts))
        if not item:
            return None
        fetched_at, record = item
        if fetched_at < datetime.now(timezone.utc) - timedelta(minutes=ttl_min):
            return None
        return record

    async def insert_hazard(self, run_id, timestep, hazard_type, prob, forecast_ts, bbox, thresholds, wkt):
        self.hazards.append({'run_id': run_id, 'timestep': timestep, 'type': hazard_type, 'hazard_prob': prob, 'forecast_ts': forecast_ts, 'provider': 'google_weather', 'generated_at': datetime.now(timezone.utc), 'geometry': {'type': 'Polygon', 'coordinates': [[[bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]], [bbox[0], bbox[3]], [bbox[0], bbox[1]]]]}})

    async def list_hazards(self, run_id, timestep):
        return [h for h in self.hazards if h['run_id'] == run_id and h['timestep'] == timestep]

    async def latest_run(self):
        return self.runs[-1] if self.runs else None

    def latest_run_sync(self):
        return self.runs[-1] if self.runs else None


class FakeWeatherClient:
    def __init__(self):
        self.calls = 0

    async def fetch_hourly(self, lat, lon, hours):
        self.calls += 1
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        return [
            {'forecast_ts': now + timedelta(hours=h), 'wind_kph': 80.0, 'precip_mm_hr': 15.0, 'temp_c': 40.0, 'humidity': 40.0}
            for h in range(hours + 1)
        ]


@pytest.fixture
def configured_app():
    from app.config import Settings

    storage = FakeStorage()
    weather = FakeWeatherClient()
    settings = Settings(
        database_url='', google_weather_api_key='x', google_weather_base_url='http://test', hazard_grid_km=25, hazard_max_points=40,
        hazard_cache_ttl_min=60, wind_threshold_kph=50, wind_max_kph=120, rain_threshold_mm_hr=10, rain_max_mm_hr=50,
        heat_threshold_c=38, heat_max_c=48, forecast_hours=24, timestep_hours=[0, 6, 12, 24],
        default_bbox=(72.0, 8.0, 73.0, 9.0), max_bbox_area_deg2=50, max_qps=5,
    )
    app.state.weather_api_configured = True
    app.state.settings = settings
    app.state.storage = storage
    app.state.generator = HazardGenerator(settings, storage, weather)
    app.state.last_hazard_run = None
    app.state.last_hazard_error = None
    return app, weather


def test_generate_writes_polygons(configured_app):
    app_obj, _ = configured_app
    client = TestClient(app_obj)
    resp = client.post('/compound/hazards/generate', json={'run_id': 'latest', 'bbox': [72.0, 8.0, 73.0, 9.0], 'timestep_hours': [0], 'hazard_types': ['WIND']})
    assert resp.status_code == 200

    hazards = client.get('/compound/hazards?run_id=latest&timestep=0')
    payload = hazards.json()
    assert payload['type'] == 'FeatureCollection'
    assert len(payload['features']) > 0


def test_cache_reduces_http_calls(configured_app):
    app_obj, weather = configured_app
    client = TestClient(app_obj)
    body = {'run_id': 'latest', 'bbox': [72.0, 8.0, 73.0, 9.0], 'timestep_hours': [0], 'hazard_types': ['WIND']}
    client.post('/compound/hazards/generate', json=body)
    first = weather.calls
    client.post('/compound/hazards/generate', json=body)
    # On identical requests, cached data should be reused so no additional weather HTTP calls are made.
    assert weather.calls == first
    assert app_obj.state.storage.latest_run_sync()['cache_hits'] > 0


def test_max_points_enforced(configured_app):
    app_obj, _ = configured_app
    client = TestClient(app_obj)
    bad = client.post('/compound/hazards/generate', json={'run_id': 'x1', 'bbox': [0, 0, 100, 100], 'timestep_hours': [0]})
    assert bad.status_code == 400

    points, _ = app_obj.state.generator._grid_points([72.0, 8.0, 76.0, 12.0])
    assert len(points) <= app_obj.state.settings.hazard_max_points


def test_health_endpoint_returns_fields(configured_app):
    app_obj, _ = configured_app
    client = TestClient(app_obj)
    response = client.get('/compound/health')
    assert response.status_code == 200
    payload = response.json()
    assert 'weather_api_configured' in payload
    assert 'last_hazard_run' in payload
    assert 'last_hazard_error' in payload
