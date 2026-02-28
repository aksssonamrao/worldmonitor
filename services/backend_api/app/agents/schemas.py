from __future__ import annotations

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    evidence_id: str
    title: str = ''
    snippet: str = ''


class CaseFile(BaseModel):
    route_id: str
    summary: str = ''
    evidence_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class RiskReport(BaseModel):
    route_id: str
    risk_total: float = 0.0
    findings: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class MitigationPlan(BaseModel):
    route_id: str
    actions: list[str] = Field(default_factory=list)
    rationale: str = ''
    evidence_ids: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    route_id: str
    decision: str
    reasoning: str = ''
    evidence_ids: list[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    verified: bool
    issues: list[str] = Field(default_factory=list)
    invalid_claims: list[dict] = Field(default_factory=list)
    allowed_evidence_ids: list[str] = Field(default_factory=list)


class BriefOutput(BaseModel):
    markdown: str
    json_output: dict
    evidence_ids: list[str] = Field(default_factory=list)
