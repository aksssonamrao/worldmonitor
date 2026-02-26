from __future__ import annotations

from datetime import datetime, timedelta, timezone
import httpx

from .common import EventSourceCreate


def magnitude_severity(mag: float) -> float:
    if mag <= 3:
        return 0.2
    if mag < 4:
        return 0.35
    if mag < 5:
        return 0.5
    if mag < 6:
        return 0.7
    if mag < 7:
        return 0.85
    return 1.0


async def fetch_usgs(client: httpx.AsyncClient, lookback_hours: int, min_magnitude: float) -> list[EventSourceCreate]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=lookback_hours)
    resp = await client.get(
        'https://earthquake.usgs.gov/fdsnws/event/1/query',
        params={
            'format': 'geojson',
            'starttime': start.date().isoformat(),
            'endtime': end.date().isoformat(),
            'minmagnitude': min_magnitude,
        },
        timeout=20,
    )
    resp.raise_for_status()
    events: list[EventSourceCreate] = []
    for feat in resp.json().get('features', []):
        props = feat.get('properties') or {}
        geom = feat.get('geometry') or {}
        coords = geom.get('coordinates') or []
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        mag = float(props.get('mag') or 0)
        epoch_ms = props.get('time')
        occurred = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc) if epoch_ms else datetime.now(timezone.utc)
        events.append(EventSourceCreate(
            source='usgs', source_event_id=str(feat.get('id') or props.get('code')), title=props.get('title') or 'USGS Earthquake',
            description=props.get('place'), url=props.get('url') or '', published_at=occurred, occurred_at=occurred,
            country=None, event_type='DISASTER', subtype='EARTHQUAKE', severity=magnitude_severity(mag), confidence=0.95,
            lat=lat, lon=lon, raw={'mag': mag, 'place': props.get('place'), 'tsunami': props.get('tsunami')},
        ))
    return events
