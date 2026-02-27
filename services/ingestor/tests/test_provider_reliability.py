from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.ingestion import _run_provider
from app.provider_client import ProviderClient, RateLimiter


class FakeStorage:
    def __init__(self, with_cache: bool):
        self.with_cache = with_cache
        self.failures = 0

    async def get_provider_status(self, provider):
        return {'provider': provider, 'consecutive_failures': self.failures, 'circuit_open_until': None}

    async def upsert_provider_cache(self, provider, cache_key, payload, ttl_seconds):
        return None

    async def mark_provider_success(self, provider):
        self.failures = 0

    async def mark_provider_failure(self, provider, error, circuit_open_until):
        self.failures += 1
        return self.failures

    async def get_provider_cache(self, provider, cache_key):
        if not self.with_cache:
            return None
        return {'payload_json': {'events': []}, 'fetched_at': datetime.now(timezone.utc), 'ttl_seconds': 60}


def _provider_client() -> ProviderClient:
    return ProviderClient(
        provider='x',
        max_retries=0,
        backoff_base_seconds=0.01,
        backoff_max_seconds=0.02,
        jitter_seconds=0.0,
        failure_threshold=2,
        cooldown_seconds=60,
        rate_limiter=RateLimiter(1000),
    )


def test_provider_failure_with_cache_marks_degraded():
    storage = FakeStorage(with_cache=True)

    async def fetcher():
        raise RuntimeError('boom')

    events, degraded, meta = asyncio.run(_run_provider(
        storage=storage,
        provider_name='gdelt',
        cache_key='default',
        cache_ttl_seconds=60,
        max_stale_seconds=600,
        provider_client=_provider_client(),
        fetcher=fetcher,
    ))
    assert events == []
    assert degraded is True
    assert meta['cache_used'] is True


def test_provider_failure_without_cache_returns_empty_degraded():
    storage = FakeStorage(with_cache=False)

    async def fetcher():
        raise RuntimeError('boom')

    events, degraded, meta = asyncio.run(_run_provider(
        storage=storage,
        provider_name='gdelt',
        cache_key='default',
        cache_ttl_seconds=60,
        max_stale_seconds=600,
        provider_client=_provider_client(),
        fetcher=fetcher,
    ))
    assert events == []
    assert degraded is True
    assert meta['cache_used'] is False


def test_circuit_opens_after_repeated_failures():
    pc = _provider_client()
    assert pc.next_circuit_open_until(1) is None
    assert pc.next_circuit_open_until(2) is not None
