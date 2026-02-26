from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.config import load_settings
from app.ingestion import run_ingestion_cycle
from app.storage import IngestStorage

logger = logging.getLogger(__name__)
ingestion_lock = asyncio.Lock()


async def _run_with_lock(settings, storage):
    async with ingestion_lock:
        return await run_ingestion_cycle(settings, storage)


async def _run_monitoring_cycle(settings, storage) -> None:
    try:
        await _run_with_lock(settings, storage)
    except Exception:
        logger.exception('Ingestion refresh failed in monitoring cycle')

    run_id = datetime.now(timezone.utc).strftime('run-%Y%m%d%H%M%S')
    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            await client.post(f'{settings.compound_api_url}/compound/hazards/generate', json={'run_id': run_id})
        except Exception:
            logger.exception('Hazard generation failed in monitoring cycle')
        try:
            await client.post(f'{settings.compound_api_url}/aois/snapshots/refresh', json={'run_id': run_id})
        except Exception:
            logger.exception('AOI snapshot refresh failed in monitoring cycle')


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    storage = IngestStorage(settings.database_url)
    await storage.connect()
    scheduler = AsyncIOScheduler()

    async def scheduled_job():
        await _run_with_lock(settings, storage)

    async def monitoring_job():
        await _run_monitoring_cycle(settings, storage)

    scheduler.add_job(scheduled_job, 'interval', minutes=settings.ingest_interval_minutes)
    scheduler.add_job(monitoring_job, 'interval', minutes=settings.monitoring_interval_minutes)
    scheduler.start()

    app.state.settings = settings
    app.state.storage = storage
    app.state.scheduler = scheduler
    yield
    app.state.scheduler.shutdown(wait=True)
    await app.state.storage.close()


app = FastAPI(title='Events Ingestor', lifespan=lifespan)


@app.get('/ingestor/health')
async def health() -> dict[str, Any]:
    return {'ok': True, 'ingestion_state': await app.state.storage.list_ingestion_state()}


@app.post('/ingestor/run')
async def run_once() -> dict[str, Any]:
    counts = await _run_with_lock(app.state.settings, app.state.storage)
    return {'ok': True, 'ingested': counts}


@app.post('/ingestor/monitoring/run')
async def run_monitoring_once() -> dict[str, Any]:
    await _run_monitoring_cycle(app.state.settings, app.state.storage)
    return {'ok': True}
