from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from os import getenv
from typing import Any

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
    # Teardown: release all resources on shutdown.
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


async def _run_id_param(run_id: str | None) -> str:
    if run_id and run_id != 'latest':
        return run_id
    latest = await app.state.storage.latest_run()
    if not latest:
        raise HTTPException(status_code=404, detail='no hazard runs')
    return latest['run_id']


@app.get('/compound/health')
def compound_health() -> dict[str, Any]:
    return {
        'ok': True,
        'weather_api_configured': bool(getattr(app.state, 'weather_api_configured', False)),
        'last_hazard_run': getattr(app.state, 'last_hazard_run', None),
        'last_hazard_error': getattr(app.state, 'last_hazard_error', None),
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
        # Validate that bbox is a list/tuple of 4 numeric values within valid coordinate ranges:
        # [min_lon, min_lat, max_lon, max_lat]
        if not isinstance(raw_bbox, (list, tuple)) or len(raw_bbox) != 4:
            raise HTTPException(
                status_code=400,
                detail='bbox must be a list of 4 coordinates [min_lon, min_lat, max_lon, max_lat]',
            )
        try:
            bbox = [float(v) for v in raw_bbox]
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail='bbox values must be numeric',
            )
        min_lon, min_lat, max_lon, max_lat = bbox
        # Longitude must be between -180 and 180; latitude between -90 and 90
        if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0 and -90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
            raise HTTPException(
                status_code=400,
                detail='bbox coordinates out of valid range: lon in [-180, 180], lat in [-90, 90]',
            )
        # Ensure bbox defines a non-empty rectangle
        if not (min_lon < max_lon and min_lat < max_lat):
            raise HTTPException(
                status_code=400,
                detail='bbox must have min_lon < max_lon and min_lat < max_lat',
            )
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


@app.get('/compound/alerts')
async def get_alerts(timestep: int = Query(default=0, ge=0), run_id: str = 'latest') -> dict[str, Any]:
    resolved_run_id = await _run_id_param(run_id)
    hazards = await app.state.storage.list_hazards(resolved_run_id, timestep)
    alerts = [
        {
            'type': 'Feature',
            'geometry': hazard['geometry'],
            'properties': {
                'hazard_type': hazard['type'],
                'score': hazard['hazard_prob'],
                'provider': hazard['provider'],
                'forecast_ts': hazard['forecast_ts'].isoformat(),
            },
        }
        for hazard in hazards
        if hazard['hazard_prob'] > 0.5
    ]
    return {'type': 'FeatureCollection', 'features': alerts}


@app.get('/compound/hazards/runs/latest')
async def latest_run() -> dict[str, Any]:
    run = await app.state.storage.latest_run()
    if not run:
        raise HTTPException(status_code=404, detail='no hazard runs')
    return run
