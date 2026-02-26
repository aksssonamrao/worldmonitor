from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from types import SimpleNamespace

from app.main import app


class AoiStorage:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.aois: dict[str, dict] = {}
        self.snapshots: dict[str, list[dict]] = {}
        self.deltas: list[dict] = []
        self.runs = [{'run_id': 'run-1', 'started_at': now}]
        self.last_refresh_run: str | None = None
        self.last_refresh_timestep: int | None = None

    async def latest_run(self):
        return self.runs[-1]

    async def create_aoi(self, name, geometry, country_tags):
        aoi_id = str(uuid4())
        row = {'id': aoi_id, 'name': name, 'geometry': geometry, 'country_tags': country_tags, 'created_at': datetime.now(timezone.utc)}
        self.aois[aoi_id] = row
        return row

    async def list_aois(self):
        return [{**item, 'last_updated': None, 'current_risk_score': 0.0} for item in self.aois.values()]

    async def get_aoi(self, aoi_id):
        return self.aois.get(aoi_id)

    async def delete_aoi(self, aoi_id):
        return self.aois.pop(aoi_id, None) is not None

    async def create_aoi_snapshot(self, aoi_id, run_id, timestep=0, event_lookback_hours=168):
        if aoi_id not in self.aois:
            raise ValueError('aoi not found')
        now = datetime.now(timezone.utc)
        snap_id = str(uuid4())
        idx = len(self.snapshots.get(aoi_id, []))
        summary = {
            'event_counts_by_type': {'DISASTER': idx + 1},
            'top_events': [{'id': f'e-{idx}', 'title': 'event', 'event_type': 'DISASTER', 'occurred_at': now.isoformat()}],
            'hazard_summary': {'top_hazard_types': [['RAIN', 1]], 'max_intensity': 0.8},
            'top_compound_alerts': [{'id': f'a-{idx}', 'score': 52.0}],
            'risk_score': float(20 + idx),
            'event_lookback_hours': event_lookback_hours,
        }
        snap = {'id': snap_id, 'aoi_id': aoi_id, 'run_id': run_id, 'timestep': timestep, 'captured_at': now, 'summary_json': summary, 'hash': 'h'}
        self.snapshots.setdefault(aoi_id, []).append(snap)
        if len(self.snapshots[aoi_id]) > 1:
            self.deltas.append(
                {
                    'id': str(uuid4()),
                    'aoi_id': aoi_id,
                    'from_snapshot_id': self.snapshots[aoi_id][-2]['id'],
                    'to_snapshot_id': snap_id,
                    'created_at': now,
                    'delta': {
                        'new_events': ['e-new'],
                        'resolved_events': [],
                        'event_count_change': 1,
                        'risk_change': 1.0,
                        'new_alerts': ['a-new'],
                        'resolved_alerts': [],
                        'human_readable': {'summary': '1 new events'},
                    },
                }
            )
        return snap

    async def list_aoi_changes(self, aoi_id, since_hours):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        result = []
        for delta in self.deltas:
            if delta.get('aoi_id') != aoi_id:
                continue
            created_at = delta.get('created_at') or delta.get('timestamp')
            if created_at and created_at < cutoff:
                continue
            result.append(delta)
        return result

    async def refresh_all_aoi_snapshots(self, run_id, timestep=0, event_lookback_hours=168):
        self.last_refresh_run = run_id
        self.last_refresh_timestep = timestep
        return []


def test_aoi_crud_and_changes():
    app.state.storage = AoiStorage()
    app.state.settings = SimpleNamespace(event_lookback_hours=72)
    client = TestClient(app)

    created = client.post('/aois', json={'name': 'Port AOI', 'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}, 'country_tags': ['US']})
    assert created.status_code == 200
    aoi_id = created.json()['id']

    assert client.get('/aois').status_code == 200
    assert client.get(f'/aois/{aoi_id}').status_code == 200
    assert client.post(f'/aois/{aoi_id}/snapshot').status_code == 200
    assert client.post(f'/aois/{aoi_id}/snapshot').status_code == 200

    changes = client.get(f'/aois/{aoi_id}/changes?since_hours=168')
    assert changes.status_code == 200
    assert changes.json()['items'][0]['delta']['event_count_change'] == 1

    assert client.delete(f'/aois/{aoi_id}').status_code == 200


def test_aoi_negative_cases_and_empty_list():
    app.state.storage = AoiStorage()
    app.state.settings = SimpleNamespace(event_lookback_hours=72)
    client = TestClient(app)

    empty = client.get('/aois')
    assert empty.status_code == 200
    assert empty.json() == []

    missing = str(uuid4())
    assert client.get(f'/aois/{missing}').status_code == 404
    assert client.post(f'/aois/{missing}/snapshot').status_code == 404
    assert client.delete(f'/aois/{missing}').status_code == 404

    invalid = client.post('/aois', json={'name': 'Invalid AOI', 'geometry': {'type': 'Point', 'coordinates': []}, 'country_tags': []})
    assert invalid.status_code == 422
    assert 'geometry.type must be Polygon or MultiPolygon' in invalid.text


def test_refresh_snapshots_uses_run_id_from_request():
    storage = AoiStorage()
    app.state.storage = storage
    app.state.settings = SimpleNamespace(event_lookback_hours=72)
    client = TestClient(app)

    response = client.post('/aois/snapshots/refresh', json={'run_id': 'run-explicit'})
    assert response.status_code == 200
    assert storage.last_refresh_run == 'run-explicit'
    assert storage.last_refresh_timestep == 0
