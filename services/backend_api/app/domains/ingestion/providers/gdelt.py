from __future__ import annotations

from hashlib import sha1
import httpx

from app.domains.ingestion.providers.common import DISRUPTION_KEYWORDS, EventSourceCreate, classify_event_type, parse_datetime_or_now, severity_from_text


async def fetch_gdelt(client: httpx.AsyncClient, since_iso: str, focus_countries: list[str]) -> list[EventSourceCreate]:
    query = ' OR '.join(DISRUPTION_KEYWORDS)
    resp = await client.get(
        'https://api.gdeltproject.org/api/v2/doc/doc',
        params={'query': query, 'format': 'json', 'mode': 'ArtList', 'maxrecords': 250, 'sort': 'DateDesc', 'startdatetime': since_iso},
        timeout=20,
    )
    resp.raise_for_status()
    events: list[EventSourceCreate] = []
    for article in resp.json().get('articles', []):
        country = (article.get('sourcecountry') or '').upper() or None
        if focus_countries and country and country not in focus_countries:
            continue
        loc = article.get('locations', [{}])[0] if article.get('locations') else {}
        lat, lon = loc.get('lat'), loc.get('lon')
        if lat is None or lon is None:
            continue
        title = article.get('title') or 'Untitled'
        source_event_id = str(article.get('url') or article.get('seendate') or sha1(title.encode()).hexdigest())
        occurred = parse_datetime_or_now(article.get('seendate'))
        events.append(EventSourceCreate(
            source='gdelt', source_event_id=source_event_id, title=title, description=article.get('title') or article.get('sourceCollection'),
            url=article.get('url') or '', published_at=occurred, occurred_at=occurred, country=country,
            event_type=classify_event_type(title), subtype=None, severity=severity_from_text(title), confidence=0.7,
            lat=float(lat), lon=float(lon), raw={'sourceCollection': article.get('sourceCollection'), 'themes': article.get('themes'), 'tone': article.get('tone')},
        ))
    return events
