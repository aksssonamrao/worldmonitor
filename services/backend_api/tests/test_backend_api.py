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


def test_health_ok() -> None:
    with TestClient(app) as client:
        response = client.get('/health')

    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'ok'
    assert 'compound' in body


def test_api_route_proxy_success(monkeypatch) -> None:
    async def fake_request(self, method, url, params=None, content=None, headers=None):
        assert method == 'POST'
        assert url.endswith('/routes/options')
        assert params.get('x') == '1'
        assert content == b'{"k":"v"}'
        return DummyResponse(200, b'{"routes":[]}')

    monkeypatch.setattr(httpx.AsyncClient, 'request', fake_request)

    with TestClient(app) as client:
        response = client.post('/api/routes/options?x=1', content=b'{"k":"v"}', headers={'content-type': 'application/json'})

    assert response.status_code == 200
    assert response.json() == {'routes': []}


def test_upstream_failure_returns_502(monkeypatch) -> None:
    async def fake_request(self, method, url, params=None, content=None, headers=None):
        raise httpx.ConnectError('boom')

    monkeypatch.setattr(httpx.AsyncClient, 'request', fake_request)

    with TestClient(app) as client:
        response = client.post('/api/routes/score', json={'hello': 'world'})

    assert response.status_code == 502
    assert 'Upstream request failed' in response.json()['detail']


def test_api_plan_direct_implementation(monkeypatch) -> None:
    async def fake_hazards(run_id: str, timestep: int):
        return []

    monkeypatch.setattr(planner_service, '_fetch_hazards', fake_hazards)

    with TestClient(app) as client:
        response = client.post('/api/plan', json=_plan_payload())

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) >= {'plan_id', 'objective', 'routes', 'constraints_ok', 'explain', 'llm_summary'}


def test_api_agent_brief_returns_memo() -> None:
    with TestClient(app) as client:
        response = client.post('/api/agent/brief', json={'prompt': 'AOI update: protest risk near corridor'})

    assert response.status_code == 200
    body = response.json()
    assert 'memo' in body
    assert 'Situation Brief' in body['memo']


def test_internal_jobs_forbidden_without_admin_key(monkeypatch) -> None:
    monkeypatch.delenv('ADMIN_API_KEY', raising=False)
    with TestClient(app) as client:
        response = client.get('/internal/jobs/stats')
    assert response.status_code == 404


def test_internal_jobs_forbidden_with_wrong_admin_key(monkeypatch) -> None:
    monkeypatch.setenv('ADMIN_API_KEY', 'secret')
    with TestClient(app) as client:
        response = client.get('/internal/jobs/stats', headers={'X-Admin-Key': 'wrong'})
    assert response.status_code == 403
