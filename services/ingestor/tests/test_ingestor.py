from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from app.config import Settings
from app.ingestion import run_ingestion_cycle
from app.providers.common import EventSourceCreate
from app.providers.gdelt import fetch_gdelt
from app.providers.planned import fetch_planned
from app.providers.reliefweb import fetch_reliefweb
from app.providers.usgs import fetch_usgs


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
    events = fetch_planned('config/planned_disruptions.yml')
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
        database_url='postgresql://', ingest_interval_minutes=15, gdelt_enabled=True, reliefweb_enabled=True, rss_enabled=False,
        usgs_enabled=True, firms_enabled=False, planned_enabled=False, rss_config_path='x', planned_disruptions_path='config/planned_disruptions.yml',
        reliefweb_appname='app', firms_map_key='', focus_countries=['US'], focus_regions=['EUROPE'], gdelt_lookback_hours=72,
        usgs_min_magnitude=4.0, dedup_time_window_hours=6, simhash_strong_max_dist=12, simhash_ambiguous_max_dist=18,
        geohash_precision=6, time_bucket_minutes=60, monitoring_interval_minutes=30, compound_api_url='http://compound_api:8084',
    )
    storage = FakeStorage()

    async def run_once():
        counts = await run_ingestion_cycle(settings, storage)
        assert counts['firms'] == 0

    asyncio.run(run_once())
