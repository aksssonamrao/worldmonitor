from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    assert client.get('/health').status_code == 200


def test_route_normalization(monkeypatch):
    async def fake_post(path, payload):
        assert path == '/route'
        return {
            'trips': [
                {
                    'summary': {'length': 12.3, 'time': 777},
                    'legs': [{'shape': '_p~iF~ps|U_ulLnnqC_mqNvxq`@'}],
                }
            ]
        }

    monkeypatch.setattr('app.main._post', fake_post)
    resp = client.post('/routing/route', json={'payload': {'locations': []}})
    assert resp.status_code == 200
    route = resp.json()['routes'][0]
    assert route['distance_km'] == 12.3
    assert route['duration_s'] == 777
    assert route['geometry']['type'] == 'LineString'
    assert len(route['geometry']['coordinates']) == 3
