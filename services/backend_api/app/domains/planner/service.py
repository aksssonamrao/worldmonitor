from __future__ import annotations

import json
import logging
import math
import os
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
from fastapi import HTTPException
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from pydantic import BaseModel, Field
from app.domains.planner.logging_utils import configure_logging, next_request_id, request_id_var
from app.providers.valhalla import isochrone as valhalla_isochrone, route as valhalla_route

configure_logging('backend_api_planner')
logger = logging.getLogger(__name__)
COMPOUND_API_URL = os.getenv('COMPOUND_API_URL', 'http://compound_api:8090').rstrip('/')

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
    selected_route_geometry: dict[str, Any] | None = None


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
    compound_url = os.getenv('COMPOUND_API_URL', 'http://localhost:8080').rstrip('/')
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

    # Do not add disjunctions with penalties here: making all jobs optional
    # would allow the solver to drop visits while the API reports that all
    # constraints were satisfied.
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
            'selected_route_geometry': request.selected_route_geometry,
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
        'selected_route_geometry': request.selected_route_geometry,
    }
    plan_result['llm_summary'] = _llm_summary(plan_result, request)
    return plan_result


class ShipmentIn(BaseModel):
    origin: dict[str, float]
    destination: dict[str, float]
    depart_time: str
    arrive_by: str
    mode: str = 'auto'
    risk_appetite: float = Field(default=0.5, ge=0, le=1)


class SelectedRouteIn(BaseModel):
    id: str
    geometry: dict[str, Any]


class MitigationConstraintsIn(BaseModel):
    avoid_event_types: list[str] = Field(default_factory=list)
    max_extra_eta_hours: float | None = None
    max_risk_score: float | None = None


class MitigationIn(BaseModel):
    shipment: ShipmentIn
    selected_route: SelectedRouteIn
    constraints: MitigationConstraintsIn | None = None


_fallback_path = Path(__file__).with_name('fallback_hubs.json')
_default_fallback_hubs = [
    {'id': 'LAX', 'label': 'Los Angeles Logistics Node', 'lat': 34.0522, 'lon': -118.2437},
    {'id': 'ORD', 'label': 'Chicago Logistics Node', 'lat': 41.8781, 'lon': -87.6298},
    {'id': 'DFW', 'label': 'Dallas/Fort Worth Logistics Node', 'lat': 32.8998, 'lon': -97.0403},
]
if _fallback_path.exists():
    try:
        FALLBACK_HUBS = json.loads(_fallback_path.read_text())
    except json.JSONDecodeError:
        logger.exception('failed to parse fallback hubs json: %s', _fallback_path)
        FALLBACK_HUBS = _default_fallback_hubs
    except Exception:
        logger.exception('failed to load fallback hubs: %s', _fallback_path)
        FALLBACK_HUBS = _default_fallback_hubs
else:
    FALLBACK_HUBS = _default_fallback_hubs


class RoutingPlugin:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def route(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await valhalla_route(**payload)

    async def isochrone(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await valhalla_isochrone(payload)

    async def corridor_score(self, geometry: dict[str, Any], depart_time: str, arrive_by: str) -> dict[str, Any]:
        resp = await self.client.post(
            f'{COMPOUND_API_URL}/routes/score',
            json={'geometry': geometry, 'depart_time': depart_time, 'arrive_by': arrive_by, 'run_id': 'latest', 'timestep': 0},
        )
        resp.raise_for_status()
        return resp.json()


def _to_utc_iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _parse_dt(value: str) -> datetime:
    """Parse an ISO-8601 datetime string that must include timezone information."""
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(status_code=422, detail='invalid datetime format')
    if parsed.tzinfo is None:
        raise HTTPException(status_code=422, detail='datetime fields must include timezone offset or Z suffix')
    return parsed.astimezone(timezone.utc)


def _normalize_evidence(score: dict[str, Any], avoid_types: set[str] | None = None) -> tuple[dict[str, Any], list[str], str | None]:
    avoid_types = avoid_types or set()
    events = score.get('top_evidence', {}).get('events', [])
    alerts = score.get('top_evidence', {}).get('alerts', [])
    hazards = score.get('top_evidence', {}).get('hazards', [])
    incidents = []
    citations: list[str] = []
    dominant_counts: dict[str, int] = {}
    for item in events:
        event_type = str(item.get('event_type') or 'unknown').upper()
        dominant_counts[event_type] = dominant_counts.get(event_type, 0) + 1
        sources = []
        if item.get('url'):
            sources.append({'url': item['url'], 'source': 'compound_events'})
            citations.append(item['url'])
        incident = {
            'id': str(item.get('id', '')),
            'title': item.get('title', 'untitled incident'),
            'severity': float(item.get('severity', 0.0)),
            'confidence': float(item.get('confidence', 0.0)),
            'start_at': item.get('occurred_at'),
            'source_count': len(sources),
            'sources': sources,
            'event_type': event_type,
        }
        if event_type not in avoid_types:
            incidents.append(incident)
    dominant_type = None
    if dominant_counts:
        dominant_type = max(dominant_counts.items(), key=lambda pair: pair[1])[0]

    normalized_hazards = [
        {'type': h.get('type', 'hazard'), 'severity': float(h.get('hazard_prob', 0.0)), 'polygon_id': str(h.get('id', ''))}
        for h in hazards
    ]
    normalized_alerts = [
        {'id': str(a.get('id', '')), 'score': float(a.get('score', 0.0)), 'message': a.get('title', 'alert')}
        for a in alerts
    ]
    for alert in alerts:
        if alert.get('url'):
            citations.append(alert['url'])
    return ({'incidents': incidents[:10], 'hazards': normalized_hazards[:10], 'alerts': normalized_alerts[:10]}, sorted(set(citations)), dominant_type)


def _risk_breakdown(score: dict[str, Any]) -> dict[str, float]:
    summary = score.get('summary_risk', {})
    return {
        'weather': float(summary.get('weather', 0.0)),
        'news': float(summary.get('news', 0.0)),
        'compound': float(summary.get('compound', 0.0)),
    }


def _objective(risk_total: float, delta_eta_hours: float, risk_appetite: float) -> float:
    lam = max(0.1, (1.0 - risk_appetite) * 5.0)
    return risk_total + lam * max(0.0, delta_eta_hours)


def _within_constraints(option: dict[str, Any], constraints: MitigationConstraintsIn | None) -> bool:
    if not constraints:
        return True
    if constraints.max_extra_eta_hours is not None and option['delta_eta_hours'] > constraints.max_extra_eta_hours:
        return False
    if constraints.max_risk_score is not None and option['risk_total'] > constraints.max_risk_score:
        return False
    return True


def _simulate_win_rates(options: list[dict[str, Any]], risk_appetite: float, runs: int, seed: int | None = None) -> list[dict[str, Any]]:
    import random

    rng = random.Random(seed) if seed is not None else random.Random()
    wins = {o['option_id']: 0 for o in options}
    for _ in range(runs):
        scores: list[tuple[str, float]] = []
        for option in options:
            breakdown = option['risk_breakdown']
            hazard_mul = rng.uniform(0.85, 1.15)
            sev_noise = rng.uniform(0.9, 1.1)
            conf_noise = rng.uniform(0.9, 1.1)
            perturbed_risk = max(
                0.0,
                (breakdown['weather'] * hazard_mul)
                + (breakdown['news'] * sev_noise * conf_noise)
                + (breakdown['compound'] * sev_noise),
            )
            objective = _objective(perturbed_risk, option['delta_eta_hours'], risk_appetite)
            scores.append((option['option_id'], objective))
        winner = min(scores, key=lambda item: item[1])[0]
        wins[winner] += 1
    return [
        {'option_id': key, 'win_pct': round((count / runs) * 100.0, 2)}
        for key, count in sorted(wins.items(), key=lambda item: item[1], reverse=True)
    ]


async def agent_mitigation(request: MitigationIn) -> dict[str, Any]:
    shipment = request.shipment
    constraints = request.constraints
    request_id = str(uuid.uuid4())
    degrade_notes: list[str] = []

    depart = _parse_dt(shipment.depart_time)
    arrive = _parse_dt(shipment.arrive_by)
    if depart >= arrive:
        raise HTTPException(status_code=422, detail='shipment.depart_time must be before shipment.arrive_by')

    async with httpx.AsyncClient(timeout=20.0) as client:
        plugin = RoutingPlugin(client)

        baseline_score: dict[str, Any] = {}
        try:
            baseline_score = await plugin.corridor_score(request.selected_route.geometry, _to_utc_iso(depart), _to_utc_iso(arrive))
        except Exception as exc:
            degrade_notes.append(f'compound_api degraded: {exc.__class__.__name__}')
            baseline_score = {'summary_risk': {'total': 0.0, 'weather': 0.0, 'news': 0.0, 'compound': 0.0}, 'top_evidence': {'events': [], 'alerts': [], 'hazards': []}}

        avoid_types = {value.upper() for value in (constraints.avoid_event_types if constraints else [])}
        base_evidence, base_citations, dominant_type = _normalize_evidence(baseline_score)
        baseline_eta = (arrive - depart).total_seconds() / 3600.0
        baseline_risk = float(baseline_score.get('summary_risk', {}).get('total', 0.0))
        baseline = {
            'eta_hours': round(baseline_eta, 3),
            'risk_total': round(baseline_risk, 3),
            'risk_breakdown': _risk_breakdown(baseline_score),
            'top_evidence': base_evidence,
        }

        candidates: list[dict[str, Any]] = []

        for delta in (6, 12):
            shifted_depart = depart + timedelta(hours=delta)
            shifted_arrive = arrive + timedelta(hours=delta)
            try:
                score = await plugin.corridor_score(request.selected_route.geometry, _to_utc_iso(shifted_depart), _to_utc_iso(shifted_arrive))
            except Exception as exc:
                degrade_notes.append(f'compound_api degraded on depart_later_{delta}h: {exc.__class__.__name__}')
                score = baseline_score
            evidence, citations, _ = _normalize_evidence(score)
            risk_total = float(score.get('summary_risk', {}).get('total', baseline_risk))
            option = {
                'option_id': f'depart_later_{delta}h',
                'label': f'Depart later (+{delta}h)',
                'geometry': request.selected_route.geometry,
                'eta_hours': round(baseline_eta + delta, 3),
                'delta_eta_hours': float(delta),
                'risk_total': round(risk_total, 3),
                'delta_risk': round(risk_total - baseline_risk, 3),
                'risk_breakdown': _risk_breakdown(score),
                'evidence': evidence,
                'citations': citations,
            }
            if _within_constraints(option, constraints):
                candidates.append(option)

        try:
            routed = await plugin.route({'locations': [shipment.origin, shipment.destination], 'costing': shipment.mode, 'alternates': 3})
            alternatives = routed.get('routes', [])[1:3]
        except Exception as exc:
            degrade_notes.append(f'valhalla degraded on alternates: {exc.__class__.__name__}')
            alternatives = []

        for idx, alt in enumerate(alternatives, start=1):
            geometry = alt.get('geometry') or request.selected_route.geometry
            eta_hours = float(alt.get('duration_s', baseline_eta * 3600.0)) / 3600.0
            try:
                score = await plugin.corridor_score(geometry, _to_utc_iso(depart), _to_utc_iso(arrive))
            except Exception as exc:
                degrade_notes.append(f'compound_api degraded on alt_route_{idx}: {exc.__class__.__name__}')
                score = baseline_score
            evidence, citations, _ = _normalize_evidence(score)
            risk_total = float(score.get('summary_risk', {}).get('total', baseline_risk))
            option = {
                'option_id': f'alt_route_{idx}',
                'label': f'Alternate route {idx}',
                'geometry': geometry,
                'eta_hours': round(eta_hours, 3),
                'delta_eta_hours': round(eta_hours - baseline_eta, 3),
                'risk_total': round(risk_total, 3),
                'delta_risk': round(risk_total - baseline_risk, 3),
                'risk_breakdown': _risk_breakdown(score),
                'evidence': evidence,
                'citations': citations,
            }
            if _within_constraints(option, constraints):
                candidates.append(option)

        midpoint = shipment.origin
        isochrone_result: dict[str, Any] | None = None
        try:
            coords = request.selected_route.geometry.get('coordinates', [])
            if len(coords) > 2:
                mid = coords[len(coords) // 2]
                midpoint = {'lat': float(mid[1]), 'lon': float(mid[0])}
            isochrone_result = await plugin.isochrone({'locations': [midpoint], 'contours': [{'time': 240}], 'costing': shipment.mode, 'polygons': True})
        except Exception as exc:
            degrade_notes.append(f'valhalla degraded on isochrone: {exc.__class__.__name__}')
        if isochrone_result is not None:
            feature_count = len(isochrone_result.get('feature_collection', {}).get('features', []))
            degrade_notes.append(f'isochrone_features={feature_count}')

        hub_rank: list[tuple[float, dict[str, Any]]] = []
        for hub in FALLBACK_HUBS:
            try:
                part1 = await plugin.route({'locations': [shipment.origin, {'lat': hub['lat'], 'lon': hub['lon']}], 'costing': shipment.mode})
                part2 = await plugin.route({'locations': [{'lat': hub['lat'], 'lon': hub['lon']}, shipment.destination], 'costing': shipment.mode})
                first = (part1.get('routes') or [{}])[0]
                second = (part2.get('routes') or [{}])[0]
                combined = {'type': 'LineString', 'coordinates': (first.get('geometry', {}).get('coordinates', []) + second.get('geometry', {}).get('coordinates', []))}
                eta_hours = float(first.get('duration_s', 0) + second.get('duration_s', 0)) / 3600.0
                score = await plugin.corridor_score(combined, _to_utc_iso(depart), _to_utc_iso(arrive))
                risk_total = float(score.get('summary_risk', {}).get('total', baseline_risk))
                evidence, citations, _ = _normalize_evidence(score)
                option = {
                    'option_id': f"fallback_hub_{hub['id']}",
                    'label': f"Fallback hub: {hub['label']}",
                    'geometry': combined,
                    'eta_hours': round(eta_hours, 3),
                    'delta_eta_hours': round(eta_hours - baseline_eta, 3),
                    'risk_total': round(risk_total, 3),
                    'delta_risk': round(risk_total - baseline_risk, 3),
                    'risk_breakdown': _risk_breakdown(score),
                    'evidence': evidence,
                    'citations': citations,
                }
                hub_rank.append((_objective(option['risk_total'], option['delta_eta_hours'], shipment.risk_appetite), option))
            except Exception as exc:
                degrade_notes.append(f"fallback hub {hub['id']} degraded: {exc.__class__.__name__}")

        for _, option in sorted(hub_rank, key=lambda item: item[0])[:2]:
            if _within_constraints(option, constraints):
                candidates.append(option)

        if dominant_type:
            avoid_set = set(avoid_types)
            avoid_set.add(dominant_type)
            evidence, citations, _ = _normalize_evidence(baseline_score, avoid_set)
            penalty = sum(1 for item in base_evidence['incidents'] if item.get('event_type') == dominant_type)
            option = {
                'option_id': f'avoid_event_type_{dominant_type}',
                'label': f'Avoid {dominant_type} corridors',
                'geometry': request.selected_route.geometry,
                'eta_hours': round(baseline_eta + 1.0, 3),
                'delta_eta_hours': 1.0,
                'risk_total': round(max(0.0, baseline_risk - penalty * 2.0), 3),
                'delta_risk': round(max(0.0, baseline_risk - penalty * 2.0) - baseline_risk, 3),
                'risk_breakdown': baseline['risk_breakdown'],
                'evidence': evidence,
                'citations': citations,
            }
            if _within_constraints(option, constraints):
                candidates.append(option)

        ranked = sorted(candidates, key=lambda option: _objective(option['risk_total'], option['delta_eta_hours'], shipment.risk_appetite))[:3]
        if not ranked:
            fallback_delta = constraints.max_extra_eta_hours if constraints and constraints.max_extra_eta_hours is not None else 6.0
            fallback_delta = max(0.0, min(float(fallback_delta), 6.0))
            fallback_option = {
                'option_id': f'depart_later_{int(fallback_delta) if fallback_delta.is_integer() else fallback_delta}h',
                'label': f'Depart later (+{fallback_delta:g}h)',
                'geometry': request.selected_route.geometry,
                'eta_hours': round(baseline_eta + fallback_delta, 3),
                'delta_eta_hours': round(fallback_delta, 3),
                'risk_total': round(baseline_risk, 3),
                'delta_risk': 0.0,
                'risk_breakdown': baseline['risk_breakdown'],
                'evidence': base_evidence,
                'citations': base_citations,
            }
            if _within_constraints(fallback_option, constraints):
                ranked = [fallback_option]

        if not ranked:
            raise HTTPException(status_code=422, detail='No mitigation options available within provided constraints')

        win_rate = _simulate_win_rates(ranked, shipment.risk_appetite, 100, seed=hash(request_id) % (2**31))
        recommended = ranked[0]['option_id']

        if os.getenv('OPENAI_API_KEY', '').strip():
            narrative_markdown = f"Recommended **{recommended}** based on objective optimization over risk and ETA tradeoff."
        else:
            narrative_markdown = (
                f"### Mitigation Recommendation\n"
                f"- Baseline risk: **{baseline['risk_total']:.2f}**\n"
                f"- Recommended option: **{recommended}**\n"
                f"- Objective: minimize `risk_total + λ*delta_eta_hours` with λ from risk appetite."
            )

        if degrade_notes:
            narrative_markdown += "\n\n_Degraded mode: " + '; '.join(sorted(set(degrade_notes))) + "_"

        return {
            'request_id': request_id,
            'baseline': baseline,
            'options': ranked,
            'recommended_option_id': recommended,
            'robustness': {
                'runs': 100,
                'win_rate': win_rate,
                'sensitivity': {'hazard_multiplier': 'uniform[0.85,1.15]', 'event_severity_noise': 'uniform[0.9,1.1] + confidence uniform[0.9,1.1]'},
            },
            'narrative_markdown': narrative_markdown,
        }


class BriefIn(BaseModel):
    prompt: str


def _render_memo(prompt: str) -> str:
    lines = [
        '# Situation Brief',
        '',
        '## Summary',
        prompt.strip() or 'No summary provided.',
        '',
        '## Recommended Actions',
        '- Validate impacted route segments and timing windows.',
        '- Prioritize mitigations with lowest ETA increase for highest risk reduction.',
        '- Continue monitoring alerts/hazards for updates.',
        '',
        '## Citations',
        '- Internal planning signals and route risk evidence.',
    ]
    return '\n'.join(lines)


async def agent_brief(request: BriefIn) -> dict[str, str]:
    return {'memo': _render_memo(request.prompt)}
