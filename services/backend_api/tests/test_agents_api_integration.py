import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import app.api.agents as agents_api
from app.main import app


def test_agents_run_and_poll_status_with_mocked_orchestrator(monkeypatch) -> None:
    async def fake_run_workflow(request: dict) -> str:
        assert request['route_id'] == 'r1'
        return 'run-123'

    async def fake_get_run(pool, run_id: str) -> dict:
        assert run_id == 'run-123'
        return {
            'run_id': run_id,
            'status': 'succeeded',
            'outputs': {
                'verify': {'verified': True},
                'brief': {'markdown': '# Situation Brief'},
            },
            'steps': [],
            'request': {'route_id': 'r1'},
        }

    monkeypatch.setattr(agents_api, 'run_workflow', fake_run_workflow)
    monkeypatch.setattr(agents_api, 'get_run', fake_get_run)
    monkeypatch.setattr(agents_api, 'get_db_pool', lambda: object())

    with TestClient(app) as client:
        start = client.post('/api/agents/run', json={'route_id': 'r1'})
        assert start.status_code == 200
        run_id = start.json()['run_id']
        status = client.get(f'/api/agents/runs/{run_id}')

    assert status.status_code == 200
    body = status.json()
    assert body['status'] == 'succeeded'
    assert body['outputs']['verify']['verified'] is True
    assert 'brief' in body['outputs']
