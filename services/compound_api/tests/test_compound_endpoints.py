from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_hazards_endpoint_returns_geojson_feature_collection() -> None:
    response = client.get('/compound/hazards?timestep=0')

    assert response.status_code == 200
    payload = response.json()

    assert payload['type'] == 'FeatureCollection'
    assert isinstance(payload['features'], list)
    assert len(payload['features']) == 3

    first = payload['features'][0]
    assert first['type'] == 'Feature'
    assert first['geometry']['type'] == 'Polygon'
    assert 'hazard_prob' in first['properties']


def test_alerts_endpoint_returns_geojson_with_breakdown_and_nonempty_alerts() -> None:
    response = client.get('/compound/alerts?timestep=0')

    assert response.status_code == 200
    payload = response.json()

    assert payload['type'] == 'FeatureCollection'
    assert isinstance(payload['features'], list)
    assert len(payload['features']) >= 1

    first = payload['features'][0]
    assert first['type'] == 'Feature'
    assert first['geometry']['type'] == 'Point'

    props = first['properties']
    assert 0 <= props['score'] <= 1
    assert 'explanation' in props
    explanation = props['explanation']
    assert set(['hazard_prob', 'event_prob', 'compatibility', 'credibility', 'raw_score', 'score']).issubset(
        explanation.keys()
    )
