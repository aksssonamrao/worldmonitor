from __future__ import annotations

import asyncio
import json

import httpx

from app.config import Settings
from app.ingestion import run_ingestion_cycle
from app.sources import fetch_gdelt, fetch_reliefweb


class FakeStorage:
    def __init__(self):
        self.events = {}
        self.cursors = {}

    async def insert_event(self, event):
        self.events[(event['source'], event['source_event_id'])] = event

    async def upsert_cursor(self, source, cursor):
        self.cursors[source] = cursor


def test_gdelt_ingest_writes_events():
    def handler(request: httpx.Request) -> httpx.Response:
        assert 'api.gdeltproject.org' in str(request.url)
        return httpx.Response(
            200,
            json={
                'articles': [
                    {
                        'url': 'https://example.com/a',
                        'title': 'Major protest blocks port access',
                        'seendate': '2026-01-01T00:00:00Z',
                        'sourcecountry': 'IN',
                        'domain': 'example.com',
                        'locations': [{'lat': 19.1, 'lon': 72.8}],
                        'sourceCollection': 'web',
                        'themes': ['PROTEST'],
                        'tone': -5,
                    }
                ]
            },
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            events = await fetch_gdelt(client, '20260101000000', ['IN'])
        assert len(events) == 1
        assert events[0]['event_type'] == 'PROTEST'

    asyncio.run(run())


def test_reliefweb_ingest_writes_events():
    def handler(request: httpx.Request) -> httpx.Response:
        assert 'reliefweb' in str(request.url)
        return httpx.Response(
            200,
            json={
                'data': [
                    {
                        'id': 'rw-1',
                        'fields': {
                            'title': 'Flooding impacts logistics routes',
                            'url': 'https://reliefweb.int/report/a',
                            'date': {'created': '2026-01-01T00:00:00Z'},
                            'origin': {'lat': 25.2, 'lon': 55.3},
                            'primary_country': {'iso3': 'ARE'},
                            'body': 'roads flooded',
                        },
                    }
                ]
            },
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            events = await fetch_reliefweb(client, '2026-01-01T00:00:00+00:00')
        assert len(events) == 1
        assert events[0]['event_type'] == 'DISASTER'

    asyncio.run(run())


def test_dedup_on_source_event_id(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if 'gdeltproject' in str(request.url):
            return httpx.Response(
                200,
                json={
                    'articles': [
                        {
                            'url': 'https://example.com/a',
                            'title': 'Port shutdown after blackout',
                            'seendate': '2026-01-01T00:00:00Z',
                            'sourcecountry': 'US',
                            'domain': 'example.com',
                            'locations': [{'lat': 40.0, 'lon': -74.0}],
                        }
                    ]
                },
            )
        return httpx.Response(200, json={'data': []})

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
        database_url='postgresql://',
        ingest_interval_minutes=15,
        gdelt_enabled=True,
        reliefweb_enabled=True,
        rss_enabled=False,
        rss_config_path='x',
        focus_countries=['US'],
        focus_regions=['EUROPE'],
        gdelt_lookback_hours=72,
    )
    storage = FakeStorage()

    async def run_twice():
        await run_ingestion_cycle(settings, storage)
        await run_ingestion_cycle(settings, storage)

    asyncio.run(run_twice())
    assert len(storage.events) == 1
