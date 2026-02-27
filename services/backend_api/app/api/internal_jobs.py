from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.core import queue
from app.main_state import get_db_pool

router = APIRouter(prefix='/internal/jobs', tags=['internal-jobs'])


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    expected = os.getenv('ADMIN_API_KEY', '').strip()
    if not expected:
        raise HTTPException(status_code=404, detail='Not found')
    if x_admin_key != expected:
        raise HTTPException(status_code=403, detail='Forbidden')


class EnqueueBody(BaseModel):
    job_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    run_after: datetime | None = None
    max_attempts: int = Field(default=5, ge=1, le=100)


@router.post('/enqueue', dependencies=[Depends(require_admin)])
async def enqueue_job(body: EnqueueBody) -> dict[str, str]:
    pool = get_db_pool()
    job_id = await queue.enqueue(pool, body.job_type, body.payload, body.run_after, body.max_attempts)
    return {'job_id': str(job_id)}


@router.get('/stats', dependencies=[Depends(require_admin)])
async def queue_stats() -> dict[str, Any]:
    pool = get_db_pool()
    return await queue.stats(pool)


@router.post('/reap-stale', dependencies=[Depends(require_admin)])
async def reap_stale() -> dict[str, int]:
    pool = get_db_pool()
    released = await queue.release_stale_locks(pool)
    return {'released': released}
