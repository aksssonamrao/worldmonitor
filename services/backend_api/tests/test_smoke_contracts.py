import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from fastapi.testclient import TestClient

from app.domains.planner import service as planner_service
from app.main import app


class DummyResponse:
    def __init__(self, status_code: int, content: bytes, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {'content-type': 'application/json'}


def _plan_payload() -> dict:
    return {
        'run_id': 'latest',
        'timestep': 0,
        'alert_id': 'alert-1',
        'vehicles': [{'id': 'v1', 'start_depot_id': 'd1', 'capacity': 10, 'max_route_time_min': 500}],
        'depots': [{'id': 'd1', 'lat': 37.74, 'lon': -122.58}],
        'jobs': [
            {'id': 'j1', 'lat': 37.76, 'lon': -122.55, 'demand': 2, 'service_time_min': 8},
            {'id': 'j2', 'lat': 37.78, 'lon': -122.53, 'demand': 1, 'service_time_min': 8},
        ],
        'objective_weights': {'distance': 1.0, 'time': 0.2, 'risk': 3.0},
        'risk_model': {'mode': 'polygon_intersection', 'sample_points_per_leg': 10},
    }


def test_routes_options_contract(monkeypatch) -> None:
    payload = {
        'routes': [
            {'id': 'fastest', 'name': 'Fastest', 'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]}, 'summary_risk': {'total': 10}},
            {'id': 'balanced', 'name': 'Balanced', 'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [1, 2]]}, 'summary_risk': {'total': 12}},
            {'id': 'safest', 'name': 'Safest', 'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [2, 2]]}, 'summary_risk': {'total': 8}},
        ]
    }

    async def fake_request(self, method, url, params=None, content=None, headers=None):
        assert method == 'POST'
        assert str(url).endswith('/routes/options')
        return DummyResponse(200, __import__('json').dumps(payload).encode('utf-8'))

    monkeypatch.setattr(httpx.AsyncClient, 'request', fake_request)
    with TestClient(app) as client:
        response = client.post('/api/routes/options', json={})
    assert response.status_code == 200
    body = response.json()
    assert len(body['routes']) == 3
    assert all('geometry' in route and 'summary_risk' in route for route in body['routes'])


def test_routes_score_contract(monkeypatch) -> None:
    payload = {
        'segment_scores': [{'segment_index': 0, 'score': 12.5, 'geometry': {'type': 'LineString', 'coordinates': [[0, 0], [1, 1]]}}],
        'top_evidence': {'events': [], 'alerts': [], 'hazards': []},
    }

    async def fake_request(self, method, url, params=None, content=None, headers=None):
        assert str(url).endswith('/routes/score')
        return DummyResponse(200, __import__('json').dumps(payload).encode('utf-8'))

    monkeypatch.setattr(httpx.AsyncClient, 'request', fake_request)
    with TestClient(app) as client:
        response = client.post('/api/routes/score', json={})
    assert response.status_code == 200
    body = response.json()
    assert 'segment_scores' in body
    assert 'top_evidence' in body


def test_plan_and_brief_contract(monkeypatch) -> None:
    async def fake_hazards(run_id: str, timestep: int):
        return []

    monkeypatch.setattr(planner_service, '_fetch_hazards', fake_hazards)

    with TestClient(app) as client:
        plan_response = client.post('/api/plan', json=_plan_payload())
        brief_response = client.post('/api/agent/brief', json={'prompt': 'AOI update'})

    assert plan_response.status_code == 200
    plan_body = plan_response.json()
    assert set(plan_body.keys()) >= {'plan_id', 'routes', 'objective'}

    assert brief_response.status_code == 200
    brief_body = brief_response.json()
    assert 'memo' in brief_body
    assert isinstance(brief_body['memo'], str)
    assert 'Situation Brief' in brief_body['memo']
