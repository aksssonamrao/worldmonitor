from __future__ import annotations

import os
from typing import Any

import httpx

VALHALLA_URL = os.getenv('VALHALLA_URL', 'http://valhalla:8002').rstrip('/')


def _decode_shape(shape: str) -> list[list[float]]:
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


def _trip_to_internal(trip: dict[str, Any], route_id: str) -> dict[str, Any]:
    summary = trip.get('summary', {})
    legs = trip.get('legs') or []
    coordinates: list[list[float]] = []
    for leg in legs:
        shape = leg.get('shape')
        if not shape:
            continue
        segment = _decode_shape(shape)
        if not segment:
            continue
        if coordinates and coordinates[-1] == segment[0]:
            coordinates.extend(segment[1:])
        else:
            coordinates.extend(segment)
    return {
        'id': route_id,
        'geometry': {'type': 'LineString', 'coordinates': coordinates},
        'distance_km': float(summary.get('length', 0.0)),
        'duration_s': float(summary.get('time', 0.0)),
    }


async def route(locations: list[dict[str, float]], costing: str = 'auto', **opts: Any) -> dict[str, Any]:
    payload = {'locations': locations, 'costing': costing, **opts}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f'{VALHALLA_URL}/route', json=payload)
        resp.raise_for_status()
        data = resp.json()
    trips = [data['trip']] if 'trip' in data else (data.get('trips') or [])
    routes = [_trip_to_internal(trip, f'route-{idx + 1}') for idx, trip in enumerate(trips)]
    return {'routes': routes}


async def isochrone(payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f'{VALHALLA_URL}/isochrone', json=payload)
        resp.raise_for_status()
        data = resp.json()
    return {'feature_collection': data}


async def healthcheck() -> bool:
    sample = {
        'locations': [
            {'lat': 37.7749, 'lon': -122.4194},
            {'lat': 34.0522, 'lon': -118.2437},
        ],
        'costing': 'auto',
    }
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.post(f'{VALHALLA_URL}/route', json=sample)
            resp.raise_for_status()
        return True
    except Exception:
        return False
