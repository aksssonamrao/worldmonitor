from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import Settings
from app.sources import fetch_gdelt, fetch_reliefweb, fetch_rss_events
from app.storage import IngestStorage


def since_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y%m%d%H%M%S')


async def run_ingestion_cycle(settings: Settings, storage: IngestStorage) -> dict[str, Any]:
    counts = {'gdelt': 0, 'reliefweb': 0, 'rss': 0}
    async with httpx.AsyncClient() as client:
        if settings.gdelt_enabled:
            gdelt_events = await fetch_gdelt(client, since_iso(settings.gdelt_lookback_hours), settings.focus_countries)
            for event in gdelt_events:
                await storage.insert_event(event)
            counts['gdelt'] = len(gdelt_events)
            await storage.upsert_cursor('gdelt', {'last_run': datetime.now(timezone.utc).isoformat()})

        if settings.reliefweb_enabled:
            relief_events = await fetch_reliefweb(client, (datetime.now(timezone.utc) - timedelta(hours=settings.gdelt_lookback_hours)).isoformat())
            for event in relief_events:
                await storage.insert_event(event)
            counts['reliefweb'] = len(relief_events)
            await storage.upsert_cursor('reliefweb', {'last_run': datetime.now(timezone.utc).isoformat()})

    if settings.rss_enabled:
        rss_events = await fetch_rss_events(settings.rss_config_path)
        for event in rss_events:
            await storage.insert_event(event)
        counts['rss'] = len(rss_events)
        await storage.upsert_cursor('rss', {'last_run': datetime.now(timezone.utc).isoformat()})
    return counts
