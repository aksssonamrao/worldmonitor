from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.agents.orchestrator import run_workflow, subscribe
from app.agents.store import get_run
from app.main_state import get_db_pool

router = APIRouter(tags=['agents'])


@router.post('/api/agents/run')
async def start_agents_run(request: dict) -> dict[str, str]:
    run_id = await run_workflow(request)
    return {'run_id': run_id}


@router.get('/api/agents/runs/{run_id}')
async def get_agents_run(run_id: str) -> dict:
    pool = get_db_pool()
    item = await get_run(pool, run_id)
    if not item:
        raise HTTPException(status_code=404, detail='run not found')
    return item


@router.websocket('/ws/agents/runs/{run_id}')
async def ws_agents_run(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    try:
        async for event in subscribe(run_id):
            await websocket.send_json(event)
    except WebSocketDisconnect:
        return
