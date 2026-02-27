from __future__ import annotations

import pytest

from app.config import load_settings


def test_load_settings_requires_database_url(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    with pytest.raises(RuntimeError, match='DATABASE_URL is required'):
        load_settings()
