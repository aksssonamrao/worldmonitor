from __future__ import annotations

from dataclasses import dataclass
from os import getenv
from typing import Any
import json


@dataclass(frozen=True)
class Settings:
    database_url: str
    google_weather_api_key: str
    google_weather_base_url: str
    hazard_grid_km: float
    hazard_max_points: int
    hazard_cache_ttl_min: int
    wind_threshold_kph: float
    wind_max_kph: float
    rain_threshold_mm_hr: float
    rain_max_mm_hr: float
    heat_threshold_c: float
    heat_max_c: float
    forecast_hours: int
    timestep_hours: list[int]
    default_bbox: tuple[float, float, float, float]
    max_bbox_area_deg2: float
    max_qps: float
    event_lookback_hours: int
    alert_score_threshold: float
    event_type_weights: dict[str, float]
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


def _csv_ints(value: str, *, default: str) -> list[int]:
    raw = value or default
    return [int(part.strip()) for part in raw.split(',') if part.strip()]


def _parse_float(name: str, raw: str | None, default: float) -> float:
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise RuntimeError(f"Invalid value for {name}: expected a float, got {raw!r}")


def _parse_int(name: str, raw: str | None, default: int) -> int:
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"Invalid value for {name}: expected an integer, got {raw!r}")




def _parse_json(name: str, raw: str | None, default: dict[str, Any]) -> dict[str, Any]:
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid value for {name}: expected valid JSON, got {raw!r}. Error: {e}")
    if not isinstance(value, dict):
        raise RuntimeError(f"Invalid value for {name}: expected JSON object, got {type(value).__name__}")
    return value

def _bbox(value: str, *, default: str) -> tuple[float, float, float, float]:
    raw = value or default
    parts = [float(part.strip()) for part in raw.split(',') if part.strip()]
    if len(parts) != 4:
        raise RuntimeError('DEFAULT_BBOX must have four comma-separated float values: minLon,minLat,maxLon,maxLat')

    min_lon, min_lat, max_lon, max_lat = parts

    # Validate longitude and latitude ranges
    if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
        raise RuntimeError('DEFAULT_BBOX longitude values must be between -180 and 180 degrees.')
    if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
        raise RuntimeError('DEFAULT_BBOX latitude values must be between -90 and 90 degrees.')

    # Validate that minimums are less than maximums
    if min_lon >= max_lon:
        raise RuntimeError('DEFAULT_BBOX must have minLon < maxLon.')
    if min_lat >= max_lat:
        raise RuntimeError('DEFAULT_BBOX must have minLat < maxLat.')

    return min_lon, min_lat, max_lon, max_lat
def load_settings() -> Settings:
    database_url = getenv('DATABASE_URL', 'postgresql://worldmonitor:worldmonitor@postgis:5432/worldmonitor')
    google_weather_api_key = getenv('GOOGLE_WEATHER_API_KEY', '').strip()
    if not google_weather_api_key:
        raise RuntimeError('GOOGLE_WEATHER_API_KEY is required for compound-api startup (google_weather is the only provider).')

    return Settings(
        database_url=database_url,
        google_weather_api_key=google_weather_api_key,
        google_weather_base_url=getenv('GOOGLE_WEATHER_BASE_URL', 'https://weather.googleapis.com/v1').rstrip('/'),
        hazard_grid_km=_parse_float('HAZARD_GRID_KM', getenv('HAZARD_GRID_KM'), 25.0),
        hazard_max_points=_parse_int('HAZARD_MAX_POINTS', getenv('HAZARD_MAX_POINTS'), 300),
        hazard_cache_ttl_min=_parse_int('HAZARD_CACHE_TTL_MIN', getenv('HAZARD_CACHE_TTL_MIN'), 60),
        wind_threshold_kph=_parse_float('WIND_THRESHOLD_KPH', getenv('WIND_THRESHOLD_KPH'), 50.0),
        wind_max_kph=_parse_float('WIND_MAX_KPH', getenv('WIND_MAX_KPH'), 120.0),
        rain_threshold_mm_hr=_parse_float('RAIN_THRESHOLD_MM_HR', getenv('RAIN_THRESHOLD_MM_HR'), 10.0),
        rain_max_mm_hr=_parse_float('RAIN_MAX_MM_HR', getenv('RAIN_MAX_MM_HR'), 50.0),
        heat_threshold_c=_parse_float('HEAT_THRESHOLD_C', getenv('HEAT_THRESHOLD_C'), 38.0),
        heat_max_c=_parse_float('HEAT_MAX_C', getenv('HEAT_MAX_C'), 48.0),
        forecast_hours=_parse_int('FORECAST_HOURS', getenv('FORECAST_HOURS'), 72),
        timestep_hours=_csv_ints(getenv('TIMESTEP_HOURS', ''), default='0,6,12,24,48,72'),
        default_bbox=_bbox(getenv('DEFAULT_BBOX', ''), default='72.0,8.0,88.0,23.0'),
        max_bbox_area_deg2=_parse_float('MAX_BBOX_AREA_DEG2', getenv('MAX_BBOX_AREA_DEG2'), 50.0),
        max_qps=_parse_float('MAX_QPS', getenv('MAX_QPS'), 5.0),
        event_lookback_hours=_parse_int('EVENT_LOOKBACK_HOURS', getenv('EVENT_LOOKBACK_HOURS'), 72),
        alert_score_threshold=_parse_float('ALERT_SCORE_THRESHOLD', getenv('ALERT_SCORE_THRESHOLD'), 20.0),
        event_type_weights=_parse_json('EVENT_TYPE_WEIGHTS_JSON', getenv('EVENT_TYPE_WEIGHTS_JSON'), {'PROTEST': 1.2, 'STRIKE': 1.2, 'CONFLICT': 1.5, 'DISASTER': 1.4, 'OUTAGE': 1.3, 'ACCIDENT': 1.1, 'OTHER': 1.0}),
        provider_connect_timeout_seconds=_parse_float('PROVIDER_CONNECT_TIMEOUT_SECONDS', getenv('PROVIDER_CONNECT_TIMEOUT_SECONDS'), 5.0),
        provider_read_timeout_seconds=_parse_float('PROVIDER_READ_TIMEOUT_SECONDS', getenv('PROVIDER_READ_TIMEOUT_SECONDS'), 20.0),
        provider_max_retries=_parse_int('PROVIDER_MAX_RETRIES', getenv('PROVIDER_MAX_RETRIES'), 3),
        provider_backoff_base_seconds=_parse_float('PROVIDER_BACKOFF_BASE_SECONDS', getenv('PROVIDER_BACKOFF_BASE_SECONDS'), 0.5),
        provider_backoff_max_seconds=_parse_float('PROVIDER_BACKOFF_MAX_SECONDS', getenv('PROVIDER_BACKOFF_MAX_SECONDS'), 8.0),
        provider_backoff_jitter_seconds=_parse_float('PROVIDER_BACKOFF_JITTER_SECONDS', getenv('PROVIDER_BACKOFF_JITTER_SECONDS'), 0.25),
        provider_rate_limit_per_second=_parse_float('PROVIDER_RATE_LIMIT_PER_SECOND', getenv('PROVIDER_RATE_LIMIT_PER_SECOND'), 5.0),
        provider_circuit_failure_threshold=_parse_int('PROVIDER_CIRCUIT_FAILURE_THRESHOLD', getenv('PROVIDER_CIRCUIT_FAILURE_THRESHOLD'), 3),
        provider_circuit_cooldown_seconds=_parse_int('PROVIDER_CIRCUIT_COOLDOWN_SECONDS', getenv('PROVIDER_CIRCUIT_COOLDOWN_SECONDS'), 60),
        provider_cache_ttl_seconds=_parse_int('PROVIDER_CACHE_TTL_SECONDS', getenv('PROVIDER_CACHE_TTL_SECONDS'), 1800),
        provider_max_stale_seconds=_parse_int('PROVIDER_MAX_STALE_SECONDS', getenv('PROVIDER_MAX_STALE_SECONDS'), 10800),
    )
