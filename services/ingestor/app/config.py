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


def _as_bool(name: str, default: bool) -> bool:
    raw = getenv(name)
    if raw is None:
        return default
    return raw.lower() in {'1', 'true', 'yes', 'on'}


def load_settings() -> Settings:
    return Settings(
        database_url=getenv('DATABASE_URL', 'postgresql://worldmonitor:worldmonitor@postgis:5432/worldmonitor'),
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
        compound_api_url=getenv('COMPOUND_API_URL', 'http://compound_api:8084').rstrip('/'),
    )
