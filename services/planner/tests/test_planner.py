from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, _objective, _simulate_win_rates

client = TestClient(app)
FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures' / 'demo_case.json'


HAZARDS = [
    {
        'type': 'Feature',
        'geometry': {
            'type': 'Polygon',
            'coordinates': [[
                [-122.515, 37.70],
                [-122.455, 37.70],
                [-122.455, 37.81],
                [-122.515, 37.81],
                [-122.515, 37.70],
            ]],
        },
        'properties': {'hazard_prob': 0.95},
    }
]


def _payload() -> dict:
    return json.loads(FIXTURE.read_text())


def test_plan_schema(monkeypatch):
    async def fake_hazards(run_id: str, timestep: int):
        return HAZARDS

    monkeypatch.setattr('app.main._fetch_hazards', fake_hazards)
    resp = client.post('/plan', json=_payload())
    assert resp.status_code == 200
    body = resp.json()
    for key in ('plan_id', 'objective', 'routes', 'constraints_ok', 'explain', 'llm_summary'):
        assert key in body


def test_constraints_hold(monkeypatch):
    async def fake_hazards(run_id: str, timestep: int):
        return HAZARDS

    monkeypatch.setattr('app.main._fetch_hazards', fake_hazards)
    payload = _payload()
    vehicle_map = {v['id']: v for v in payload['vehicles']}
    job_map = {j['id']: j for j in payload['jobs']}

    body = client.post('/plan', json=payload).json()
    for route in body['routes']:
        cap_used = sum(job_map[s['id']]['demand'] for s in route['stops'] if s['type'] == 'job')
        assert cap_used <= vehicle_map[route['vehicle_id']]['capacity']


def test_risk_changes_solution(monkeypatch):
    async def fake_hazards(run_id: str, timestep: int):
        return HAZARDS

    monkeypatch.setattr('app.main._fetch_hazards', fake_hazards)

    baseline = _payload()
    baseline['objective_weights']['risk'] = 0.0
    risk_aware = _payload()
    risk_aware['objective_weights']['risk'] = 3.0

    b = client.post('/plan', json=baseline).json()
    r = client.post('/plan', json=risk_aware).json()
    assert [route['stops'] for route in r['routes']] != [route['stops'] for route in b['routes']]


def test_llm_summary_null_without_key(monkeypatch):
    async def fake_hazards(run_id: str, timestep: int):
        return HAZARDS

    monkeypatch.setattr('app.main._fetch_hazards', fake_hazards)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)

    body = client.post('/plan', json=_payload()).json()
    assert body['llm_summary'] is None


class FakePlugin:
    def __init__(self, client):
        self.client = client

    async def route(self, payload):
        locs = payload.get('locations', [])
        if len(locs) == 2 and locs[1].get('lon') in {-118.2437, -87.6298, -97.0403, -84.4277, -74.006}:
            return {'routes': [{'geometry': {'type': 'LineString', 'coordinates': [[locs[0]['lon'], locs[0]['lat']], [locs[1]['lon'], locs[1]['lat']]]}, 'duration_s': 10000}]}
        return {
            'routes': [
                {'geometry': {'type': 'LineString', 'coordinates': [[-122.4, 37.7], [-118.2, 34.0]]}, 'duration_s': 28800},
                {'geometry': {'type': 'LineString', 'coordinates': [[-122.4, 37.7], [-119.0, 35.0], [-118.2, 34.0]]}, 'duration_s': 32400},
                {'geometry': {'type': 'LineString', 'coordinates': [[-122.4, 37.7], [-120.5, 36.0], [-118.2, 34.0]]}, 'duration_s': 36000},
            ]
        }

    async def isochrone(self, payload):
        return {'feature_collection': {'type': 'FeatureCollection', 'features': []}}

    async def corridor_score(self, geometry, depart_time, arrive_by):
        coords = geometry.get('coordinates', [])
        risk = 50.0 - min(len(coords), 4) * 4
        return {
            'summary_risk': {'total': risk, 'weather': 15.0, 'news': 20.0, 'compound': risk - 35.0},
            'top_evidence': {
                'events': [
                    {'id': 'e1', 'title': 'Strike risk', 'event_type': 'STRIKE', 'severity': 0.8, 'confidence': 0.9, 'occurred_at': '2026-01-01T00:00:00Z', 'url': 'https://example.com/e1'},
                    {'id': 'e2', 'title': 'Port congestion', 'event_type': 'CONGESTION', 'severity': 0.6, 'confidence': 0.7, 'occurred_at': '2026-01-01T02:00:00Z', 'url': 'https://example.com/e2'},
                ],
                'alerts': [{'id': 'a1', 'title': 'Alert', 'score': 0.7, 'url': 'https://example.com/a1'}],
                'hazards': [{'id': 'h1', 'type': 'flood', 'hazard_prob': 0.4}],
            },
        }


def test_agent_mitigation_schema_and_top3(monkeypatch):
    monkeypatch.setattr('app.main.RoutingPlugin', FakePlugin)
    resp = client.post('/agent/mitigation', json={
        'shipment': {
            'origin': {'lat': 37.78, 'lon': -122.42},
            'destination': {'lat': 34.05, 'lon': -118.24},
            'depart_time': '2026-01-01T00:00:00Z',
            'arrive_by': '2026-01-01T08:00:00Z',
            'mode': 'auto',
            'risk_appetite': 0.6,
        },
        'selected_route': {'id': 'route-1', 'geometry': {'type': 'LineString', 'coordinates': [[-122.4, 37.7], [-118.2, 34.0]]}},
        'constraints': {'avoid_event_types': ['STRIKE'], 'max_extra_eta_hours': 20, 'max_risk_score': 70},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) >= {'request_id', 'baseline', 'options', 'recommended_option_id', 'robustness'}
    assert len(body['options']) == 3
    assert body['recommended_option_id'] in [opt['option_id'] for opt in body['options']]
    assert body['robustness']['runs'] == 100


def test_robustness_win_rate_calculation():
    options = [
        {'option_id': 'a', 'risk_breakdown': {'weather': 10, 'news': 8, 'compound': 3}, 'delta_eta_hours': 0.5},
        {'option_id': 'b', 'risk_breakdown': {'weather': 15, 'news': 12, 'compound': 6}, 'delta_eta_hours': 0.0},
    ]
    results = _simulate_win_rates(options, 0.5, 100, seed=7)
    assert len(results) == 2
    assert round(sum(item['win_pct'] for item in results), 2) == 100.0


def test_robustness_single_option_edge_case():
    options = [
        {'option_id': 'only', 'risk_breakdown': {'weather': 12, 'news': 9, 'compound': 4}, 'delta_eta_hours': 1.0},
    ]
    results = _simulate_win_rates(options, 0.5, 100, seed=11)
    assert len(results) == 1
    assert results[0]['option_id'] == 'only'
    assert results[0]['win_pct'] == 100.0


def test_objective_respects_risk_appetite():
    risk_first = _objective(20.0, 3.0, 0.9)
    eta_penalized = _objective(20.0, 3.0, 0.1)
    assert eta_penalized > risk_first
