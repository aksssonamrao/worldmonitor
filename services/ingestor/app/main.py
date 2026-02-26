from __future__ import annotations

from typing import Any
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.config import Settings, load_settings
from app.ingestion import run_ingestion_cycle
from app.storage import IngestStorage


app = FastAPI(title='Events Ingestor')


@app.on_event('startup')
async def startup() -> None:
    settings = load_settings()
    storage = IngestStorage(settings.database_url)
    await storage.connect()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_ingestion_cycle, 'interval', minutes=settings.ingest_interval_minutes, kwargs={'settings': settings, 'storage': storage})
    scheduler.start()
    app.state.settings = settings
    app.state.storage = storage
    app.state.scheduler = scheduler


@app.on_event('shutdown')
async def shutdown() -> None:
    app.state.scheduler.shutdown(wait=False)
    await app.state.storage.close()


@app.get('/ingestor/health')
async def health() -> dict[str, Any]:
    return {'ok': True, 'ingestion_state': await app.state.storage.list_ingestion_state()}


@app.post('/ingestor/run')
async def run_once() -> dict[str, Any]:
    counts = await run_ingestion_cycle(app.state.settings, app.state.storage)
    return {'ok': True, 'ingested': counts}
