import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.plugins.validation_plugin import ValidationPlugin


def test_validate_claims_flags_risk_claim_without_evidence_ids() -> None:
    plugin = ValidationPlugin()
    payload = {
        'claims': [
            {
                'type': 'risk',
                'text': 'Elevated disruption risk on route segment A',
            }
        ]
    }

    result = plugin.validate_claims(payload, allowed_evidence_ids=['ev-1'])

    assert result['ok'] is False
    assert len(result['invalid_claims']) == 1
    assert result['invalid_claims'][0]['reason'] == 'missing_evidence_ids'


def test_validate_claims_flags_evidence_ids_not_in_allowed_list() -> None:
    plugin = ValidationPlugin()
    payload = {
        'claims': [
            {
                'type': 'risk',
                'text': 'Port congestion likely delays shipment',
                'evidence_ids': ['ev-1', 'ev-999'],
            }
        ]
    }

    result = plugin.validate_claims(payload, allowed_evidence_ids=['ev-1', 'ev-2'])

    assert result['ok'] is False
    assert len(result['invalid_claims']) == 1
    assert result['invalid_claims'][0]['reason'] == 'unapproved_evidence_ids'
    assert result['invalid_claims'][0]['invalid_evidence_ids'] == ['ev-999']


def test_validate_claims_ignores_non_risk_claims_without_evidence() -> None:
    plugin = ValidationPlugin()
    payload = {
        'claims': [
            {
                'type': 'status',
                'text': 'Weather remains stable',
            }
        ]
    }

    result = plugin.validate_claims(payload, allowed_evidence_ids=[])

    assert result['ok'] is True
    assert result['invalid_claims'] == []
