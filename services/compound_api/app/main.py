from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Query

app = FastAPI(title='Compound API')


@dataclass(frozen=True)
class Event:
    id: int
    type: str
    event_prob: float
    ts: datetime
    confidence_radius_m: float
    source: str
    credibility: float
    lon: float
    lat: float


@dataclass(frozen=True)
class Hazard:
    id: int
    type: str
    hazard_prob: float
    forecast_ts: datetime
    timestep: int
    run_id: str
    polygon: list[list[float]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _seed_events(now: datetime) -> list[Event]:
    return [
        Event(1, 'earthquake', 0.8, now - timedelta(hours=2), 120000, 'usgs', 0.9, -122.4, 37.8),
        Event(2, 'wildfire', 0.7, now - timedelta(hours=4), 90000, 'firms', 0.8, -121.8, 37.4),
        Event(3, 'flood', 0.6, now - timedelta(hours=8), 150000, 'glofas', 0.75, -90.1, 29.9),
        Event(4, 'storm', 0.55, now - timedelta(hours=10), 140000, 'noaa', 0.7, -80.2, 25.9),
        Event(5, 'heatwave', 0.5, now - timedelta(hours=12), 130000, 'meteo', 0.6, 2.35, 48.85),
        Event(6, 'earthquake', 0.65, now - timedelta(hours=16), 110000, 'usgs', 0.85, 139.69, 35.68),
        Event(7, 'wildfire', 0.45, now - timedelta(hours=20), 75000, 'firms', 0.7, 151.21, -33.87),
        Event(8, 'flood', 0.52, now - timedelta(hours=23), 160000, 'glofas', 0.72, 77.2, 28.6),
        Event(9, 'storm', 0.4, now - timedelta(hours=26), 100000, 'noaa', 0.65, -3.7, 40.4),
        Event(10, 'heatwave', 0.48, now - timedelta(hours=30), 90000, 'meteo', 0.58, 31.2, 30.0),
    ]


def _seed_hazards(now: datetime) -> list[Hazard]:
    return [
        Hazard(1, 'landslide', 0.7, now + timedelta(hours=6), 0, 'run-001', _rect(-122.8, 37.4, -121.9, 38.2)),
        Hazard(2, 'smoke', 0.8, now + timedelta(hours=8), 0, 'run-001', _rect(-122.2, 37.0, -121.4, 37.8)),
        Hazard(7, 'flooded_corridor', 0.95, now + timedelta(hours=5), 0, 'run-001', _rect(-122.515, 37.7, -122.455, 37.81)),
        Hazard(3, 'inundation', 0.75, now + timedelta(hours=24), 1, 'run-001', _rect(-90.7, 29.4, -89.4, 30.5)),
        Hazard(4, 'storm_surge', 0.6, now + timedelta(hours=30), 1, 'run-001', _rect(-80.8, 25.3, -79.6, 26.4)),
        Hazard(5, 'power_grid_stress', 0.55, now + timedelta(hours=54), 2, 'run-001', _rect(1.8, 48.2, 3.0, 49.2)),
        Hazard(6, 'liquefaction', 0.73, now + timedelta(hours=60), 2, 'run-001', _rect(139.1, 35.1, 140.2, 36.2)),
    ]


def _rect(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> list[list[float]]:
    return [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]


COMPATIBILITY: dict[tuple[str, str], float] = {
    ('earthquake', 'landslide'): 0.9,
    ('earthquake', 'liquefaction'): 0.95,
    ('wildfire', 'smoke'): 0.95,
    ('flood', 'inundation'): 0.95,
    ('storm', 'storm_surge'): 0.9,
    ('heatwave', 'power_grid_stress'): 0.85,
}


def compatibility(event_type: str, hazard_type: str) -> float:
    return COMPATIBILITY.get((event_type, hazard_type), 0.1)


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _meters_per_degree_lat() -> float:
    return 111_320.0


def _meters_per_degree_lon(latitude: float) -> float:
    from math import cos, radians

    return 111_320.0 * max(0.01, cos(radians(latitude)))


def _point_buffer_intersects_polygon(event: Event, polygon: list[list[float]]) -> bool:
    lons = [p[0] for p in polygon]
    lats = [p[1] for p in polygon]
    min_lon, max_lon = min(lons), max(lons)
    min_lat, max_lat = min(lats), max(lats)

    closest_lon = min(max(event.lon, min_lon), max_lon)
    closest_lat = min(max(event.lat, min_lat), max_lat)

    dx_m = abs(event.lon - closest_lon) * _meters_per_degree_lon((event.lat + closest_lat) / 2)
    dy_m = abs(event.lat - closest_lat) * _meters_per_degree_lat()
    distance_m = (dx_m * dx_m + dy_m * dy_m) ** 0.5

    return distance_m <= event.confidence_radius_m


def _event_recent(event: Event, now: datetime) -> bool:
    return event.ts >= now - timedelta(hours=24)


def _hazard_upcoming(hazard: Hazard, now: datetime) -> bool:
    return hazard.forecast_ts <= now + timedelta(hours=72)


def _fuse_alerts(events: list[Event], hazards: list[Hazard], now: datetime, timestep: int) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    alert_id = 1

    for hazard in hazards:
        if hazard.timestep != timestep or not _hazard_upcoming(hazard, now):
            continue

        for event in events:
            if not _event_recent(event, now):
                continue
            if not _point_buffer_intersects_polygon(event, hazard.polygon):
                continue

            comp = compatibility(event.type, hazard.type)
            raw_score = hazard.hazard_prob * event.event_prob * comp * event.credibility
            score = clamp(raw_score, 0.0, 1.0)

            alerts.append(
                {
                    'id': alert_id,
                    'event': event,
                    'hazard': hazard,
                    'score': score,
                    'created_at': now,
                    'details': {
                        'event_source': event.source,
                        'event_ts': event.ts.isoformat(),
                        'hazard_forecast_ts': hazard.forecast_ts.isoformat(),
                    },
                    'explanation': {
                        'hazard_prob': hazard.hazard_prob,
                        'event_prob': event.event_prob,
                        'compatibility': comp,
                        'credibility': event.credibility,
                        'raw_score': raw_score,
                        'score': score,
                    },
                }
            )
            alert_id += 1

    return alerts


def _hazard_feature(hazard: Hazard) -> dict[str, Any]:
    return {
        'type': 'Feature',
        'geometry': {'type': 'Polygon', 'coordinates': [hazard.polygon]},
        'properties': {
            'id': hazard.id,
            'type': hazard.type,
            'hazard_prob': hazard.hazard_prob,
            'forecast_ts': hazard.forecast_ts.isoformat(),
            'timestep': hazard.timestep,
            'run_id': hazard.run_id,
        },
    }


def _alert_feature(alert: dict[str, Any]) -> dict[str, Any]:
    event: Event = alert['event']
    hazard: Hazard = alert['hazard']

    return {
        'type': 'Feature',
        'geometry': {'type': 'Point', 'coordinates': [event.lon, event.lat]},
        'properties': {
            'id': alert['id'],
            'event_id': event.id,
            'hazard_id': hazard.id,
            'event_type': event.type,
            'hazard_type': hazard.type,
            'score': alert['score'],
            'created_at': alert['created_at'].isoformat(),
            'details': alert['details'],
            'explanation': alert['explanation'],
        },
    }


@app.get('/compound/health')
def compound_health() -> dict[str, bool]:
    return {'ok': True}


@app.get('/compound/hazards')
def get_hazards(run_id: str = Query(default='latest'), timestep: int = Query(default=0, ge=0)) -> dict[str, Any]:
    now = _utc_now()
    all_hazards = _seed_hazards(now)
    if run_id == 'latest':
        run_ids = sorted({h.run_id for h in all_hazards})
        resolved = run_ids[-1] if run_ids else run_id
    else:
        resolved = run_id
    hazards = [h for h in all_hazards if h.timestep == timestep and h.run_id == resolved]

    return {'type': 'FeatureCollection', 'features': [_hazard_feature(h) for h in hazards]}


@app.get('/compound/alerts')
def get_alerts(timestep: int = Query(default=0, ge=0)) -> dict[str, Any]:
    now = _utc_now()
    events = _seed_events(now)
    hazards = _seed_hazards(now)
    alerts = _fuse_alerts(events, hazards, now, timestep)

    return {'type': 'FeatureCollection', 'features': [_alert_feature(alert) for alert in alerts]}
