from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_ok_true() -> None:
    client = TestClient(app)
    response = client.get('/compound/health')

    assert response.status_code == 200
    assert response.json() == {'ok': True}
