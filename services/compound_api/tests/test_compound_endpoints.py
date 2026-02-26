from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.hazards.generator import HazardGenerator
from app.main import app


class FakeStorage:
    def __init__(self):
        self.hazards = []
        self.runs = []
        self.samples = {}
        self.events = []
        self.cache = {}

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

    async def list_events(self, since_hours, event_types=None, bbox=None):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        result = []
        for event in self.events:
            if event['occurred_at'] < cutoff:
                continue
            if event_types and event['event_type'] not in event_types:
                continue
            if bbox:
                lon, lat = event['geometry']['coordinates']
                if not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                    continue
            result.append(event)
        return result

    async def get_event(self, event_id):
        for event in self.events:
            if str(event['id']) == event_id:
                return event
        return None

    async def list_ingestion_state(self):
        return {'gdelt': {'cursor': {'last_run': '2026-01-01T00:00:00Z'}, 'updated_at': '2026-01-01T00:00:00Z'}}

    async def detect_compound_alerts(self, run_id, timestep, lookback_hours, score_threshold, event_weights, bbox=None):
        candidates = []
        events = await self.list_events(lookback_hours, bbox=bbox)
        for event in events:
            ex, ey = event['geometry']['coordinates']
            matches = []
            for hazard in [h for h in self.hazards if h['run_id'] == run_id and h['timestep'] == timestep]:
                coords = hazard['geometry']['coordinates'][0]
                minx, miny = coords[0]
                maxx, maxy = coords[2]
                if minx <= ex <= maxx and miny <= ey <= maxy:
                    base = event['severity'] * event['confidence'] * hazard['hazard_prob']
                    score = max(0.0, min(100.0, base * event_weights.get(event['event_type'], 1.0) * 100.0))
                    matches.append((score, hazard))
            if not matches:
                continue
            matches.sort(key=lambda m: m[0], reverse=True)
            best_score, best_hazard = matches[0]
            if best_score < score_threshold:
                continue
            candidates.append({
                'event_id': str(event['id']),
                'title': event['title'],
                'url': event['url'],
                'event_type': event['event_type'],
                'hazard_type': best_hazard['type'],
                'hazard_prob': best_hazard['hazard_prob'],
                'forecast_ts': best_hazard['forecast_ts'],
                'score': best_score,
                'country': event['country'],
                'occurred_at': event['occurred_at'],
                'geometry': event['geometry'],
                'details': {
                    'base': event['severity'] * event['confidence'] * best_hazard['hazard_prob'],
                    'event_weight': event_weights.get(event['event_type'], 1.0),
                    'severity': event['severity'],
                    'confidence': event['confidence'],
                    'hazard_prob': best_hazard['hazard_prob'],
                    'other_hazards': [{'hazard_type': h['type'], 'hazard_prob': h['hazard_prob']} for _, h in matches[1:]],
                },
            })
        return candidates

    def latest_run_sync(self):
        return self.runs[-1] if self.runs else None

    async def get_route_score_cache(self, route_hash, time_bucket):
        return self.cache.get((route_hash, time_bucket))

    async def set_route_score_cache(self, route_hash, time_bucket, payload):
        self.cache[(route_hash, time_bucket)] = payload

    async def score_route_corridor(self, geometry, lookback_hours, run_id, timestep, buffer_meters=15000):
        coords = geometry.get('coordinates', [])
        base = 20 + len(coords) * 5
        return {
            'total_risk': float(base),
            'summary_risk': {'total': float(base), 'weather': base * 0.4, 'news': base * 0.35, 'compound': base * 0.25},
            'segment_scores': [
                {'segment_index': i, 'score': float(base + i), 'weather': 10.0, 'news': 8.0, 'compound': 7.0, 'geometry': {'type': 'LineString', 'coordinates': [coords[i], coords[i + 1]]}}
                for i in range(max(0, len(coords) - 1))
            ],
            'top_evidence': {'events': [], 'alerts': [], 'hazards': []},
        }


class FakeWeatherClient:
    def __init__(self):
        self.calls = 0

    async def fetch_hourly(self, lat, lon, hours):
        self.calls += 1
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        return [{'forecast_ts': now + timedelta(hours=h), 'wind_kph': 80.0, 'precip_mm_hr': 15.0, 'temp_c': 40.0, 'humidity': 40.0} for h in range(hours + 1)]


@pytest.fixture
def configured_app():
    from app.config import Settings

    storage = FakeStorage()
    weather = FakeWeatherClient()
    settings = Settings(
        database_url='', google_weather_api_key='x', google_weather_base_url='http://test', hazard_grid_km=25, hazard_max_points=40,
        hazard_cache_ttl_min=60, wind_threshold_kph=50, wind_max_kph=120, rain_threshold_mm_hr=10, rain_max_mm_hr=50,
        heat_threshold_c=38, heat_max_c=48, forecast_hours=24, timestep_hours=[0, 6, 12, 24],
        default_bbox=(72.0, 8.0, 73.0, 9.0), max_bbox_area_deg2=50, max_qps=5, event_lookback_hours=72,
        alert_score_threshold=20, event_type_weights={'PROTEST': 1.2, 'DISASTER': 1.4, 'OTHER': 1.0, 'CONFLICT': 1.5, 'STRIKE': 1.2, 'OUTAGE': 1.3, 'ACCIDENT': 1.1},
    )
    app.state.weather_api_configured = True
    app.state.settings = settings
    app.state.storage = storage
    app.state.generator = HazardGenerator(settings, storage, weather)
    app.state.last_hazard_run = None
    app.state.last_hazard_error = None
    return app, storage


def test_events_geojson_endpoint(configured_app):
    app_obj, storage = configured_app
    now = datetime.now(timezone.utc)
    storage.events.append({'id': uuid4(), 'source': 'gdelt', 'title': 'Airport strike causes delays', 'description': 'Workers strike', 'url': 'https://example.com/event', 'event_type': 'STRIKE', 'severity': 0.7, 'confidence': 0.8, 'country': 'GB', 'region': 'EUROPE', 'occurred_at': now, 'ingested_at': now, 'raw': {}, 'geometry': {'type': 'Point', 'coordinates': [-0.1, 51.5]}})
    storage.events.append({'id': uuid4(), 'source': 'gdelt', 'title': 'Old protest', 'description': 'old', 'url': 'https://example.com/old', 'event_type': 'PROTEST', 'severity': 0.7, 'confidence': 0.8, 'country': 'GB', 'region': 'EUROPE', 'occurred_at': now - timedelta(hours=200), 'ingested_at': now, 'raw': {}, 'geometry': {'type': 'Point', 'coordinates': [-0.2, 51.6]}})

    client = TestClient(app_obj)
    response = client.get('/compound/events?since_hours=72&types=STRIKE,,')
    assert response.status_code == 200
    payload = response.json()
    assert payload['type'] == 'FeatureCollection'
    assert len(payload['features']) == 1


def test_compound_alert_generation(configured_app):
    app_obj, storage = configured_app
    now = datetime.now(timezone.utc)
    storage.runs.append({'run_id': 'run-test', 'started_at': now})
    storage.hazards.append({'run_id': 'run-test', 'timestep': 0, 'type': 'RAIN', 'hazard_prob': 0.9, 'forecast_ts': now, 'provider': 'google_weather', 'generated_at': now, 'geometry': {'type': 'Polygon', 'coordinates': [[[72.0, 8.0], [73.0, 8.0], [73.0, 9.0], [72.0, 9.0], [72.0, 8.0]]]}})
    event_id = uuid4()
    storage.events.append({'id': event_id, 'source': 'gdelt', 'title': 'Flood warning and logistics disruption', 'description': 'desc', 'url': 'https://example.com/flood', 'event_type': 'DISASTER', 'severity': 0.8, 'confidence': 0.85, 'country': 'IN', 'region': 'ASIA', 'occurred_at': now, 'ingested_at': now, 'raw': {}, 'geometry': {'type': 'Point', 'coordinates': [72.5, 8.5]}})

    client = TestClient(app_obj)
    response = client.get('/compound/alerts?run_id=run-test&timestep=0&bbox=72.0,8.0,73.0,9.0')
    assert response.status_code == 200
    features = response.json()['features']
    assert len(features) == 1
    assert features[0]['properties']['event_id'] == str(event_id)


def test_dedup_multiple_hazards_and_invalid_event_id(configured_app):
    app_obj, storage = configured_app
    now = datetime.now(timezone.utc)
    storage.runs.append({'run_id': 'run-dedup', 'started_at': now})
    poly = {'type': 'Polygon', 'coordinates': [[[72.0, 8.0], [73.0, 8.0], [73.0, 9.0], [72.0, 9.0], [72.0, 8.0]]]}
    storage.hazards.extend([
        {'run_id': 'run-dedup', 'timestep': 0, 'type': 'RAIN', 'hazard_prob': 0.9, 'forecast_ts': now, 'provider': 'google_weather', 'generated_at': now, 'geometry': poly},
        {'run_id': 'run-dedup', 'timestep': 0, 'type': 'WIND', 'hazard_prob': 0.7, 'forecast_ts': now, 'provider': 'google_weather', 'generated_at': now, 'geometry': poly},
    ])
    event_id = uuid4()
    storage.events.append({'id': event_id, 'source': 'gdelt', 'title': 'Protest near highway', 'description': 'desc', 'url': 'https://example.com/protest', 'event_type': 'PROTEST', 'severity': 0.7, 'confidence': 0.9, 'country': 'US', 'region': 'NA', 'occurred_at': now, 'ingested_at': now, 'raw': {}, 'geometry': {'type': 'Point', 'coordinates': [72.4, 8.4]}})

    client = TestClient(app_obj)
    response = client.get('/compound/alerts?run_id=run-dedup&timestep=0')
    assert response.status_code == 200
    features = response.json()['features']
    assert len(features) == 1
    assert len(features[0]['properties']['details']['other_hazards']) == 1

    bad = client.get('/compound/events/not-a-uuid')
    assert bad.status_code == 400

    ok = client.get(f'/compound/events/{event_id}')
    assert ok.status_code == 200


def test_routes_options_and_score(configured_app):
    app_obj, storage = configured_app
    now = datetime.now(timezone.utc)
    storage.runs.append({'run_id': 'run-routes', 'started_at': now})
    client = TestClient(app_obj)

    options_resp = client.post(
        '/routes/options',
        json={
            'origin': {'lat': 37.78, 'lon': -122.42},
            'destination': {'lat': 34.05, 'lon': -118.24},
            'depart_time': now.isoformat(),
            'arrive_by': (now + timedelta(hours=10)).isoformat(),
            'risk_appetite': 0.5,
        },
    )
    assert options_resp.status_code == 200
    routes = options_resp.json()['routes']
    assert len(routes) == 3
    assert {route['name'] for route in routes} == {'Fastest', 'Balanced', 'Safest'}

    score_resp = client.post(
        '/routes/score',
        json={
            'geometry': routes[0]['geometry'],
            'depart_time': now.isoformat(),
            'arrive_by': (now + timedelta(hours=10)).isoformat(),
            'run_id': 'latest',
            'timestep': 0,
        },
    )
    assert score_resp.status_code == 200
    score = score_resp.json()
    assert score['segment_scores']
    assert 'top_evidence' in score
