from __future__ import annotations

from typing import Any

from app.agents.plugins._sk_compat import kernel_function


class ValidationPlugin:
    """Strict output validation tools for evidence-grounded agent responses."""

    @staticmethod
    def _claims_list(claims_json: dict[str, Any]) -> list[dict[str, Any]]:
        claims = claims_json.get('claims', [])
        if isinstance(claims, list):
            return [item for item in claims if isinstance(item, dict)]
        return []

    @staticmethod
    def _normalize_evidence_ids(claim: dict[str, Any]) -> list[str]:
        evidence_ids = claim.get('evidence_ids', [])
        if not isinstance(evidence_ids, list):
            return []
        return [str(eid) for eid in evidence_ids if str(eid).strip()]

    @staticmethod
    def _is_risk_claim(claim: dict[str, Any]) -> bool:
        claim_type = str(claim.get('type', '')).strip().lower()
        return claim_type == 'risk'

    @kernel_function(name='validate_claims', description='Validate claims are grounded to allowed evidence IDs')
    def validate_claims(self, claims_json: dict[str, Any], allowed_evidence_ids: list[str]) -> dict[str, Any]:
        allowed = {str(item) for item in allowed_evidence_ids}
        invalid_claims: list[dict[str, Any]] = []

        for index, claim in enumerate(self._claims_list(claims_json)):
            if not self._is_risk_claim(claim):
                continue

            evidence_ids = self._normalize_evidence_ids(claim)
            if not evidence_ids:
                invalid_claims.append(
                    {
                        'index': index,
                        'reason': 'missing_evidence_ids',
                        'claim': claim,
                    }
                )
                continue

            disallowed = sorted([evidence_id for evidence_id in evidence_ids if evidence_id not in allowed])
            if disallowed:
                invalid_claims.append(
                    {
                        'index': index,
                        'reason': 'unapproved_evidence_ids',
                        'invalid_evidence_ids': disallowed,
                        'claim': claim,
                    }
                )

        return {
            'ok': len(invalid_claims) == 0,
            'invalid_claims': invalid_claims,
        }

    @kernel_function(name='enforce_no_new_claims', description='Enforce that outputs only cite approved evidence IDs')
    def enforce_no_new_claims(self, output_json: dict[str, Any], allowed_evidence_ids: list[str]) -> dict[str, Any]:
        validation = self.validate_claims(output_json, allowed_evidence_ids)
        return {
            'ok': validation['ok'],
            'invalid_claims': validation['invalid_claims'],
            'violations_count': len(validation['invalid_claims']),
        }
