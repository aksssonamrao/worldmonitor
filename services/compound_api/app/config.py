from __future__ import annotations

from dataclasses import dataclass
from os import getenv


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


def _csv_ints(value: str, *, default: str) -> list[int]:
    raw = value or default
    return [int(part.strip()) for part in raw.split(',') if part.strip()]


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
        hazard_grid_km=float(getenv('HAZARD_GRID_KM', '25')),
        hazard_max_points=int(getenv('HAZARD_MAX_POINTS', '300')),
        hazard_cache_ttl_min=int(getenv('HAZARD_CACHE_TTL_MIN', '60')),
        wind_threshold_kph=float(getenv('WIND_THRESHOLD_KPH', '50')),
        wind_max_kph=float(getenv('WIND_MAX_KPH', '120')),
        rain_threshold_mm_hr=float(getenv('RAIN_THRESHOLD_MM_HR', '10')),
        rain_max_mm_hr=float(getenv('RAIN_MAX_MM_HR', '50')),
        heat_threshold_c=float(getenv('HEAT_THRESHOLD_C', '38')),
        heat_max_c=float(getenv('HEAT_MAX_C', '48')),
        forecast_hours=int(getenv('FORECAST_HOURS', '72')),
        timestep_hours=_csv_ints(getenv('TIMESTEP_HOURS', ''), default='0,6,12,24,48,72'),
        default_bbox=_bbox(getenv('DEFAULT_BBOX', ''), default='72.0,8.0,88.0,23.0'),
        max_bbox_area_deg2=float(getenv('MAX_BBOX_AREA_DEG2', '50')),
        max_qps=float(getenv('MAX_QPS', '5')),
    )
