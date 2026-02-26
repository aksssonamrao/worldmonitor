from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title='Routing API')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

VALHALLA_URL = os.getenv('VALHALLA_URL', 'http://valhalla:8002').rstrip('/')


class RoutingRequest(BaseModel):
    payload: dict[str, Any]


def _decode_shape(shape: str) -> list[list[float]]:
    # Polyline6 decoder
    coords: list[list[float]] = []
    index = lat = lon = 0
    factor = 1_000_000.0
    while index < len(shape):
        result = shift = 0
        while True:
            b = ord(shape[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if result & 1 else result >> 1
        lat += dlat

        result = shift = 0
        while True:
            b = ord(shape[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlon = ~(result >> 1) if result & 1 else result >> 1
        lon += dlon
        coords.append([lon / factor, lat / factor])
    return coords


def _route_to_internal(trip: dict[str, Any], route_id: str) -> dict[str, Any]:
    summary = trip.get('summary', {})
    leg = (trip.get('legs') or [{}])[0]
    shape = leg.get('shape')
    coordinates = _decode_shape(shape) if shape else []
    return {
        'id': route_id,
        'geometry': {'type': 'LineString', 'coordinates': coordinates},
        'distance_km': float(summary.get('length', 0.0)),
        'duration_s': float(summary.get('time', 0.0)),
    }


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f'{VALHALLA_URL}{path}', json=payload)
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f'Valhalla error {resp.status_code}: {resp.text}')
        return resp.json()


@app.get('/health')
async def health() -> dict[str, bool]:
    return {'ok': True}


@app.post('/routing/route')
async def route(body: RoutingRequest) -> dict[str, Any]:
    data = await _post('/route', body.payload)
    trips = data.get('trip') and [data['trip']] or data.get('trips', [])
    routes = [_route_to_internal(trip, f'route-{idx + 1}') for idx, trip in enumerate(trips)]
    return {'routes': routes}


@app.post('/routing/isochrone')
async def isochrone(body: RoutingRequest) -> dict[str, Any]:
    data = await _post('/isochrone', body.payload)
    return {'feature_collection': data}


@app.post('/routing/matrix')
async def matrix(body: RoutingRequest) -> dict[str, Any]:
    data = await _post('/sources_to_targets', body.payload)
    return {'matrix': data}


@app.post('/routing/map_match')
async def map_match(body: RoutingRequest) -> dict[str, Any]:
    data = await _post('/trace_route', body.payload)
    trip = data.get('trip', {})
    return {'match': _route_to_internal(trip, 'map-match')}


@app.post('/routing/optimized_route')
async def optimized_route(body: RoutingRequest) -> dict[str, Any]:
    data = await _post('/optimized_route', body.payload)
    trip = data.get('trip', {})
    return {'route': _route_to_internal(trip, 'optimized')}
