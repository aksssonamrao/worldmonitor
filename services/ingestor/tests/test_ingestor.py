from __future__ import annotations

import asyncio
from pathlib import Path
from datetime import datetime, timezone

import httpx

from app.config import Settings
from app.ingestion import run_ingestion_cycle
from app.providers.common import EventSourceCreate
from app.providers.gdelt import fetch_gdelt
from app.providers.planned import fetch_planned
from app.providers.reliefweb import fetch_reliefweb
from app.providers.usgs import fetch_usgs


PLANNED_DISRUPTIONS_PATH = (Path(__file__).resolve().parents[3] / 'config' / 'planned_disruptions.yml').as_posix()


class FakeStorage:
    def __init__(self):
        self.events = {}
        self.cursors = {}

    async def upsert_event_source_and_incident(self, event, **kwargs):
        self.events[(event.source, event.source_event_id)] = event

    async def upsert_cursor(self, source, cursor):
        self.cursors[source] = cursor


def test_usgs_ingest_creates_sources_and_incidents():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={'features': [{'id': 'us1', 'properties': {'mag': 5.2, 'title': 'M 5.2 - test', 'place': 'Test Place', 'url': 'https://usgs/1', 'time': 1760000000000}, 'geometry': {'coordinates': [72.8, 19.1]}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await fetch_usgs(client, 72, 4)
        assert len(events) == 1
        assert events[0].subtype == 'EARTHQUAKE'
        assert events[0].confidence == 0.95

    asyncio.run(run())


def test_planned_ingest_creates_incidents():
    events = fetch_planned(PLANNED_DISRUPTIONS_PATH)
    assert len(events) >= 1
    assert all(isinstance(e, EventSourceCreate) for e in events)


def test_reliefweb_missing_appname_is_graceful():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={'message': 'forbidden'})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = await fetch_reliefweb(client, '2026-01-01T00:00:00+00:00', ['AE'], [], 'bad-app')
        assert events == []

    asyncio.run(run())


def test_firms_disabled_skips_cleanly(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if 'gdeltproject' in str(request.url):
            return httpx.Response(200, json={'articles': []})
        if 'reliefweb' in str(request.url):
            return httpx.Response(200, json={'data': []})
        if 'earthquake.usgs.gov' in str(request.url):
            return httpx.Response(200, json={'features': []})
        return httpx.Response(200, json={})

    original_client = httpx.AsyncClient

    class DummyClient:
        def __init__(self, *args, **kwargs):
            self.client = original_client(transport=httpx.MockTransport(handler))

        async def __aenter__(self):
            return self.client

        async def __aexit__(self, *args):
            await self.client.aclose()

    monkeypatch.setattr('app.ingestion.httpx.AsyncClient', DummyClient)

    settings = Settings(
        database_url='postgresql://', ingest_interval_minutes=15, gdelt_enabled=False, reliefweb_enabled=False, rss_enabled=False,
        usgs_enabled=False, firms_enabled=False, planned_enabled=False, rss_config_path='x', planned_disruptions_path=PLANNED_DISRUPTIONS_PATH,
        reliefweb_appname='app', firms_map_key='', focus_countries=['US'], focus_regions=['EUROPE'], gdelt_lookback_hours=72,
        usgs_min_magnitude=4.0, dedup_time_window_hours=6, simhash_strong_max_dist=12, simhash_ambiguous_max_dist=18,
        geohash_precision=6, time_bucket_minutes=60, monitoring_interval_minutes=30, compound_api_url='http://compound_api:8084',
        provider_connect_timeout_seconds=5.0, provider_read_timeout_seconds=20.0, provider_max_retries=1,
        provider_backoff_base_seconds=0.01, provider_backoff_max_seconds=0.02, provider_backoff_jitter_seconds=0.0,
        provider_rate_limit_per_second=100.0, provider_circuit_failure_threshold=3, provider_circuit_cooldown_seconds=60,
        provider_cache_ttl_seconds=60, provider_max_stale_seconds=600,
    )
    storage = FakeStorage()

    async def run_once():
        result = await run_ingestion_cycle(settings, storage)
        assert result['counts']['firms'] == 0

    asyncio.run(run_once())
