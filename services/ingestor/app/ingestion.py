from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .config import Settings
from .sources import fetch_gdelt, fetch_reliefweb, fetch_rss_events
from .storage import IngestStorage

logger = logging.getLogger(__name__)


def since_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y%m%d%H%M%S')


async def _safe_insert_events(storage: IngestStorage, source_name: str, events: list[dict[str, Any]]) -> int:
    inserted = 0
    for event in events:
        try:
            await storage.insert_event(event)
            inserted += 1
        except Exception:
            logger.exception('Failed to insert %s event %s', source_name, event.get('source_event_id'))
    return inserted


async def run_ingestion_cycle(settings: Settings, storage: IngestStorage) -> dict[str, Any]:
    counts = {'gdelt': 0, 'reliefweb': 0, 'rss': 0}
    async with httpx.AsyncClient() as client:
        if settings.gdelt_enabled:
            try:
                gdelt_events = await fetch_gdelt(client, since_iso(settings.gdelt_lookback_hours), settings.focus_countries)
                counts['gdelt'] = await _safe_insert_events(storage, 'gdelt', gdelt_events)
                await storage.upsert_cursor('gdelt', {'last_run': datetime.now(timezone.utc).isoformat()})
            except Exception:
                logger.exception('GDELT ingestion failed')
                counts['gdelt'] = 0

        if settings.reliefweb_enabled:
            try:
                relief_events = await fetch_reliefweb(
                    client,
                    (datetime.now(timezone.utc) - timedelta(hours=settings.gdelt_lookback_hours)).isoformat(),
                    settings.focus_countries,
                    settings.focus_regions,
                )
                counts['reliefweb'] = await _safe_insert_events(storage, 'reliefweb', relief_events)
                await storage.upsert_cursor('reliefweb', {'last_run': datetime.now(timezone.utc).isoformat()})
            except Exception:
                logger.exception('ReliefWeb ingestion failed')
                counts['reliefweb'] = 0

    if settings.rss_enabled:
        try:
            rss_events = await fetch_rss_events(settings.rss_config_path, settings.focus_countries, settings.focus_regions)
            counts['rss'] = await _safe_insert_events(storage, 'rss', rss_events)
            await storage.upsert_cursor('rss', {'last_run': datetime.now(timezone.utc).isoformat()})
        except Exception:
            logger.exception('RSS ingestion failed')
            counts['rss'] = 0
    return counts
