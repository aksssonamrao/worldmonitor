from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha1
from typing import Any

import httpx

DISRUPTION_KEYWORDS = [
    'protest', 'riot', 'strike', 'conflict', 'violence', 'terror',
    'flood', 'cyclone', 'landslide', 'outage', 'blackout', 'blockade',
    'airport', 'port', 'border', 'rail', 'highway closure', 'logistics',
]


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


async def fetch_gdelt(client: httpx.AsyncClient, since_iso: str, focus_countries: list[str]) -> list[dict[str, Any]]:
    query = ' OR '.join(DISRUPTION_KEYWORDS)
    url = 'https://api.gdeltproject.org/api/v2/doc/doc'
    params = {
        'query': query,
        'format': 'json',
        'mode': 'ArtList',
        'maxrecords': 250,
        'sort': 'DateDesc',
        'startdatetime': since_iso,
    }
    resp = await client.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    articles = data.get('articles', [])
    events = []
    for article in articles:
        country = (article.get('sourcecountry') or '').upper()
        if focus_countries and country and country not in focus_countries:
            continue
        lat = article.get('locations', [{}])[0].get('lat') if article.get('locations') else None
        lon = article.get('locations', [{}])[0].get('lon') if article.get('locations') else None
        if lat is None or lon is None:
            continue
        title = article.get('title') or 'Untitled'
        events.append({
            'source': 'gdelt',
            'source_event_id': str(article.get('url') or article.get('seendate') or sha1(title.encode()).hexdigest()),
            'title': title,
            'description': article.get('seendate'),
            'url': article.get('url') or '',
            'event_type': classify_event_type(title),
            'severity': severity_from_text(title),
            'confidence': 0.7,
            'country': country or None,
            'region': article.get('domain'),
            'occurred_at': datetime.fromisoformat(article.get('seendate').replace('Z', '+00:00')) if article.get('seendate') else datetime.now(timezone.utc),
            'lat': float(lat),
            'lon': float(lon),
            'raw': {
                'sourceCollection': article.get('sourceCollection'),
                'themes': article.get('themes'),
                'tone': article.get('tone'),
            },
        })
    return events


async def fetch_reliefweb(client: httpx.AsyncClient, since_iso: str) -> list[dict[str, Any]]:
    payload = {
        'appname': 'worldmonitor',
        'query': {'value': 'flood OR cyclone OR landslide OR heatwave OR disaster'},
        'filter': {'field': 'date.created', 'value': {'from': since_iso}},
        'fields': {'include': ['id', 'title', 'url', 'date', 'source', 'country', 'body', 'primary_country', 'origin']},
        'limit': 100,
    }
    resp = await client.post('https://api.reliefweb.int/v1/reports', json=payload, timeout=20)
    resp.raise_for_status()
    items = resp.json().get('data', [])
    events = []
    for item in items:
        fields = item.get('fields', {})
        origin = fields.get('origin') or {'lat': None, 'lon': None}
        lat, lon = origin.get('lat'), origin.get('lon')
        if lat is None or lon is None:
            continue
        title = fields.get('title', 'Untitled')
        events.append({
            'source': 'reliefweb',
            'source_event_id': str(item.get('id')),
            'title': title,
            'description': fields.get('body'),
            'url': fields.get('url') or '',
            'event_type': 'DISASTER',
            'severity': max(0.65, severity_from_text(title)),
            'confidence': 0.85,
            'country': (fields.get('primary_country') or {}).get('iso3'),
            'region': None,
            'occurred_at': datetime.fromisoformat(fields.get('date', {}).get('created').replace('Z', '+00:00')),
            'lat': float(lat),
            'lon': float(lon),
            'raw': {'source': fields.get('source'), 'country': fields.get('country')},
        })
    return events


async def fetch_rss_events(rss_path: str) -> list[dict[str, Any]]:
    import yaml
    import feedparser

    with open(rss_path, 'r', encoding='utf-8') as fh:
        config = yaml.safe_load(fh) or {}
    feeds = config.get('feeds', [])
    events = []
    for feed in feeds:
        if feed.get('enabled', True) is False:
            continue
        parsed = feedparser.parse(feed['url'])
        for entry in parsed.entries[:20]:
            text = f"{entry.get('title', '')} {entry.get('summary', '')}".strip()
            if not any(keyword in text.lower() for keyword in DISRUPTION_KEYWORDS):
                continue
            published = entry.get('published') or entry.get('updated')
            occurred_at = parsedate_to_datetime(published) if published else datetime.now(timezone.utc)
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=timezone.utc)
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
                'country': feed.get('country'),
                'region': feed.get('region'),
                'occurred_at': occurred_at,
                'lat': float(lat),
                'lon': float(lon),
                'raw': {'feed': feed.get('name')},
            })
    return events
