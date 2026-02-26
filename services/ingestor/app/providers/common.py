from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'to', 'of', 'in', 'on', 'for', 'at', 'by', 'with', 'from',
    'is', 'are', 'was', 'were', 'be', 'been', 'it', 'this', 'that', 'as', 'after', 'near', 'into'
}

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

BASE32 = '0123456789bcdefghjkmnpqrstuvwxyz'


@dataclass
class EventSourceCreate:
    source: str
    source_event_id: str
    title: str
    description: str | None
    url: str
    published_at: datetime
    occurred_at: datetime | None
    country: str | None
    event_type: str
    subtype: str | None
    severity: float
    confidence: float
    lat: float
    lon: float
    raw: dict[str, Any]


def classify_event_type(text: str) -> str:
    t = (text or '').lower()
    if any(k in t for k in ['protest', 'riot']):
        return 'PROTEST'
    if 'strike' in t:
        return 'STRIKE'
    if any(k in t for k in ['conflict', 'violence', 'terror', 'war']):
        return 'CONFLICT'
    if any(k in t for k in ['flood', 'cyclone', 'landslide', 'storm', 'heatwave', 'disaster', 'earthquake', 'wildfire']):
        return 'DISASTER'
    if any(k in t for k in ['outage', 'blackout']):
        return 'OUTAGE'
    if any(k in t for k in ['accident', 'crash', 'derailment']):
        return 'ACCIDENT'
    return 'OTHER'


def severity_from_text(text: str) -> float:
    t = (text or '').lower()
    if any(k in t for k in ['emergency', 'major', 'severe', 'fatal', 'catastrophic']):
        return 0.8
    if any(k in t for k in ['disruption', 'warning', 'closure', 'damage']):
        return 0.6
    return 0.4


def parse_datetime_or_now(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def normalize_text(title: str, description: str | None) -> str:
    raw = f"{title or ''} {description or ''}".lower()
    raw = re.sub(r'https?://\S+', ' ', raw)
    raw = re.sub(r'[^\w\s]', ' ', raw)
    tokens = [t for t in raw.split() if t not in STOPWORDS]
    return ' '.join(tokens)


def compute_simhash64(text: str) -> int:
    if not text:
        return 0
    vector = [0] * 64
    for token in text.split():
        from hashlib import blake2b
        h = int.from_bytes(blake2b(token.encode('utf-8'), digest_size=8).digest(), 'big')
        for i in range(64):
            vector[i] += 1 if (h >> i) & 1 else -1
    result = 0
    for i, value in enumerate(vector):
        if value >= 0:
            result |= (1 << i)
    return result


def hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def compute_geohash(lat: float, lon: float, precision: int = 6) -> str:
    lat_interval = [-90.0, 90.0]
    lon_interval = [-180.0, 180.0]
    geohash = []
    is_even = True
    bit = 0
    ch = 0
    while len(geohash) < precision:
        if is_even:
            mid = (lon_interval[0] + lon_interval[1]) / 2
            if lon > mid:
                ch |= 1 << (4 - bit)
                lon_interval[0] = mid
            else:
                lon_interval[1] = mid
        else:
            mid = (lat_interval[0] + lat_interval[1]) / 2
            if lat > mid:
                ch |= 1 << (4 - bit)
                lat_interval[0] = mid
            else:
                lat_interval[1] = mid
        is_even = not is_even
        if bit < 4:
            bit += 1
        else:
            geohash.append(BASE32[ch])
            bit = 0
            ch = 0
    return ''.join(geohash)


def time_bucket(ts: datetime, bucket_minutes: int = 60) -> datetime:
    seconds = int(ts.timestamp())
    bucket = bucket_minutes * 60
    return datetime.fromtimestamp(seconds - (seconds % bucket), tz=timezone.utc)


def incident_key(event_type: str, subtype: str | None, geohash: str, bucket: datetime, normalized_text: str) -> str:
    from hashlib import sha1

    prefix_hash = sha1(normalized_text[:80].encode('utf-8')).hexdigest()[:8]
    return f"{event_type}:{subtype or 'na'}:{geohash}:{bucket.isoformat()}:{prefix_hash}"
