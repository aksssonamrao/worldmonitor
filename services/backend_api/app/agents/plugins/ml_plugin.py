from __future__ import annotations

from typing import Any

from app.agents.plugins._sk_compat import kernel_function


class MLPlugin:
    """ML-oriented deterministic helpers (stubs until model services are wired)."""

    @kernel_function(name='get_relevance_scores', description='Return relevance scores for a route')
    def get_relevance_scores(self, route_id: str) -> dict[str, Any]:
        return {'route_id': route_id, 'scores': {}, 'status': 'stub'}

    @kernel_function(name='get_calibration', description='Return calibration metadata for route risk outputs')
    def get_calibration(self, route_id: str) -> dict[str, Any]:
        return {'route_id': route_id, 'calibration': {}, 'status': 'stub'}

    @kernel_function(name='get_clusters', description='Return spatiotemporal clusters in a bounding box/time window')
    def get_clusters(self, bbox: dict[str, Any], time_window_hours: int) -> dict[str, Any]:
        return {
            'bbox': bbox,
            'time_window_hours': int(time_window_hours),
            'clusters': [],
            'status': 'stub',
        }
