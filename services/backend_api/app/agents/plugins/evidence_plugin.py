from __future__ import annotations

from typing import Any

from app.agents.plugins._sk_compat import kernel_function


class EvidencePlugin:
    """Deterministic evidence lookup tools exposed to Semantic Kernel agents."""

    @kernel_function(name='search_evidence', description='Search evidence records for a route and time window')
    def search_evidence(self, route_id: str, time_window_hours: int, types: list[str] | None = None) -> dict[str, Any]:
        return {
            'route_id': route_id,
            'time_window_hours': int(time_window_hours),
            'types': types or [],
            'items': [],
            'count': 0,
        }

    @kernel_function(name='get_evidence', description='Return a single evidence object by id')
    def get_evidence(self, evidence_id: str) -> dict[str, Any]:
        return {
            'evidence_id': evidence_id,
            'found': False,
            'item': None,
        }

    @kernel_function(name='vector_search', description='Vector similarity search over evidence corpus')
    def vector_search(self, query: str, bbox: dict[str, Any], k: int = 20) -> list[dict[str, Any]]:
        _ = (query, bbox, k)
        return []

    @kernel_function(name='lexical_search', description='Keyword/lexical search over evidence corpus')
    def lexical_search(self, query: str, bbox: dict[str, Any], k: int = 20) -> list[dict[str, Any]]:
        _ = (query, bbox, k)
        return []
