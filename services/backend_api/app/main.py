from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.api.agent import router as agent_router
from app.api.planner import router as planner_router
from app.api.internal_jobs import router as internal_jobs_router
from app.domains.compound.main import app as compound_app
from app.main_state import set_db_pool, get_db_pool
from app.providers.valhalla import healthcheck as valhalla_healthcheck

app = FastAPI(title='backend_api')

UPSTREAM_TIMEOUT_SECONDS = float(os.getenv('UPSTREAM_TIMEOUT_SECONDS', '20'))


@app.on_event('startup')
async def startup() -> None:
    app.state.http_client = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT_SECONDS)
    os.environ.setdefault('ALLOW_MISCONFIGURED_STARTUP', '1')
    app.state.compound_lifespan = compound_app.router.lifespan_context(compound_app)
    await app.state.compound_lifespan.__aenter__()
    app.state.compound_client = httpx.AsyncClient(
        timeout=UPSTREAM_TIMEOUT_SECONDS,
        transport=httpx.ASGITransport(app=compound_app),
        base_url='http://compound.internal',
    )
    storage = getattr(compound_app.state, 'storage', None)
    if storage is not None and getattr(storage, '_pool', None) is not None:
        set_db_pool(storage._pool)



@app.on_event('shutdown')
async def shutdown() -> None:
    await app.state.compound_client.aclose()
    await app.state.compound_lifespan.__aexit__(None, None, None)
    await app.state.http_client.aclose()


async def _proxy_compound(request: Request, target_path: str) -> Response:
    client: httpx.AsyncClient = request.app.state.compound_client
    body = await request.body()
    try:
        upstream_response = await client.request(
            method=request.method,
            url=target_path,
            params=request.query_params,
            content=body,
            headers={k: v for k, v in request.headers.items() if k.lower() not in {'host', 'content-length'}},
        )
    except httpx.HTTPError as exc:
        return JSONResponse(status_code=502, content={'detail': f'Upstream request failed: {exc}'})

    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        media_type=upstream_response.headers.get('content-type'),
    )


@app.get('/health')
async def health() -> dict[str, object]:
    health_data: dict[str, object] = {'status': 'ok'}
    client: httpx.AsyncClient = app.state.compound_client
    try:
        compound_health = (await client.get('/compound/health')).json()
        system_status = (await client.get('/system/status')).json()
        health_data['compound'] = {
            'last_hazard_run': compound_health.get('last_hazard_run'),
            'events_freshness': system_status.get('events_freshness'),
            'hazards_freshness': system_status.get('hazards_freshness'),
            'alerts_freshness': system_status.get('alerts_freshness'),
        }
    except Exception as exc:
        health_data['compound'] = {'error': str(exc)}

    try:
        pool = get_db_pool()
        async with pool.acquire() as conn:
            await conn.fetchval('SELECT 1')
            gdelt = await conn.fetchrow("SELECT last_success_at FROM ingestion_runs WHERE source='gdelt'")
            relief = await conn.fetchrow("SELECT last_success_at FROM ingestion_runs WHERE source='reliefweb'")
            counts = await conn.fetch("SELECT status, count(*)::int AS count FROM job_queue GROUP BY status")
        health_data['db'] = {'ok': True}
        health_data['ingestion'] = {
            'last_ingest_gdelt': gdelt['last_success_at'].isoformat() if gdelt and gdelt['last_success_at'] else None,
            'last_ingest_reliefweb': relief['last_success_at'].isoformat() if relief and relief['last_success_at'] else None,
        }
        by_status = {row['status']: row['count'] for row in counts}
        health_data['job_queue'] = {
            'queued': by_status.get('queued', 0),
            'running': by_status.get('running', 0),
        }
    except Exception as exc:
        health_data['db'] = {'ok': False, 'error': str(exc)}
        health_data['ingestion'] = {'error': str(exc)}


    try:
        health_data['valhalla'] = {'ok': await valhalla_healthcheck()}
    except Exception as exc:
        health_data['valhalla'] = {'ok': False, 'error': str(exc)}

    return health_data


@app.post('/api/routes/options')
async def routes_options(request: Request) -> Response:
    return await _proxy_compound(request, '/routes/options')


@app.post('/api/routes/score')
async def routes_score(request: Request) -> Response:
    return await _proxy_compound(request, '/routes/score')


@app.api_route('/compound/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
async def compound_passthrough(path: str, request: Request) -> Response:
    return await _proxy_compound(request, f'/compound/{path}')


@app.api_route('/system/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
async def system_passthrough(path: str, request: Request) -> Response:
    return await _proxy_compound(request, f'/system/{path}')


@app.api_route('/aois', methods=['GET', 'POST'])
async def aois_root(request: Request) -> Response:
    return await _proxy_compound(request, '/aois')


@app.api_route('/aois/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
async def aois_passthrough(path: str, request: Request) -> Response:
    return await _proxy_compound(request, f'/aois/{path}')


app.include_router(planner_router)
app.include_router(agent_router)
app.include_router(internal_jobs_router)
