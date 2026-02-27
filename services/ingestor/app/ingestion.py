from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable

import httpx

from .config import Settings
from .provider_client import ProviderClient, RateLimiter
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


def _serialize_event(event: Any) -> dict[str, Any]:
    item = asdict(event)
    for key in ('published_at', 'occurred_at'):
        if item.get(key):
            item[key] = item[key].isoformat()
    return item


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


async def _run_provider(
    *,
    storage: IngestStorage,
    provider_name: str,
    cache_key: str,
    cache_ttl_seconds: int,
    max_stale_seconds: int,
    provider_client: ProviderClient,
    fetcher: Callable[[], Awaitable[list[Any]]],
) -> tuple[list[Any], bool, dict[str, Any]]:
    status = await storage.get_provider_status(provider_name)
    try:
        events = await provider_client.run(
            fetcher,
            consecutive_failures=int(status.get('consecutive_failures', 0) or 0),
            circuit_open_until=status.get('circuit_open_until'),
        )
        await storage.upsert_provider_cache(
            provider_name,
            cache_key,
            {'events': [_serialize_event(event) for event in events]},
            cache_ttl_seconds,
        )
        await storage.mark_provider_success(provider_name)
        return events, False, {'degraded': False, 'fetched_at': datetime.now(timezone.utc).isoformat()}
    except Exception as exc:  # noqa: BLE001
        failures = await storage.mark_provider_failure(provider_name, str(exc), None)
        circuit_open_until = provider_client.next_circuit_open_until(failures)
        if circuit_open_until is not None:
            await storage.mark_provider_failure(provider_name, str(exc), circuit_open_until)
        cached = await storage.get_provider_cache(provider_name, cache_key)
        if cached:
            stale_seconds = (datetime.now(timezone.utc) - cached['fetched_at']).total_seconds()
            if stale_seconds <= max_stale_seconds:
                return [], True, {
                    'degraded': True,
                    'fetched_at': cached['fetched_at'].isoformat(),
                    'error': str(exc),
                    'cache_used': True,
                }
        return [], True, {'degraded': True, 'error': str(exc), 'cache_used': False}


async def run_ingestion_cycle(settings: Settings, storage: IngestStorage) -> dict[str, Any]:
    counts = {'gdelt': 0, 'reliefweb': 0, 'rss': 0, 'usgs': 0, 'planned': 0, 'firms': 0}
    provider_meta: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.provider_read_timeout_seconds, connect=settings.provider_connect_timeout_seconds)) as client:
        providers: list[tuple[str, Callable[[], Awaitable[list[Any]]], bool]] = []
        if settings.gdelt_enabled:
            providers.append(('gdelt', lambda: fetch_gdelt(client, since_iso(settings.gdelt_lookback_hours), settings.focus_countries), True))
        if settings.reliefweb_enabled:
            providers.append((
                'reliefweb',
                lambda: fetch_reliefweb(
                    client,
                    (datetime.now(timezone.utc) - timedelta(hours=settings.gdelt_lookback_hours)).isoformat(),
                    settings.focus_countries,
                    settings.focus_regions,
                    settings.reliefweb_appname,
                ),
                True,
            ))
        if settings.usgs_enabled:
            providers.append(('usgs', lambda: fetch_usgs(client, settings.gdelt_lookback_hours, settings.usgs_min_magnitude), True))

        for provider_name, fetcher, update_cursor in providers:
            try:
                events, degraded, meta = await _run_provider(
                    storage=storage,
                    provider_name=provider_name,
                    cache_key='default',
                    cache_ttl_seconds=settings.provider_cache_ttl_seconds,
                    max_stale_seconds=settings.provider_max_stale_seconds,
                    provider_client=ProviderClient(
                        provider=provider_name,
                        max_retries=settings.provider_max_retries,
                        backoff_base_seconds=settings.provider_backoff_base_seconds,
                        backoff_max_seconds=settings.provider_backoff_max_seconds,
                        jitter_seconds=settings.provider_backoff_jitter_seconds,
                        failure_threshold=settings.provider_circuit_failure_threshold,
                        cooldown_seconds=settings.provider_circuit_cooldown_seconds,
                        rate_limiter=RateLimiter(settings.provider_rate_limit_per_second),
                    ),
                    fetcher=fetcher,
                )
                counts[provider_name] = await _safe_insert_events(storage, provider_name, events, settings)
                provider_meta[provider_name] = meta
                if update_cursor:
                    await storage.upsert_cursor(provider_name, {'last_run': datetime.now(timezone.utc).isoformat(), 'degraded': degraded})
            except Exception:
                logger.exception('%s ingestion failed', provider_name)

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

    return {'counts': counts, 'providers': provider_meta}
