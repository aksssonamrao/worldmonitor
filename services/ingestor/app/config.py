from __future__ import annotations

from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    ingest_interval_minutes: int
    gdelt_enabled: bool
    reliefweb_enabled: bool
    rss_enabled: bool
    usgs_enabled: bool
    firms_enabled: bool
    planned_enabled: bool
    rss_config_path: str
    planned_disruptions_path: str
    reliefweb_appname: str
    firms_map_key: str
    focus_countries: list[str]
    focus_regions: list[str]
    gdelt_lookback_hours: int
    usgs_min_magnitude: float
    dedup_time_window_hours: int
    simhash_strong_max_dist: int
    simhash_ambiguous_max_dist: int
    geohash_precision: int
    time_bucket_minutes: int
    monitoring_interval_minutes: int
    compound_api_url: str
    provider_connect_timeout_seconds: float
    provider_read_timeout_seconds: float
    provider_max_retries: int
    provider_backoff_base_seconds: float
    provider_backoff_max_seconds: float
    provider_backoff_jitter_seconds: float
    provider_rate_limit_per_second: float
    provider_circuit_failure_threshold: int
    provider_circuit_cooldown_seconds: int
    provider_cache_ttl_seconds: int
    provider_max_stale_seconds: int


def _as_bool(name: str, default: bool) -> bool:
    raw = getenv(name)
    if raw is None:
        return default
    return raw.lower() in {'1', 'true', 'yes', 'on'}


def _required(name: str) -> str:
    value = getenv(name, '').strip()
    if not value:
        raise RuntimeError(f'{name} is required but missing. Set it in environment/.env before starting ingestor.')
    return value


def load_settings() -> Settings:
    return Settings(
        database_url=_required('DATABASE_URL'),
        ingest_interval_minutes=int(getenv('INGEST_INTERVAL_MINUTES', '15')),
        gdelt_enabled=_as_bool('GDELT_ENABLED', True),
        reliefweb_enabled=_as_bool('RELIEFWEB_ENABLED', True),
        rss_enabled=_as_bool('RSS_ENABLED', False),
        usgs_enabled=_as_bool('USGS_ENABLED', True),
        firms_enabled=_as_bool('FIRMS_ENABLED', False),
        planned_enabled=_as_bool('PLANNED_ENABLED', True),
        rss_config_path=getenv('RSS_CONFIG_PATH', '/app/config/rss_feeds.yml'),
        planned_disruptions_path=getenv('PLANNED_DISRUPTIONS_PATH', '/app/config/planned_disruptions.yml'),
        reliefweb_appname=getenv('RELIEFWEB_APPNAME', 'worldmonitor'),
        firms_map_key=getenv('FIRMS_MAP_KEY', ''),
        focus_countries=[c.strip().upper() for c in getenv('FOCUS_COUNTRIES', 'IN,AE,GB,US').split(',') if c.strip()],
        focus_regions=[r.strip().upper() for r in getenv('FOCUS_REGIONS', 'EUROPE').split(',') if r.strip()],
        gdelt_lookback_hours=int(getenv('EVENT_LOOKBACK_HOURS', '72')),
        usgs_min_magnitude=float(getenv('USGS_MIN_MAGNITUDE', '4')),
        dedup_time_window_hours=int(getenv('DEDUP_TIME_WINDOW_HOURS', '6')),
        simhash_strong_max_dist=int(getenv('SIMHASH_STRONG_MAX_DIST', '12')),
        simhash_ambiguous_max_dist=int(getenv('SIMHASH_AMBIGUOUS_MAX_DIST', '18')),
        geohash_precision=int(getenv('GEOHASH_PRECISION', '6')),
        time_bucket_minutes=int(getenv('TIME_BUCKET_MINUTES', '60')),
        monitoring_interval_minutes=int(getenv('MONITORING_INTERVAL_MINUTES', '30')),
        compound_api_url=getenv('COMPOUND_API_URL', 'http://compound_api:8090').rstrip('/'),
        provider_connect_timeout_seconds=float(getenv('PROVIDER_CONNECT_TIMEOUT_SECONDS', '5.0')),
        provider_read_timeout_seconds=float(getenv('PROVIDER_READ_TIMEOUT_SECONDS', '20.0')),
        provider_max_retries=int(getenv('PROVIDER_MAX_RETRIES', '3')),
        provider_backoff_base_seconds=float(getenv('PROVIDER_BACKOFF_BASE_SECONDS', '0.5')),
        provider_backoff_max_seconds=float(getenv('PROVIDER_BACKOFF_MAX_SECONDS', '8.0')),
        provider_backoff_jitter_seconds=float(getenv('PROVIDER_BACKOFF_JITTER_SECONDS', '0.25')),
        provider_rate_limit_per_second=float(getenv('PROVIDER_RATE_LIMIT_PER_SECOND', '5.0')),
        provider_circuit_failure_threshold=int(getenv('PROVIDER_CIRCUIT_FAILURE_THRESHOLD', '3')),
        provider_circuit_cooldown_seconds=int(getenv('PROVIDER_CIRCUIT_COOLDOWN_SECONDS', '60')),
        provider_cache_ttl_seconds=int(getenv('PROVIDER_CACHE_TTL_SECONDS', '1800')),
        provider_max_stale_seconds=int(getenv('PROVIDER_MAX_STALE_SECONDS', '10800')),
    )
