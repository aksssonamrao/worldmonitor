from __future__ import annotations

import logging
import httpx

from .common import EventSourceCreate, ISO3_TO_ISO2, parse_datetime_or_now, severity_from_text

logger = logging.getLogger(__name__)


def in_scope(country: str | None, region: str | None, focus_countries: list[str], focus_regions: list[str]) -> bool:
    country_match = country is not None and country.upper() in focus_countries
    region_match = region is not None and region.upper() in focus_regions
    if focus_countries and focus_regions:
        return country_match or region_match
    if focus_countries:
        return country_match
    if focus_regions:
        return region_match
    return True


async def fetch_reliefweb(
    client: httpx.AsyncClient,
    since_iso: str,
    focus_countries: list[str],
    focus_regions: list[str],
    appname: str,
) -> list[EventSourceCreate]:
    resp = await client.get(
        'https://api.reliefweb.int/v2/reports',
        params={
            'appname': appname,
            'limit': 100,
            'profile': 'full',
            'sort[]': 'date:desc',
            'filter[field]': 'date.created',
            'filter[value][from]': since_iso,
        },
        timeout=20,
    )
    if resp.status_code >= 400:
        if resp.status_code in (400, 401, 403):
            logger.error('Set RELIEFWEB_APPNAME to your pre-approved appname; request approval from ReliefWeb if needed.')
            return []
        resp.raise_for_status()
    events: list[EventSourceCreate] = []
    for item in resp.json().get('data', []):
        fields = item.get('fields', {})
        origin = fields.get('origin') or {}
        lat, lon = origin.get('lat'), origin.get('lon')
        if lat is None or lon is None:
            continue
        pcountry = fields.get('primary_country') or {}
        country = ISO3_TO_ISO2.get((pcountry.get('iso3') or '').upper(), (pcountry.get('iso3') or '').upper()) or None
        region = (pcountry.get('region') or '').upper() or None
        if not in_scope(country, region, focus_countries, focus_regions):
            continue
        source_event_id = str(item.get('id'))
        title = fields.get('title') or 'Untitled'
        occurred = parse_datetime_or_now((fields.get('date') or {}).get('created'))
        events.append(EventSourceCreate(
            source='reliefweb', source_event_id=source_event_id, title=title, description=fields.get('body'), url=fields.get('url') or '',
            published_at=occurred, occurred_at=occurred, country=country, event_type='DISASTER', subtype=None,
            severity=max(0.65, severity_from_text(title)), confidence=0.85, lat=float(lat), lon=float(lon),
            raw={'source': fields.get('source'), 'country': fields.get('country')},
        ))
    return events
