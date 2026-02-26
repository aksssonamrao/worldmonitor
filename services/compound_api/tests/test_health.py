from pathlib import Path
import sys
from ..app.main import compound_health
def test_health_endpoint_returns_ok_true() -> None:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return compound_health()

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
