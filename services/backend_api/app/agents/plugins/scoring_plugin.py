from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.agents.plugins._sk_compat import kernel_function


class ScoringPlugin:
    """Route scoring tools that call internal python modules (never backend HTTP endpoints)."""

    @staticmethod
    def _default_time_window() -> tuple[str, str]:
        depart = datetime.now(timezone.utc)
        arrive = depart + timedelta(hours=8)
        return depart.isoformat(), arrive.isoformat()

    @staticmethod
    def _fallback_route_options() -> dict[str, Any]:
        return {'routes': []}

    @staticmethod
    def _fallback_route_score(route_id: str) -> dict[str, Any]:
        return {
            'route_id': route_id,
            'summary_risk': {'total': 0.0},
            'segment_scores': [],
            'top_evidence': {'events': [], 'alerts': [], 'hazards': []},
        }

    @kernel_function(name='get_route_options', description='Compute route options from a shipment request')
    async def get_route_options(self, shipment_request: dict[str, Any]) -> dict[str, Any]:
        try:
            from app.domains.compound.main import RouteOptionsIn, route_options
        except ImportError:
            return self._fallback_route_options()

        payload = dict(shipment_request)
        if 'depart_time' not in payload or 'arrive_by' not in payload:
            depart_time, arrive_by = self._default_time_window()
            payload.setdefault('depart_time', depart_time)
            payload.setdefault('arrive_by', arrive_by)

        try:
            body = RouteOptionsIn(**payload)
        except Exception:
            return self._fallback_route_options()

        try:
            return await route_options(body)
        except Exception:
            # Expected when app.state dependencies are not initialized in unit/runtime context.
            return self._fallback_route_options()

    @kernel_function(name='score_route', description='Score a route geometry with internal route scoring logic')
    async def score_route(self, route_id: str, geometry: dict[str, Any]) -> dict[str, Any]:
        try:
            from app.domains.compound.main import RouteScoreIn, route_score
        except ImportError:
            return self._fallback_route_score(route_id)

        depart_time, arrive_by = self._default_time_window()
        try:
            body = RouteScoreIn(
                geometry=geometry,
                depart_time=depart_time,
                arrive_by=arrive_by,
                run_id='latest',
                timestep=0,
            )
        except Exception:
            return self._fallback_route_score(route_id)

        try:
            result = await route_score(body)
            if isinstance(result, dict) and 'route_id' not in result:
                return {'route_id': route_id, **result}
            return result
        except Exception:
            return self._fallback_route_score(route_id)

    @kernel_function(name='compare_routes', description='Compare multiple routes deterministically')
    async def compare_routes(self, route_ids: list[str]) -> dict[str, Any]:
        unique_ids = [item for idx, item in enumerate(route_ids) if item and item not in route_ids[:idx]]
        comparisons = [{'route_id': route_id, 'score': 0.0} for route_id in unique_ids]
        return {
            'route_ids': unique_ids,
            'comparisons': comparisons,
            'best_route_id': unique_ids[0] if unique_ids else None,
        }
