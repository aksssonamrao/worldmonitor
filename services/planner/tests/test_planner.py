from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

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
    assert body['routes']
    assert any(len(route['stops']) > 2 for route in body['routes'])


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
        assert route['time_min'] <= vehicle_map[route['vehicle_id']]['max_route_time_min']


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

    # Changing the risk weight with hazards present should change the chosen routes/stops.
    assert [route['stops'] for route in r['routes']] != [route['stops'] for route in b['routes']]


def test_determinism(monkeypatch):
    async def fake_hazards(run_id: str, timestep: int):
        return HAZARDS

    monkeypatch.setattr('app.main._fetch_hazards', fake_hazards)

    payload = _payload()
    first = client.post('/plan', json=payload).json()
    second = client.post('/plan', json=payload).json()

    assert first['objective'] == second['objective']
    assert [r['vehicle_id'] for r in first['routes']] == [r['vehicle_id'] for r in second['routes']]
    assert [r['stops'] for r in first['routes']] == [r['stops'] for r in second['routes']]


def test_llm_summary_null_without_key(monkeypatch):
    async def fake_hazards(run_id: str, timestep: int):
        return HAZARDS

    monkeypatch.setattr('app.main._fetch_hazards', fake_hazards)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)

    body = client.post('/plan', json=_payload()).json()
    assert body['llm_summary'] is None


def test_plan_accepts_selected_route_geometry(monkeypatch):
    async def fake_hazards(run_id: str, timestep: int):
        return HAZARDS

    monkeypatch.setattr('app.main._fetch_hazards', fake_hazards)
    payload = _payload()
    payload['selected_route_geometry'] = {'type': 'LineString', 'coordinates': [[-122.4, 37.7], [-122.3, 37.8]]}
    body = client.post('/plan', json=payload).json()
    assert body['selected_route_geometry'] == payload['selected_route_geometry']


def test_agent_brief_template():
    resp = client.post('/agent/brief', json={'shipment': {'origin': 'SFO', 'destination': 'LAX', 'depart_time': '2026-01-01T00:00:00Z', 'arrive_by': '2026-01-01T08:00:00Z'}, 'selected_route_id': 'balanced'})
    assert resp.status_code == 200
    body = resp.json()
    assert 'markdown' in body
    assert body['citations']


def test_agent_mitigation(monkeypatch):
    class FakePlugin:
        def __init__(self, client):
            self.client = client

        async def route(self, payload):
            return {'routes': [{'geometry': {'type': 'LineString', 'coordinates': [[-122.4, 37.7], [-118.2, 34.0]]}, 'duration_s': 1000}, {'geometry': {'type': 'LineString', 'coordinates': [[-122.4, 37.7], [-119.0, 35.0], [-118.2, 34.0]]}, 'duration_s': 1200}]}

        async def isochrone(self, payload):
            return {'feature_collection': {'type': 'FeatureCollection', 'features': []}}

        async def corridor_score(self, geometry, depart_time, arrive_by):
            return {'summary_risk': {'total': 17.0}}

    monkeypatch.setattr('app.main.RoutingPlugin', FakePlugin)
    resp = client.post('/agent/mitigation', json={
        'shipment': {
            'origin': {'lat': 37.78, 'lon': -122.42},
            'destination': {'lat': 34.05, 'lon': -118.24},
            'depart_time': '2026-01-01T00:00:00Z',
            'arrive_by': '2026-01-01T08:00:00Z',
        },
        'selected_route': {'geometry': {'type': 'LineString', 'coordinates': [[-122.4, 37.7], [-118.2, 34.0]]}, 'eta_hours': 8},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body['mitigations']['depart_later']
    assert body['mitigations']['reroute']['risk_total'] == 17.0
    assert body['citations']
