from __future__ import annotations

import httpx
import pytest

from app.config import load_settings
from app.weather.google_weather_client import GoogleWeatherClient


def test_startup_requires_api_key(monkeypatch):
    monkeypatch.delenv('GOOGLE_WEATHER_API_KEY', raising=False)
    with pytest.raises(RuntimeError, match='GOOGLE_WEATHER_API_KEY is required'):
        load_settings()


def test_rate_limit_and_retry(monkeypatch):
    client = GoogleWeatherClient('https://weather.googleapis.com/v1', 'abc', max_qps=1000)
    calls = {'n': 0}

    async def fake_get(*args, **_):
        calls['n'] += 1
        if calls['n'] == 1:
            return httpx.Response(429, request=httpx.Request('GET', args[0]), json={'error': 'rate'})
        return httpx.Response(
            200,
            request=httpx.Request('GET', args[0]),
            json={
                'hours': [
                    {
                        'interval': {'startTime': '2025-01-01T00:00:00Z'},
                        'wind': {'speed': {'value': 70}},
                        'precipitation': {'qpf': {'value': 15}},
                        'temperature': {'degrees': 39},
                        'relativeHumidity': {'value': 35},
                    }
                ]
            },
        )

    monkeypatch.setattr(client.client, 'get', fake_get)

    import asyncio

    rows = asyncio.run(client.fetch_hourly(10.0, 20.0, 1))
    assert len(rows) == 1
    assert calls['n'] == 2


def test_invalid_event_type_weights_json(monkeypatch):
    monkeypatch.setenv('GOOGLE_WEATHER_API_KEY', 'test-key')
    monkeypatch.setenv('EVENT_TYPE_WEIGHTS_JSON', '{invalid')
    with pytest.raises(RuntimeError, match='Invalid value for EVENT_TYPE_WEIGHTS_JSON'):
        load_settings()
