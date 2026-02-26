from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.main import compound_health
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_health_endpoint_returns_ok_true() -> None:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return compound_health()

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
