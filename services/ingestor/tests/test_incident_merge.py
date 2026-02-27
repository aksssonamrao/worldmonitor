from __future__ import annotations

from uuid import uuid4

from app.storage import pick_incident_candidate


def _candidate(dist_hash: int):
    return {'id': uuid4(), 'representative_simhash64': dist_hash}


def test_pick_incident_candidate_merges_within_threshold():
    simhash = int('10101010', 2)
    candidates = [
        _candidate(int('11110000', 2)),
        _candidate(int('10101011', 2)),
    ]

    winner = pick_incident_candidate(simhash, candidates, max_distance=2)

    assert winner == candidates[1]['id']


def test_pick_incident_candidate_rejects_when_distance_too_large():
    simhash = int('00000000', 2)
    candidates = [
        _candidate(int('11111111', 2)),
    ]

    winner = pick_incident_candidate(simhash, candidates, max_distance=2)

    assert winner is None
