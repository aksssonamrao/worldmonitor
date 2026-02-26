from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.providers.common import compute_geohash, compute_simhash64, hamming_distance, incident_key, normalize_text, time_bucket


def test_simhash_merges_same_story_same_geo_time():
    t1 = normalize_text('Major earthquake disrupts roads in Gujarat', 'USGS M5.4 quake near Gujarat')
    t2 = normalize_text('Earthquake disrupts roads in Gujarat', 'M5.4 quake reported near Gujarat roads')
    d = hamming_distance(compute_simhash64(t1), compute_simhash64(t2))
    assert d <= 12


def test_no_merge_when_far_apart():
    g1 = compute_geohash(19.1, 72.8, 6)
    g2 = compute_geohash(51.5, -0.1, 6)
    assert g1 != g2


def test_no_merge_when_time_far():
    ts = datetime.now(timezone.utc)
    b1 = time_bucket(ts)
    b2 = time_bucket(ts + timedelta(hours=12))
    assert b1 != b2


def test_title_preference_reliefweb_over_gdelt():
    preference = {'reliefweb': 6, 'usgs': 5, 'firms': 4, 'planned': 3, 'rss': 2, 'gdelt': 1}
    source_titles = [('gdelt', 'Noisy title'), ('reliefweb', 'Curated title')]
    best = max(source_titles, key=lambda s: preference[s[0]])
    assert best[1] == 'Curated title'


def test_incident_key_stable():
    ts = datetime(2026, 1, 1, 0, 33, tzinfo=timezone.utc)
    bucket = time_bucket(ts)
    text = normalize_text('Port strike in London', 'Workers strike at port terminal')
    first = incident_key('STRIKE', 'PORT_DISRUPTION', 'gcpvj0', bucket, text)
    second = incident_key('STRIKE', 'PORT_DISRUPTION', 'gcpvj0', bucket, text)
    assert first == second
