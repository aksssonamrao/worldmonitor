from __future__ import annotations

import asyncio

import httpx
import pytest

from app.config import load_settings
from app.provider_client import RateLimiter
from app.weather.google_weather_client import GoogleWeatherClient


class FakeStorage:
    def __init__(self):
        self.cache = {}
        self.status = {'provider': 'google_weather', 'consecutive_failures': 0, 'circuit_open_until': None}

    async def get_provider_status(self, provider):
        return self.status

    async def upsert_provider_cache(self, provider, cache_key, payload, ttl_seconds):
        self.cache[(provider, cache_key)] = {'payload_json': payload, 'fetched_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc)}

    async def mark_provider_success(self, provider):
        self.status['consecutive_failures'] = 0

    async def mark_provider_failure(self, provider, error, circuit_open_until):
        self.status['consecutive_failures'] += 1
        self.status['circuit_open_until'] = circuit_open_until
        return self.status['consecutive_failures']

    async def get_provider_cache(self, provider, cache_key):
        return self.cache.get((provider, cache_key))


def _settings(monkeypatch):
    monkeypatch.setenv('GOOGLE_WEATHER_API_KEY', 'k')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://worldmonitor:worldmonitor@localhost:5432/worldmonitor')
    return load_settings()


def test_startup_requires_api_key(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://worldmonitor:worldmonitor@localhost:5432/worldmonitor')
    monkeypatch.delenv('GOOGLE_WEATHER_API_KEY', raising=False)
    with pytest.raises(RuntimeError, match='GOOGLE_WEATHER_API_KEY is required'):
        load_settings()


def test_startup_requires_database_url(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('GOOGLE_WEATHER_API_KEY', 'test-key')
    with pytest.raises(RuntimeError, match='DATABASE_URL is required'):
        load_settings()


def test_provider_failure_with_cache_returns_degraded(monkeypatch):
    settings = _settings(monkeypatch)
    storage = FakeStorage()
    cache_key = '10.0:20.0:1'
    storage.cache[('google_weather', cache_key)] = {
        'payload_json': {'rows': [{'forecast_ts': '2025-01-01T00:00:00+00:00', 'wind_kph': 10, 'precip_mm_hr': 0, 'temp_c': 20, 'humidity': 30}]},
        'fetched_at': __import__('datetime').datetime.now(__import__('datetime').timezone.utc),
    }
    client = GoogleWeatherClient(settings, storage)

    async def fake_get(*args, **kwargs):
        return httpx.Response(503, request=httpx.Request('GET', args[0]), text='down')

    monkeypatch.setattr(client.client, 'get', fake_get)
    result = asyncio.run(client.fetch_hourly(10.0, 20.0, 1))
    assert result['degraded'] is True
    assert len(result['rows']) == 1


def test_provider_failure_without_cache_returns_empty_degraded(monkeypatch):
    settings = _settings(monkeypatch)
    storage = FakeStorage()
    client = GoogleWeatherClient(settings, storage)

    async def fake_get(*args, **kwargs):
        raise httpx.ConnectError('offline')

    monkeypatch.setattr(client.client, 'get', fake_get)
    result = asyncio.run(client.fetch_hourly(11.0, 21.0, 1))
    assert result['degraded'] is True
    assert result['rows'] == []


def test_circuit_breaker_opens_after_failures(monkeypatch):
    settings = _settings(monkeypatch)
    storage = FakeStorage()
    client = GoogleWeatherClient(settings, storage)

    async def fake_get(*args, **kwargs):
        raise httpx.ConnectError('offline')

    monkeypatch.setattr(client.client, 'get', fake_get)
    for _ in range(settings.provider_circuit_failure_threshold):
        asyncio.run(client.fetch_hourly(12.0, 22.0, 1))
    assert storage.status['circuit_open_until'] is not None


def test_invalid_event_type_weights_json(monkeypatch):
    monkeypatch.setenv('GOOGLE_WEATHER_API_KEY', 'test-key')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://worldmonitor:worldmonitor@localhost:5432/worldmonitor')
    monkeypatch.setenv('EVENT_TYPE_WEIGHTS_JSON', '{invalid')
    with pytest.raises(RuntimeError, match='Invalid value for EVENT_TYPE_WEIGHTS_JSON'):
        load_settings()


def test_invalid_provider_timeout_settings(monkeypatch):
    monkeypatch.setenv('GOOGLE_WEATHER_API_KEY', 'test-key')
    monkeypatch.setenv('DATABASE_URL', 'postgresql://worldmonitor:worldmonitor@localhost:5432/worldmonitor')
    monkeypatch.setenv('PROVIDER_CONNECT_TIMEOUT_SECONDS', '0')
    with pytest.raises(RuntimeError, match='PROVIDER_CONNECT_TIMEOUT_SECONDS'):
        load_settings()


def test_rate_limiter_rejects_non_positive_rate():
    with pytest.raises(ValueError, match='rate_per_second'):
        RateLimiter(0)
