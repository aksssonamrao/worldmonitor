from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.domains.ingestion.ingest_common import IngestStorage
from app.domains.ingestion.provider_client import ProviderClient, RateLimiter
from app.domains.ingestion.providers.common import EventSourceCreate
from app.domains.ingestion.providers.gdelt import fetch_gdelt
from app.domains.ingestion.providers.reliefweb import fetch_reliefweb
from app.domains.ingestion.providers.rss import fetch_rss_events



def _since_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y%m%d%H%M%S')


def _settings() -> dict[str, Any]:
    return {
        'focus_countries': [c.strip().upper() for c in os.getenv('FOCUS_COUNTRIES', 'IN,AE,GB,US').split(',') if c.strip()],
        'focus_regions': [r.strip().upper() for r in os.getenv('FOCUS_REGIONS', 'EUROPE').split(',') if r.strip()],
        'event_lookback_hours': int(os.getenv('EVENT_LOOKBACK_HOURS', '72')),
        'rss_config_path': os.getenv('RSS_CONFIG_PATH', '/app/config/rss_feeds.yml'),
        'reliefweb_appname': os.getenv('RELIEFWEB_APPNAME', 'corridorone'),
        'geohash_precision': int(os.getenv('GEOHASH_PRECISION', '6')),
        'time_bucket_minutes': int(os.getenv('TIME_BUCKET_MINUTES', '60')),
        'dedup_time_window_hours': int(os.getenv('DEDUP_TIME_WINDOW_HOURS', '6')),
        'simhash_strong_max_dist': int(os.getenv('SIMHASH_STRONG_MAX_DIST', '12')),
        'provider_connect_timeout_seconds': float(os.getenv('PROVIDER_CONNECT_TIMEOUT_SECONDS', '5.0')),
        'provider_read_timeout_seconds': float(os.getenv('PROVIDER_READ_TIMEOUT_SECONDS', '20.0')),
        'provider_max_retries': int(os.getenv('PROVIDER_MAX_RETRIES', '3')),
        'provider_backoff_base_seconds': float(os.getenv('PROVIDER_BACKOFF_BASE_SECONDS', '0.5')),
        'provider_backoff_max_seconds': float(os.getenv('PROVIDER_BACKOFF_MAX_SECONDS', '8.0')),
        'provider_backoff_jitter_seconds': float(os.getenv('PROVIDER_BACKOFF_JITTER_SECONDS', '0.25')),
        'provider_rate_limit_per_second': float(os.getenv('PROVIDER_RATE_LIMIT_PER_SECOND', '5.0')),
        'provider_circuit_failure_threshold': int(os.getenv('PROVIDER_CIRCUIT_FAILURE_THRESHOLD', '3')),
        'provider_circuit_cooldown_seconds': int(os.getenv('PROVIDER_CIRCUIT_COOLDOWN_SECONDS', '60')),
        'provider_cache_ttl_seconds': int(os.getenv('PROVIDER_CACHE_TTL_SECONDS', '1800')),
        'provider_max_stale_seconds': int(os.getenv('PROVIDER_MAX_STALE_SECONDS', '10800')),
    }


def _serialize_event(event: EventSourceCreate) -> dict[str, Any]:
    item = asdict(event)
    for key in ('published_at', 'occurred_at'):
        if item.get(key):
            item[key] = item[key].isoformat()
    return item


def _deserialize_event(payload: dict[str, Any]) -> EventSourceCreate:
    return EventSourceCreate(
        source=payload['source'],
        source_event_id=payload['source_event_id'],
        title=payload['title'],
        description=payload.get('description'),
        url=payload['url'],
        published_at=datetime.fromisoformat(payload['published_at']),
        occurred_at=datetime.fromisoformat(payload['occurred_at']) if payload.get('occurred_at') else None,
        country=payload.get('country'),
        event_type=payload['event_type'],
        subtype=payload.get('subtype'),
        severity=float(payload['severity']),
        confidence=float(payload['confidence']),
        lat=float(payload['lat']),
        lon=float(payload['lon']),
        raw=payload.get('raw') or {},
    )


async def _safe_insert(storage: IngestStorage, events: list[EventSourceCreate], cfg: dict[str, Any]) -> int:
    count = 0
    for event in events:
        await storage.upsert_event_source_and_incident(
            event,
            geohash_precision=cfg['geohash_precision'],
            bucket_minutes=cfg['time_bucket_minutes'],
            dedup_window_hours=cfg['dedup_time_window_hours'],
            simhash_strong_max_dist=cfg['simhash_strong_max_dist'],
        )
        count += 1
    return count


async def _run_provider(storage: IngestStorage, provider_name: str, fetcher, cfg: dict[str, Any]) -> tuple[list[EventSourceCreate], bool]:
    status = await storage.get_provider_status(provider_name)
    provider_client = ProviderClient(
        provider=provider_name,
        max_retries=cfg['provider_max_retries'],
        backoff_base_seconds=cfg['provider_backoff_base_seconds'],
        backoff_max_seconds=cfg['provider_backoff_max_seconds'],
        jitter_seconds=cfg['provider_backoff_jitter_seconds'],
        failure_threshold=cfg['provider_circuit_failure_threshold'],
        cooldown_seconds=cfg['provider_circuit_cooldown_seconds'],
        rate_limiter=RateLimiter(cfg['provider_rate_limit_per_second']),
    )
    try:
        events = await provider_client.run(fetcher, circuit_open_until=status.get('circuit_open_until'))
        await storage.upsert_provider_cache(provider_name, 'default', {'events': [_serialize_event(e) for e in events]}, cfg['provider_cache_ttl_seconds'])
        await storage.mark_provider_success(provider_name)
        return events, False
    except Exception as exc:  # noqa: BLE001
        failures = await storage.mark_provider_failure(provider_name, str(exc), None)
        open_until = provider_client.next_circuit_open_until(failures)
        if open_until:
            await storage.update_provider_circuit_open_until(provider_name, open_until)
        cached = await storage.get_provider_cache(provider_name, 'default')
        if cached:
            stale = (datetime.now(timezone.utc) - cached['fetched_at']).total_seconds()
            if stale <= cfg['provider_max_stale_seconds']:
                events = [_deserialize_event(it) for it in (cached.get('payload_json', {}) or {}).get('events', [])]
                return events, True
        raise


async def ingest_gdelt(storage: IngestStorage) -> int:
    cfg = _settings()
    timeout = httpx.Timeout(cfg['provider_read_timeout_seconds'], connect=cfg['provider_connect_timeout_seconds'])
    async with httpx.AsyncClient(timeout=timeout) as client:
        events, _ = await _run_provider(storage, 'gdelt', lambda: fetch_gdelt(client, _since_iso(cfg['event_lookback_hours']), cfg['focus_countries']), cfg)
    count = await _safe_insert(storage, events, cfg)
    await storage.upsert_cursor('gdelt', {'last_run': datetime.now(timezone.utc).isoformat()})
    return count


async def ingest_reliefweb(storage: IngestStorage) -> int:
    cfg = _settings()
    timeout = httpx.Timeout(cfg['provider_read_timeout_seconds'], connect=cfg['provider_connect_timeout_seconds'])
    async with httpx.AsyncClient(timeout=timeout) as client:
        events, _ = await _run_provider(
            storage,
            'reliefweb',
            lambda: fetch_reliefweb(client, (datetime.now(timezone.utc) - timedelta(hours=cfg['event_lookback_hours'])).isoformat(), cfg['focus_countries'], cfg['focus_regions'], cfg['reliefweb_appname']),
            cfg,
        )
    count = await _safe_insert(storage, events, cfg)
    await storage.upsert_cursor('reliefweb', {'last_run': datetime.now(timezone.utc).isoformat()})
    return count


async def ingest_rss(storage: IngestStorage) -> int:
    cfg = _settings()
    events = await fetch_rss_events(cfg['rss_config_path'], cfg['focus_countries'], cfg['focus_regions'])
    count = await _safe_insert(storage, events, cfg)
    await storage.upsert_cursor('rss', {'last_run': datetime.now(timezone.utc).isoformat()})
    return count
