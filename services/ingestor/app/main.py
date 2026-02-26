from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.config import load_settings
from app.ingestion import run_ingestion_cycle
from app.storage import IngestStorage

ingestion_lock = asyncio.Lock()


async def _run_with_lock(settings, storage):
    async with ingestion_lock:
        return await run_ingestion_cycle(settings, storage)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    storage = IngestStorage(settings.database_url)
    await storage.connect()
    scheduler = AsyncIOScheduler()

    async def scheduled_job():
        await _run_with_lock(settings, storage)

    scheduler.add_job(scheduled_job, 'interval', minutes=settings.ingest_interval_minutes)
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
