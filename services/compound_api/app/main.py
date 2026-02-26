from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from os import getenv
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field

from fastapi import FastAPI, HTTPException, Query

from app.config import Settings, load_settings
from app.hazards.generator import HazardGenerator
from app.storage import Storage
from app.weather.google_weather_client import GoogleWeatherClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configured = True
    startup_error = None
    settings = None
    try:
        settings = load_settings()
    except RuntimeError as exc:
        configured = False
        startup_error = str(exc)
        if getenv('ALLOW_MISCONFIGURED_STARTUP', '0') != '1':
            raise

    app.state.weather_api_configured = configured
    app.state.last_hazard_run = None
    app.state.last_hazard_error = startup_error
    if settings:
        app.state.settings = settings
        storage = Storage(settings.database_url)
        await storage.connect()
        app.state.storage = storage
        app.state.weather_client = GoogleWeatherClient(settings.google_weather_base_url, settings.google_weather_api_key, settings.max_qps)
        app.state.generator = HazardGenerator(settings, app.state.storage, app.state.weather_client)
    else:
        app.state.storage = None
        app.state.weather_client = None
        app.state.generator = None
    yield
    weather_client = getattr(app.state, 'weather_client', None)
    if weather_client is not None:
        try:
            await weather_client.aclose()
        except Exception:
            logger.exception('Error closing weather client')
        app.state.weather_client = None
    storage = getattr(app.state, 'storage', None)
    if storage is not None:
        try:
            await storage.close()
        except Exception:
            logger.exception('Error closing storage')
        app.state.storage = None


app = FastAPI(title='Compound API', lifespan=lifespan)


class PointIn(BaseModel):
    lat: float
    lon: float


class RouteOptionsIn(BaseModel):
    origin: PointIn
    destination: PointIn
    depart_time: str
    arrive_by: str
    risk_appetite: float = Field(ge=0, le=1)


class RouteScoreIn(BaseModel):
    geometry: dict[str, Any]
    depart_time: str
    arrive_by: str
    run_id: str = 'latest'
    timestep: int = 0


def _parse_bbox(raw_bbox: str | None) -> list[float] | None:
    if not raw_bbox:
        return None
    try:
        parts = [float(v.strip()) for v in raw_bbox.split(',')]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='bbox must be comma separated floats') from exc
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail='bbox must have 4 values min_lon,min_lat,max_lon,max_lat')
    min_lon, min_lat, max_lon, max_lat = parts
    if not (min_lon < max_lon and min_lat < max_lat):
        raise HTTPException(status_code=400, detail='bbox min values must be less than max values')
    return parts


async def _run_id_param(run_id: str | None) -> str:
    if run_id and run_id != 'latest':
        return run_id
    latest = await app.state.storage.latest_run()
    if not latest:
        raise HTTPException(status_code=404, detail='no hazard runs')
    return latest['run_id']


def _parse_route_datetime(raw_value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw_value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f'{field_name} must be a valid ISO-8601 datetime') from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=422, detail=f'{field_name} must include timezone information')
    return parsed


@app.get('/compound/health')
async def compound_health() -> dict[str, Any]:
    ingestion_state = {}
    storage = getattr(app.state, 'storage', None)
    if storage is not None:
        ingestion_state = await storage.list_ingestion_state()
    return {
        'ok': True,
        'weather_api_configured': bool(getattr(app.state, 'weather_api_configured', False)),
        'last_hazard_run': getattr(app.state, 'last_hazard_run', None),
        'last_hazard_error': getattr(app.state, 'last_hazard_error', None),
        'ingestion_state': ingestion_state,
    }


@app.post('/compound/hazards/generate')
async def generate_hazards(body: dict[str, Any]) -> dict[str, Any]:
    if not getattr(app.state, 'weather_api_configured', False):
        raise HTTPException(status_code=503, detail='google weather is not configured')

    settings: Settings = app.state.settings
    run_id = body.get('run_id') or datetime.now(timezone.utc).strftime('run-%Y%m%d%H%M%S')
    raw_bbox = body.get('bbox')
    if raw_bbox is None:
        bbox = list(settings.default_bbox)
    else:
        if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
            raise HTTPException(status_code=400, detail='bbox must be a list of 4 coordinates [min_lon, min_lat, max_lon, max_lat]')
        try:
            bbox = [float(v) for v in raw_bbox]
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail='bbox values must be numeric')
    timestep_hours = body.get('timestep_hours') or [0, 6, 12, 24]
    hazard_types = body.get('hazard_types') or ['WIND', 'RAIN', 'HEAT']

    result = await app.state.generator.generate(run_id, bbox, timestep_hours, hazard_types)
    app.state.last_hazard_run = datetime.now(timezone.utc).isoformat()
    app.state.last_hazard_error = None
    latest = await app.state.storage.latest_run() or {}
    return {**result, 'started_at': latest.get('started_at'), 'finished_at': latest.get('finished_at')}


@app.get('/compound/hazards')
async def get_hazards(timestep: int = Query(default=0, ge=0), run_id: str = 'latest') -> dict[str, Any]:
    resolved_run_id = await _run_id_param(run_id)
    hazards = await app.state.storage.list_hazards(resolved_run_id, timestep)
    features = [
        {
            'type': 'Feature',
            'geometry': hazard['geometry'],
            'properties': {
                'type': hazard['type'],
                'hazard_prob': hazard['hazard_prob'],
                'forecast_ts': hazard['forecast_ts'].isoformat(),
                'provider': hazard['provider'],
                'generated_at': hazard['generated_at'].isoformat(),
            },
        }
        for hazard in hazards
    ]
    return {'type': 'FeatureCollection', 'features': features}


@app.get('/compound/events')
async def get_events(
    bbox: str | None = None,
    since_hours: int = Query(default=72, ge=1, le=720),
    types: str | None = None,
) -> dict[str, Any]:
    parsed_bbox = _parse_bbox(bbox)
    type_list = [part.strip().upper() for part in types.split(',') if part.strip()] if types else None
    events = await app.state.storage.list_events(since_hours=since_hours, event_types=type_list, bbox=parsed_bbox)
    return {
        'type': 'FeatureCollection',
        'features': [
            {
                'type': 'Feature',
                'geometry': event['geometry'],
                'properties': {
                    'id': str(event['id']),
                    'source': event['source'],
                    'title': event['title'],
                    'description': event['description'],
                    'url': event['url'],
                    'event_type': event['event_type'],
                    'severity': event['severity'],
                    'confidence': event['confidence'],
                    'country': event['country'],
                    'region': event['region'],
                    'occurred_at': event['occurred_at'].isoformat(),
                },
            }
            for event in events
        ],
    }


@app.get('/compound/events/{event_id}')
async def get_event(event_id: str) -> dict[str, Any]:
    try:
        parsed_event_id = UUID(event_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail='invalid event_id') from exc
    event = await app.state.storage.get_event(str(parsed_event_id))
    if not event:
        raise HTTPException(status_code=404, detail='event not found')
    event['id'] = str(event['id'])
    event['occurred_at'] = event['occurred_at'].isoformat()
    event['ingested_at'] = event['ingested_at'].isoformat()
    return event


@app.get('/compound/alerts')
async def get_alerts(
    timestep: int = Query(default=0, ge=0),
    run_id: str = 'latest',
    bbox: str | None = None,
) -> dict[str, Any]:
    resolved_run_id = await _run_id_param(run_id)
    settings: Settings = app.state.settings
    alerts = await app.state.storage.detect_compound_alerts(
        run_id=resolved_run_id,
        timestep=timestep,
        lookback_hours=settings.event_lookback_hours,
        score_threshold=settings.alert_score_threshold,
        event_weights=settings.event_type_weights,
        bbox=_parse_bbox(bbox),
    )
    return {
        'type': 'FeatureCollection',
        'features': [
            {
                'type': 'Feature',
                'geometry': alert['geometry'],
                'properties': {
                    'alert_type': 'COMPOUND',
                    'event_id': alert['event_id'],
                    'title': alert['title'],
                    'url': alert['url'],
                    'event_type': alert['event_type'],
                    'hazard_type': alert['hazard_type'],
                    'hazard_prob': alert['hazard_prob'],
                    'score': alert['score'],
                    'country': alert['country'],
                    'occurred_at': alert['occurred_at'].isoformat(),
                    'forecast_ts': alert['forecast_ts'].isoformat(),
                    'details': alert['details'],
                },
            }
            for alert in alerts
        ],
    }


@app.post('/compound/ingest/run')
async def ingest_run() -> dict[str, Any]:
    return {'ok': True, 'message': 'Trigger ingestion by calling ingestor service endpoint /ingestor/run'}


@app.get('/compound/hazards/runs/latest')
async def latest_run() -> dict[str, Any]:
    run = await app.state.storage.latest_run()
    if not run:
        raise HTTPException(status_code=404, detail='no hazard runs')
    return run


def _line_option(origin: PointIn, destination: PointIn, bend: float) -> dict[str, Any]:
    mid_lon = (origin.lon + destination.lon) / 2.0
    mid_lat = (origin.lat + destination.lat) / 2.0
    dx = destination.lon - origin.lon
    dy = destination.lat - origin.lat
    normal_lon = -dy
    normal_lat = dx
    norm = max((normal_lon**2 + normal_lat**2) ** 0.5, 1e-6)
    offset_lon = (normal_lon / norm) * bend
    offset_lat = (normal_lat / norm) * bend
    return {
        'type': 'LineString',
        'coordinates': [
            [origin.lon, origin.lat],
            [mid_lon + offset_lon, mid_lat + offset_lat],
            [destination.lon, destination.lat],
        ],
    }


def _distance_km(origin: PointIn, destination: PointIn) -> float:
    from math import asin, cos, radians, sin, sqrt

    r = 6371.0
    p1, p2 = radians(origin.lat), radians(destination.lat)
    dphi = radians(destination.lat - origin.lat)
    dlambda = radians(destination.lon - origin.lon)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlambda / 2) ** 2
    return 2 * r * asin(sqrt(a))


@app.post('/routes/options')
async def route_options(body: RouteOptionsIn) -> dict[str, Any]:
    depart_time = _parse_route_datetime(body.depart_time, 'depart_time')
    arrive_by = _parse_route_datetime(body.arrive_by, 'arrive_by')
    if depart_time >= arrive_by:
        raise HTTPException(status_code=422, detail='depart_time must be before arrive_by')

    base_distance = _distance_km(body.origin, body.destination)
    options = [
        {'id': 'fastest', 'name': 'Fastest', 'geometry': _line_option(body.origin, body.destination, 0.0), 'distance_factor': 1.0, 'eta_factor': 1.0},
        {'id': 'balanced', 'name': 'Balanced', 'geometry': _line_option(body.origin, body.destination, 0.9), 'distance_factor': 1.08, 'eta_factor': 1.12},
        {'id': 'safest', 'name': 'Safest', 'geometry': _line_option(body.origin, body.destination, -1.1), 'distance_factor': 1.16, 'eta_factor': 1.25},
    ]
    scored = []
    run_id = await _run_id_param('latest')
    for item in options:
        score = await app.state.storage.score_route_corridor(
            item['geometry'],
            app.state.settings.event_lookback_hours,
            run_id,
            0,
            depart_time,
            arrive_by,
        )
        risk_bias = {'fastest': 1.1, 'balanced': 1.0, 'safest': 0.82}[item['id']]
        summary = dict(score['summary_risk'])
        summary['total'] = round(min(100.0, summary['total'] * risk_bias * (1.1 - body.risk_appetite * 0.2)), 3)
        scored.append(
            {
                'id': item['id'],
                'name': item['name'],
                'geometry': item['geometry'],
                'distance_km': round(base_distance * item['distance_factor'], 3),
                'eta_hours': round((base_distance / 55.0) * item['eta_factor'], 3),
                'summary_risk': summary,
            }
        )
    return {'routes': scored}


@app.post('/routes/score')
async def route_score(body: RouteScoreIn) -> dict[str, Any]:
    depart_time = _parse_route_datetime(body.depart_time, 'depart_time')
    arrive_by = _parse_route_datetime(body.arrive_by, 'arrive_by')
    if depart_time >= arrive_by:
        raise HTTPException(status_code=422, detail='depart_time must be before arrive_by')

    run_id = await _run_id_param(body.run_id)
    return await app.state.storage.score_route_corridor(
        geometry=body.geometry,
        lookback_hours=app.state.settings.event_lookback_hours,
        run_id=run_id,
        timestep=body.timestep,
        depart_time=depart_time,
        arrive_by=arrive_by,
    )
