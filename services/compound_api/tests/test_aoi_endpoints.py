from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


class AoiStorage:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.aois: dict[str, dict] = {}
        self.snapshots: dict[str, list[dict]] = {}
        self.deltas: list[dict] = []
        self.runs = [{'run_id': 'run-1', 'started_at': now}]

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

    async def create_aoi_snapshot(self, aoi_id, run_id, timestep=0):
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
        }
        snap = {'id': snap_id, 'aoi_id': aoi_id, 'run_id': run_id, 'timestep': timestep, 'captured_at': now, 'summary_json': summary, 'hash': 'h'}
        self.snapshots.setdefault(aoi_id, []).append(snap)
        if len(self.snapshots[aoi_id]) > 1:
            self.deltas.append({'id': str(uuid4()), 'aoi_id': aoi_id, 'from_snapshot_id': self.snapshots[aoi_id][-2]['id'], 'to_snapshot_id': snap_id, 'created_at': now, 'delta': {'new_events': ['e-new'], 'resolved_events': [], 'event_count_change': 1, 'risk_change': 1.0, 'new_alerts': ['a-new'], 'resolved_alerts': [], 'human_readable': {'summary': '1 new events'}}})
        return snap

    async def list_aoi_changes(self, aoi_id, since_hours):
        return [d for d in self.deltas if d['aoi_id'] == aoi_id]

    async def refresh_all_aoi_snapshots(self, run_id, timestep=0):
        return []


def test_aoi_crud_and_changes():
    app.state.storage = AoiStorage()
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
