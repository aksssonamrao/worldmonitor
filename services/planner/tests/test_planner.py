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

    resp = client.post('/plan', json=payload)
    assert resp.status_code == 200
    body = resp.json()
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

    b_resp = client.post('/plan', json=baseline)
    assert b_resp.status_code == 200
    b = b_resp.json()
    r_resp = client.post('/plan', json=risk_aware)
    assert r_resp.status_code == 200
    r = r_resp.json()

    # Changing the risk weight with hazards present should change the chosen routes/stops.
    assert [route['stops'] for route in r['routes']] != [route['stops'] for route in b['routes']]


def test_determinism(monkeypatch):
    async def fake_hazards(run_id: str, timestep: int):
        return HAZARDS

    monkeypatch.setattr('app.main._fetch_hazards', fake_hazards)

    payload = _payload()
    first_resp = client.post('/plan', json=payload)
    assert first_resp.status_code == 200
    first = first_resp.json()
    second_resp = client.post('/plan', json=payload)
    assert second_resp.status_code == 200
    second = second_resp.json()

    assert first['objective'] == second['objective']
    assert [r['vehicle_id'] for r in first['routes']] == [r['vehicle_id'] for r in second['routes']]
    assert [r['stops'] for r in first['routes']] == [r['stops'] for r in second['routes']]


def test_llm_summary_null_without_key(monkeypatch):
    async def fake_hazards(run_id: str, timestep: int):
        return HAZARDS

    monkeypatch.setattr('app.main._fetch_hazards', fake_hazards)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)

    resp = client.post('/plan', json=_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body['llm_summary'] is None
