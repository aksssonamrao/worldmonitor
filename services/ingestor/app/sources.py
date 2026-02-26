from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha1
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DISRUPTION_KEYWORDS = [
    'protest', 'riot', 'strike', 'conflict', 'violence', 'terror',
    'flood', 'cyclone', 'landslide', 'outage', 'blackout', 'blockade',
    'airport', 'port', 'border', 'rail', 'highway closure', 'logistics',
]

ISO3_TO_ISO2 = {
    'ARE': 'AE',
    'GBR': 'GB',
    'USA': 'US',
    'IND': 'IN',
}


def classify_event_type(text: str) -> str:
    t = (text or '').lower()
    if any(k in t for k in ['protest', 'riot']):
        return 'PROTEST'
    if 'strike' in t:
        return 'STRIKE'
    if any(k in t for k in ['conflict', 'violence', 'terror', 'war']):
        return 'CONFLICT'
    if any(k in t for k in ['flood', 'cyclone', 'landslide', 'storm', 'heatwave', 'disaster']):
        return 'DISASTER'
    if any(k in t for k in ['outage', 'blackout']):
        return 'OUTAGE'
    if any(k in t for k in ['accident', 'crash', 'derailment']):
        return 'ACCIDENT'
    return 'OTHER'


def severity_from_text(text: str) -> float:
    t = (text or '').lower()
    severe_terms = ['emergency', 'major', 'severe', 'fatal', 'catastrophic']
    medium_terms = ['disruption', 'warning', 'closure', 'damage']
    if any(k in t for k in severe_terms):
        return 0.8
    if any(k in t for k in medium_terms):
        return 0.6
    return 0.4


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


def parse_datetime_or_now(raw: str | None, record_id: str) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        logger.warning('Invalid occurred_at timestamp for %s: %r', record_id, raw)
        return datetime.now(timezone.utc)


async def fetch_gdelt(client: httpx.AsyncClient, since_iso: str, focus_countries: list[str]) -> list[dict[str, Any]]:
    query = ' OR '.join(DISRUPTION_KEYWORDS)
    resp = await client.get(
        'https://api.gdeltproject.org/api/v2/doc/doc',
        params={
            'query': query,
            'format': 'json',
            'mode': 'ArtList',
            'maxrecords': 250,
            'sort': 'DateDesc',
            'startdatetime': since_iso,
        },
        timeout=20,
    )
    resp.raise_for_status()
    events = []
    for article in resp.json().get('articles', []):
        country = (article.get('sourcecountry') or '').upper() or None
        if focus_countries and country and country not in focus_countries:
            continue
        lat = article.get('locations', [{}])[0].get('lat') if article.get('locations') else None
        lon = article.get('locations', [{}])[0].get('lon') if article.get('locations') else None
        if lat is None or lon is None:
            continue
        title = article.get('title') or 'Untitled'
        source_event_id = str(article.get('url') or article.get('seendate') or sha1(title.encode()).hexdigest())
        events.append({
            'source': 'gdelt',
            'source_event_id': source_event_id,
            'title': title,
            'description': article.get('seendate'),
            'url': article.get('url') or '',
            'event_type': classify_event_type(title),
            'severity': severity_from_text(title),
            'confidence': 0.7,
            'country': country,
            'region': article.get('region') or article.get('domain'),
            'occurred_at': parse_datetime_or_now(article.get('seendate'), source_event_id),
            'lat': float(lat),
            'lon': float(lon),
            'raw': {
                'sourceCollection': article.get('sourceCollection'),
                'themes': article.get('themes'),
                'tone': article.get('tone'),
            },
        })
    return events


async def fetch_reliefweb(
    client: httpx.AsyncClient,
    since_iso: str,
    focus_countries: list[str],
    focus_regions: list[str],
) -> list[dict[str, Any]]:
    resp = await client.post(
        'https://api.reliefweb.int/v1/reports',
        json={
            'appname': 'worldmonitor',
            'query': {'value': 'flood OR cyclone OR landslide OR heatwave OR disaster'},
            'filter': {'field': 'date.created', 'value': {'from': since_iso}},
            'fields': {'include': ['id', 'title', 'url', 'date', 'source', 'country', 'body', 'primary_country', 'origin']},
            'limit': 100,
        },
        timeout=20,
    )
    resp.raise_for_status()
    events = []
    for item in resp.json().get('data', []):
        fields = item.get('fields', {})
        origin = fields.get('origin') or {'lat': None, 'lon': None}
        lat, lon = origin.get('lat'), origin.get('lon')
        if lat is None or lon is None:
            continue
        country = ISO3_TO_ISO2.get((fields.get('primary_country') or {}).get('iso3', ''), (fields.get('primary_country') or {}).get('iso3'))
        country = country.upper() if country else None
        region = ((fields.get('primary_country') or {}).get('region') or '').upper() or None
        if not in_scope(country, region, focus_countries, focus_regions):
            continue
        source_event_id = str(item.get('id'))
        title = fields.get('title', 'Untitled')
        events.append({
            'source': 'reliefweb',
            'source_event_id': source_event_id,
            'title': title,
            'description': fields.get('body'),
            'url': fields.get('url') or '',
            'event_type': 'DISASTER',
            'severity': max(0.65, severity_from_text(title)),
            'confidence': 0.85,
            'country': country,
            'region': region,
            'occurred_at': parse_datetime_or_now(fields.get('date', {}).get('created'), source_event_id),
            'lat': float(lat),
            'lon': float(lon),
            'raw': {'source': fields.get('source'), 'country': fields.get('country')},
        })
    return events


async def fetch_rss_events(rss_path: str, focus_countries: list[str], focus_regions: list[str]) -> list[dict[str, Any]]:
    import yaml
    import feedparser

    with open(rss_path, 'r', encoding='utf-8') as fh:
        config = yaml.safe_load(fh) or {}
    feeds = config.get('feeds', [])
    events = []
    for feed in feeds:
        country = (feed.get('country') or '').upper() or None
        region = (feed.get('region') or '').upper() or None
        if not in_scope(country, region, focus_countries, focus_regions):
            continue
        if feed.get('enabled', True) is False:
            continue
        parsed = feedparser.parse(feed['url'])
        for entry in parsed.entries[:20]:
            text = f"{entry.get('title', '')} {entry.get('summary', '')}".strip()
            if not any(keyword in text.lower() for keyword in DISRUPTION_KEYWORDS):
                continue
            published = entry.get('published') or entry.get('updated')
            occurred_at = datetime.now(timezone.utc)
            if published:
                try:
                    occurred_at = parsedate_to_datetime(published)
                    if occurred_at.tzinfo is None:
                        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    logger.warning('Invalid RSS timestamp for feed %s: %r', feed.get('name'), published)
            lat = feed.get('default_lat')
            lon = feed.get('default_lon')
            if lat is None or lon is None:
                continue
            guid = entry.get('id') or entry.get('link') or sha1(text.encode()).hexdigest()
            events.append({
                'source': 'rss',
                'source_event_id': str(guid),
                'title': entry.get('title') or 'Untitled',
                'description': entry.get('summary'),
                'url': entry.get('link') or '',
                'event_type': classify_event_type(text),
                'severity': severity_from_text(text),
                'confidence': 0.5,
                'country': country,
                'region': region,
                'occurred_at': occurred_at,
                'lat': float(lat),
                'lon': float(lon),
                'raw': {'feed': feed.get('name')},
            })
    return events
