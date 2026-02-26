from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha1


from .common import DISRUPTION_KEYWORDS, EventSourceCreate, classify_event_type, severity_from_text


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


async def fetch_rss_events(rss_path: str, focus_countries: list[str], focus_regions: list[str]) -> list[EventSourceCreate]:
    import yaml
    import feedparser

    with open(rss_path, 'r', encoding='utf-8') as fh:
        config = yaml.safe_load(fh) or {}
    events: list[EventSourceCreate] = []
    for feed in config.get('feeds', []):
        country = (feed.get('country') or '').upper() or None
        region = (feed.get('region') or '').upper() or None
        if not in_scope(country, region, focus_countries, focus_regions) or feed.get('enabled', True) is False:
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
                    pass
            lat, lon = feed.get('default_lat'), feed.get('default_lon')
            if lat is None or lon is None:
                continue
            guid = entry.get('id') or entry.get('link') or sha1(text.encode()).hexdigest()
            events.append(EventSourceCreate(
                source='rss', source_event_id=str(guid), title=entry.get('title') or 'Untitled', description=entry.get('summary'), url=entry.get('link') or '',
                published_at=occurred_at, occurred_at=occurred_at, country=country, event_type=classify_event_type(text), subtype=None,
                severity=severity_from_text(text), confidence=0.5, lat=float(lat), lon=float(lon), raw={'feed': feed.get('name')},
            ))
    return events
