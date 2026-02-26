from __future__ import annotations

from datetime import datetime
from pathlib import Path
import yaml

from .common import EventSourceCreate


def fetch_planned(path: str) -> list[EventSourceCreate]:
    payload = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    events: list[EventSourceCreate] = []
    for item in payload.get('disruptions', []):
        start_at = datetime.fromisoformat(item['start_at'].replace('Z', '+00:00'))
        end_at = datetime.fromisoformat(item['end_at'].replace('Z', '+00:00'))
        events.append(EventSourceCreate(
            source='planned', source_event_id=item['id'], title=item['title'], description=item.get('description'),
            url=item.get('url') or '', published_at=start_at, occurred_at=start_at, country=item.get('country'),
            event_type=item.get('event_type', 'OTHER'), subtype=item.get('subtype'), severity=float(item.get('severity', 0.6)),
            confidence=float(item.get('confidence', 0.85)), lat=float(item['lat']), lon=float(item['lon']), raw={'end_at': end_at.isoformat()},
        ))
    return events
