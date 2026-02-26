from __future__ import annotations

import json
from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    ingest_interval_minutes: int
    gdelt_enabled: bool
    reliefweb_enabled: bool
    rss_enabled: bool
    rss_config_path: str
    focus_countries: list[str]
    focus_regions: list[str]
    gdelt_lookback_hours: int


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
        rss_config_path=getenv('RSS_CONFIG_PATH', '/app/config/rss_feeds.yml'),
        focus_countries=[c.strip().upper() for c in getenv('FOCUS_COUNTRIES', 'IN,AE,GB,US').split(',') if c.strip()],
        focus_regions=[r.strip().upper() for r in getenv('FOCUS_REGIONS', 'EUROPE').split(',') if r.strip()],
        gdelt_lookback_hours=int(getenv('EVENT_LOOKBACK_HOURS', '72')),
    )
