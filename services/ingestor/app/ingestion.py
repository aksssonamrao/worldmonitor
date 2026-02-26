from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .config import Settings
from .providers.firms import fetch_firms
from .providers.gdelt import fetch_gdelt
from .providers.planned import fetch_planned
from .providers.reliefweb import fetch_reliefweb
from .providers.rss import fetch_rss_events
from .providers.usgs import fetch_usgs
from .storage import IngestStorage

logger = logging.getLogger(__name__)


def since_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y%m%d%H%M%S')


async def _safe_insert_events(storage: IngestStorage, source_name: str, events: list[Any], settings: Settings) -> int:
    inserted = 0
    for event in events:
        try:
            await storage.upsert_event_source_and_incident(
                event,
                geohash_precision=settings.geohash_precision,
                bucket_minutes=settings.time_bucket_minutes,
                dedup_window_hours=settings.dedup_time_window_hours,
                simhash_strong_max_dist=settings.simhash_strong_max_dist,
            )
            inserted += 1
        except Exception:
            logger.exception('Failed to insert %s event %s', source_name, getattr(event, 'source_event_id', None))
    return inserted


async def run_ingestion_cycle(settings: Settings, storage: IngestStorage) -> dict[str, Any]:
    counts = {'gdelt': 0, 'reliefweb': 0, 'rss': 0, 'usgs': 0, 'planned': 0, 'firms': 0}
    async with httpx.AsyncClient() as client:
        if settings.gdelt_enabled:
            try:
                gdelt_events = await fetch_gdelt(client, since_iso(settings.gdelt_lookback_hours), settings.focus_countries)
                counts['gdelt'] = await _safe_insert_events(storage, 'gdelt', gdelt_events, settings)
                await storage.upsert_cursor('gdelt', {'last_run': datetime.now(timezone.utc).isoformat()})
            except Exception:
                logger.exception('GDELT ingestion failed')

        if settings.reliefweb_enabled:
            try:
                relief_events = await fetch_reliefweb(
                    client,
                    (datetime.now(timezone.utc) - timedelta(hours=settings.gdelt_lookback_hours)).isoformat(),
                    settings.focus_countries,
                    settings.focus_regions,
                    settings.reliefweb_appname,
                )
                counts['reliefweb'] = await _safe_insert_events(storage, 'reliefweb', relief_events, settings)
                await storage.upsert_cursor('reliefweb', {'last_run': datetime.now(timezone.utc).isoformat()})
            except Exception:
                logger.exception('ReliefWeb ingestion failed')

        if settings.usgs_enabled:
            try:
                events = await fetch_usgs(client, settings.gdelt_lookback_hours, settings.usgs_min_magnitude)
                counts['usgs'] = await _safe_insert_events(storage, 'usgs', events, settings)
                await storage.upsert_cursor('usgs', {'last_run': datetime.now(timezone.utc).isoformat()})
            except Exception:
                logger.exception('USGS ingestion failed')

        if settings.firms_enabled and settings.firms_map_key:
            counts['firms'] = await _safe_insert_events(storage, 'firms', await fetch_firms(), settings)
        else:
            logger.info('FIRMS disabled or missing key')

    if settings.rss_enabled:
        try:
            rss_events = await fetch_rss_events(settings.rss_config_path, settings.focus_countries, settings.focus_regions)
            counts['rss'] = await _safe_insert_events(storage, 'rss', rss_events, settings)
            await storage.upsert_cursor('rss', {'last_run': datetime.now(timezone.utc).isoformat()})
        except Exception:
            logger.exception('RSS ingestion failed')

    if settings.planned_enabled:
        try:
            planned_events = fetch_planned(settings.planned_disruptions_path)
            counts['planned'] = await _safe_insert_events(storage, 'planned', planned_events, settings)
            await storage.upsert_cursor('planned', {'last_run': datetime.now(timezone.utc).isoformat()})
        except Exception:
            logger.exception('Planned disruptions ingestion failed')

    return counts
