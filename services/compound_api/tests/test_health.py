from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.main import compound_health


def test_health_endpoint_returns_ok_true() -> None:
    assert compound_health() == {'ok': True}
