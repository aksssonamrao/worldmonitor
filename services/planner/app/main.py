from __future__ import annotations

import math
import os
import uuid
from typing import Any, Literal

import httpx
from fastapi import FastAPI
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from pydantic import BaseModel, Field

app = FastAPI(title='Planner API')


class VehicleIn(BaseModel):
    id: str
    start_depot_id: str
    capacity: int = Field(ge=0)
    max_route_time_min: int = Field(ge=0)


class DepotIn(BaseModel):
    id: str
    lat: float
    lon: float


class JobIn(BaseModel):
    id: str
    lat: float
    lon: float
    demand: int = Field(ge=0)
    service_time_min: int = Field(ge=0)
    time_window: tuple[int, int] = (0, 24 * 60)


class ObjectiveWeightsIn(BaseModel):
    distance: float = 1.0
    time: float = 0.2
    risk: float = 3.0


class RiskModelIn(BaseModel):
    mode: Literal['polygon_intersection'] = 'polygon_intersection'
    sample_points_per_leg: int = Field(default=10, ge=1, le=200)


class PlanRequest(BaseModel):
    run_id: str = 'latest'
    timestep: int = Field(ge=0)
    alert_id: str
    vehicles: list[VehicleIn]
    depots: list[DepotIn]
    jobs: list[JobIn]
    objective_weights: ObjectiveWeightsIn = ObjectiveWeightsIn()
    risk_model: RiskModelIn = RiskModelIn()


@app.get('/health')
def health() -> dict[str, bool]:
    return {'ok': True}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _point_in_polygon(lon: float, lat: float, polygon: list[list[float]]) -> bool:
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        intersects = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


async def _fetch_hazards(run_id: str, timestep: int) -> list[dict[str, Any]]:
    compound_url = os.getenv('VITE_COMPOUND_API_URL', 'http://compound_api:8090').rstrip('/')
    url = f'{compound_url}/compound/hazards?run_id={run_id}&timestep={timestep}'
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    return data.get('features', [])


def _compute_leg_risk(
    a: tuple[float, float],
    b: tuple[float, float],
    hazards: list[dict[str, Any]],
    sample_points: int,
    risk_weight: float,
) -> float:
    risk = 0.0
    for i in range(1, sample_points + 1):
        t = i / (sample_points + 1)
        lon = a[0] + (b[0] - a[0]) * t
        lat = a[1] + (b[1] - a[1]) * t
        hit_prob = 0.0
        for feature in hazards:
            geom = feature.get('geometry', {})
            if geom.get('type') != 'Polygon':
                continue
            coords = geom.get('coordinates', [])
            if not coords:
                continue
            polygon = coords[0]
            if _point_in_polygon(lon, lat, polygon):
                prob = float(feature.get('properties', {}).get('hazard_prob', 0.7))
                hit_prob = max(hit_prob, prob)
        if hit_prob > 0:
            risk += risk_weight * hit_prob
    return risk


def _llm_summary(plan: dict[str, Any], request: PlanRequest) -> str | None:
    api_key = os.getenv('OPENAI_API_KEY', '').strip()
    model = os.getenv('OPENAI_MODEL', '').strip() or 'gpt-4o-mini'
    if not api_key:
        return None
    # Optional feature: never modifies plan fields, only produces text.
    try:
        import json

        payload = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': 'Summarize the deterministic logistics plan in 3-5 concise sentences.'},
                {
                    'role': 'user',
                    'content': json.dumps(
                        {
                            'objective': plan['objective'],
                            'routes': plan['routes'],
                            'weights': request.objective_weights.model_dump(),
                        }
                    ),
                },
            ],
            'temperature': 0,
        }
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                'https://api.openai.com/v1/chat/completions',
                headers={'Authorization': f'Bearer {api_key}'},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data['choices'][0]['message']['content']
    except Exception:
        return None


@app.post('/plan')
async def plan(request: PlanRequest) -> dict[str, Any]:
    depot_by_id = {d.id: d for d in sorted(request.depots, key=lambda x: x.id)}
    vehicles = sorted(request.vehicles, key=lambda x: x.id)
    jobs = sorted(request.jobs, key=lambda x: x.id)

    hazards = await _fetch_hazards(request.run_id, request.timestep)

    nodes: list[dict[str, Any]] = []
    for depot in sorted(request.depots, key=lambda x: x.id):
        nodes.append({'type': 'depot', 'id': depot.id, 'lat': depot.lat, 'lon': depot.lon, 'demand': 0, 'service': 0})
    for job in jobs:
        nodes.append(
            {
                'type': 'job',
                'id': job.id,
                'lat': job.lat,
                'lon': job.lon,
                'demand': job.demand,
                'service': job.service_time_min,
            }
        )

    depot_count = len(depot_by_id)
    node_count = len(nodes)

    starts: list[int] = []
    ends: list[int] = []
    for v in vehicles:
        starts.append(next(i for i, n in enumerate(nodes[:depot_count]) if n['id'] == v.start_depot_id))
        ends.append(starts[-1])

    manager = pywrapcp.RoutingIndexManager(node_count, len(vehicles), starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    speed_kmph = 40.0
    dist_matrix = [[0.0] * node_count for _ in range(node_count)]
    time_matrix = [[0.0] * node_count for _ in range(node_count)]
    risk_matrix = [[0.0] * node_count for _ in range(node_count)]
    cost_matrix = [[0] * node_count for _ in range(node_count)]

    for i in range(node_count):
        for j in range(node_count):
            if i == j:
                continue
            dkm = _haversine_km(nodes[i]['lat'], nodes[i]['lon'], nodes[j]['lat'], nodes[j]['lon'])
            tmin = (dkm / speed_kmph) * 60.0 + nodes[j]['service']
            rcost = _compute_leg_risk(
                (nodes[i]['lon'], nodes[i]['lat']),
                (nodes[j]['lon'], nodes[j]['lat']),
                hazards,
                request.risk_model.sample_points_per_leg,
                request.objective_weights.risk,
            )
            weighted = request.objective_weights.distance * dkm + request.objective_weights.time * tmin + rcost
            dist_matrix[i][j] = dkm
            time_matrix[i][j] = tmin
            risk_matrix[i][j] = rcost
            cost_matrix[i][j] = int(round(weighted * 1000))

    def transit_cb(from_index: int, to_index: int) -> int:
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        return cost_matrix[i][j]

    transit_idx = routing.RegisterTransitCallback(transit_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_idx)

    def demand_cb(from_index: int) -> int:
        i = manager.IndexToNode(from_index)
        return int(nodes[i]['demand'])

    demand_idx = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(demand_idx, 0, [v.capacity for v in vehicles], True, 'Capacity')

    def time_cb(from_index: int, to_index: int) -> int:
        i = manager.IndexToNode(from_index)
        j = manager.IndexToNode(to_index)
        return int(round(time_matrix[i][j]))

    time_idx = routing.RegisterTransitCallback(time_cb)
    routing.AddDimension(time_idx, 0, max(v.max_route_time_min for v in vehicles), True, 'Time')
    time_dim = routing.GetDimensionOrDie('Time')
    for v_idx, v in enumerate(vehicles):
        end_index = routing.End(v_idx)
        time_dim.CumulVar(end_index).SetRange(0, v.max_route_time_min)

    for idx in range(depot_count, node_count):
        routing.AddDisjunction([manager.NodeToIndex(idx)], 10_000_000)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GREEDY_DESCENT
    params.time_limit.seconds = 3
    params.log_search = False

    solution = routing.SolveWithParameters(params)
    if solution is None:
        return {
            'plan_id': str(uuid.uuid4()),
            'objective': {'total_cost': 0.0, 'distance_km': 0.0, 'time_min': 0.0, 'risk_cost': 0.0},
            'routes': [],
            'constraints_ok': False,
            'explain': {
                'high_level': 'No feasible solution found for provided constraints.',
                'tradeoffs': ['Tight capacity or route time likely caused infeasibility.'],
                'assumptions': ['Straight-line distance approximation', 'Deterministic OR-Tools configuration'],
            },
            'llm_summary': None,
        }

    routes = []
    total_distance = 0.0
    total_time = 0.0
    total_risk = 0.0

    for v_idx, vehicle in enumerate(vehicles):
        index = routing.Start(v_idx)
        route_stops = []
        route_distance = 0.0
        route_time = 0.0
        route_risk = 0.0
        eta = 0.0

        while not routing.IsEnd(index):
            node_idx = manager.IndexToNode(index)
            node = nodes[node_idx]
            stop = {'type': node['type'], 'id': node['id'], 'lat': node['lat'], 'lon': node['lon']}
            if node['type'] == 'job':
                stop['eta_min'] = round(eta, 3)
            route_stops.append(stop)

            next_index = solution.Value(routing.NextVar(index))
            next_node = manager.IndexToNode(next_index)
            route_distance += dist_matrix[node_idx][next_node]
            route_time += time_matrix[node_idx][next_node]
            route_risk += risk_matrix[node_idx][next_node]
            eta += time_matrix[node_idx][next_node]
            index = next_index

        end_node = manager.IndexToNode(index)
        route_stops.append({'type': 'depot', 'id': nodes[end_node]['id'], 'lat': nodes[end_node]['lat'], 'lon': nodes[end_node]['lon']})

        if len(route_stops) > 2:
            routes.append(
                {
                    'vehicle_id': vehicle.id,
                    'stops': route_stops,
                    'distance_km': round(route_distance, 3),
                    'time_min': round(route_time, 3),
                    'risk_cost': round(route_risk, 3),
                }
            )
            total_distance += route_distance
            total_time += route_time
            total_risk += route_risk

    total_cost = request.objective_weights.distance * total_distance + request.objective_weights.time * total_time + total_risk
    plan_result: dict[str, Any] = {
        'plan_id': str(uuid.uuid4()),
        'objective': {
            'total_cost': round(total_cost, 6),
            'distance_km': round(total_distance, 3),
            'time_min': round(total_time, 3),
            'risk_cost': round(total_risk, 3),
        },
        'routes': routes,
        'constraints_ok': True,
        'explain': {
            'high_level': 'Deterministic OR-Tools solution balancing travel distance/time and hazard exposure.',
            'tradeoffs': [
                'Higher risk weight increases preference for legs with fewer hazard intersections.',
                'Capacity and max route time constraints may force additional vehicles.',
            ],
            'assumptions': ['Straight-line haversine distance', 'Fixed average speed of 40 km/h', 'Polygon-sampling risk model'],
        },
        'llm_summary': None,
    }
    plan_result['llm_summary'] = _llm_summary(plan_result, request)
    return plan_result
