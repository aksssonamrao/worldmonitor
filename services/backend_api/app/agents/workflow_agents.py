from __future__ import annotations

import json
from typing import Any

from app.agents.plugins import EvidencePlugin, MLPlugin, ScoringPlugin, ValidationPlugin
from app.agents.prompts import (
    SYSTEM_PROMPT_BRIEF_WRITER,
    SYSTEM_PROMPT_DECISION,
    SYSTEM_PROMPT_DISPATCHER,
    SYSTEM_PROMPT_MITIGATION,
    SYSTEM_PROMPT_RETRIEVER,
    SYSTEM_PROMPT_RISK_ANALYST,
    SYSTEM_PROMPT_VERIFIER,
)
from app.agents.schemas import BriefOutput, CaseFile, Decision, EvidenceItem, MitigationPlan, RiskReport, VerificationResult
from app.core.llm_config import llm_settings
from app.llm.gemini_client import GeminiClient
from app.llm.kernel_factory import ModelRouter
from app.llm.sk_gemini_adapter import SKGeminiChatAdapter


class AgentLLMRunner:
    def __init__(self) -> None:
        self.router = ModelRouter()
        self._flash = None
        self._pro = None
        if llm_settings.GEMINI_API_KEY.strip():
            client = GeminiClient()
            self._flash = SKGeminiChatAdapter('gemini_flash', llm_settings.GEMINI_FLASH_MODEL, client)
            self._pro = SKGeminiChatAdapter('gemini_pro', llm_settings.GEMINI_PRO_MODEL, client)

    async def complete_json(self, step_name: str, payload: dict[str, Any], system_prompt: str, strict: bool = False) -> dict[str, Any]:
        service = self.router.choose_service(step_name)
        adapter = self._pro if service == 'gemini_pro' else self._flash
        if adapter is None:
            return {}
        defaults = {'temperature': 0.25, 'max_tokens': 2200, 'top_p': 0.95, 'top_k': 40} if service == 'gemini_pro' else {
            'temperature': float(llm_settings.AGENT_TEMPERATURE),
            'max_tokens': int(llm_settings.AGENT_MAX_TOKENS),
            'top_p': 0.95,
            'top_k': 20,
        }
        if strict:
            system_prompt = f"{system_prompt}\n\nOnly use allowed evidence_ids, no new claims."
        text = await adapter.complete_chat(
            messages=[{'role': 'user', 'content': json.dumps(payload)}],
            settings={**defaults, 'system': system_prompt},
        )
        try:
            return json.loads(text)
        except Exception:
            return {}


async def dispatcher_agent(request: dict[str, Any], llm: AgentLLMRunner) -> dict[str, Any]:
    default = {
        'run_steps': ['retrieve', 'risk', 'mitigation', 'decision', 'verify', 'brief'],
        'model_policy': {'retrieve': 'flash', 'risk': 'pro', 'mitigation': 'flash', 'decision': 'pro', 'verify': 'pro', 'brief': 'flash'},
        'budgets': {'max_tool_calls_per_step': llm_settings.AGENT_MAX_TOOL_CALLS, 'max_evidence_per_route': llm_settings.AGENT_MAX_EVIDENCE_PER_ROUTE, 'max_total_evidence': 80, 'max_routes': 3},
        'notes': 'default full pipeline',
    }
    result = await llm.complete_json('dispatcher', {'request_json': request, 'system_state_json': {}}, SYSTEM_PROMPT_DISPATCHER)
    return result if isinstance(result.get('run_steps'), list) else default


async def retriever_agent(request: dict[str, Any], llm: AgentLLMRunner) -> CaseFile:
    route_id = str(request.get('route_id', 'unknown'))
    plugin = EvidencePlugin()
    data = plugin.search_evidence(route_id=route_id, time_window_hours=int(request.get('time_window_hours', 24)), types=request.get('types'))
    result = await llm.complete_json('retrieve', {'routes_json': [{'route_id': route_id}], 'retrieved_evidence_json': data.get('items', [])}, SYSTEM_PROMPT_RETRIEVER)
    evidence = [EvidenceItem(evidence_id=str(item.get('evidence_id', '')), title=str(item.get('title', '')), snippet=str(item.get('snippet', ''))) for item in data.get('items', []) if item.get('evidence_id')]
    case_file = CaseFile(route_id=route_id, summary='Retrieved evidence context', evidence_ids=[e.evidence_id for e in evidence], evidence=evidence)
    if isinstance(result, dict) and isinstance(result.get('case_files'), list) and result['case_files']:
        first = result['case_files'][0]
        case_file.summary = str(first.get('unknowns', [''])[0]) if first.get('unknowns') else case_file.summary
    return case_file


async def risk_analyst_agent(case_file: CaseFile, request: dict[str, Any], llm: AgentLLMRunner) -> RiskReport:
    scoring = ScoringPlugin()
    ml = MLPlugin()
    route_score = await scoring.score_route(route_id=case_file.route_id, geometry=request.get('geometry', {'type': 'LineString', 'coordinates': []}))
    ml_calibration = ml.get_calibration(case_file.route_id)
    _ = await llm.complete_json(
        'risk',
        {
            'case_files_json': {'case_files': [case_file.model_dump()]},
            'segment_scores_json': route_score.get('segment_scores', []),
            'ml_calibration_json': ml_calibration,
            'allowed_evidence_ids': case_file.evidence_ids,
        },
        SYSTEM_PROMPT_RISK_ANALYST,
    )
    return RiskReport(route_id=case_file.route_id, risk_total=float(route_score.get('summary_risk', {}).get('total', 0.0)), findings=['Risk computed from deterministic route scoring'], evidence_ids=list(case_file.evidence_ids))


async def mitigation_agent(risk: RiskReport, llm: AgentLLMRunner) -> MitigationPlan:
    _ = await llm.complete_json('mitigation', {'route_risk_reports_json': {'route_risk_reports': [risk.model_dump()]}, 'constraints_json': {}}, SYSTEM_PROMPT_MITIGATION)
    return MitigationPlan(route_id=risk.route_id, actions=['Delay departure by 1 hour if severe alerts increase'], rationale='Conservative mitigation based on current risk profile', evidence_ids=list(risk.evidence_ids))


async def decision_agent(risk: RiskReport, mitigation: MitigationPlan, llm: AgentLLMRunner, strict: bool = False) -> Decision:
    _ = await llm.complete_json(
        'decision',
        {'route_risk_reports_json': {'route_risk_reports': [risk.model_dump()]}, 'mitigation_plans_json': {'mitigation_plans': [mitigation.model_dump()]}, 'objectives_json': {}, 'allowed_evidence_ids': risk.evidence_ids},
        SYSTEM_PROMPT_DECISION,
        strict=strict,
    )
    return Decision(route_id=risk.route_id, decision='proceed_with_mitigation', reasoning='Risk acceptable with mitigation and monitoring.', evidence_ids=list({*risk.evidence_ids, *mitigation.evidence_ids}))


async def verifier_agent(decision: Decision, allowed_evidence_ids: list[str], llm: AgentLLMRunner) -> VerificationResult:
    _ = await llm.complete_json('verifier', {'decision_json': decision.model_dump(), 'allowed_evidence_ids': allowed_evidence_ids}, SYSTEM_PROMPT_VERIFIER)
    plugin = ValidationPlugin()
    validation = plugin.validate_claims(claims_json={'claims': [{'type': 'risk', 'text': decision.reasoning, 'evidence_ids': decision.evidence_ids}]}, allowed_evidence_ids=allowed_evidence_ids)
    return VerificationResult(verified=bool(validation['ok']), issues=[item['reason'] for item in validation['invalid_claims']], invalid_claims=validation['invalid_claims'], allowed_evidence_ids=allowed_evidence_ids)


async def brief_writer_agent(decision: Decision, risk: RiskReport, mitigation: MitigationPlan, allowed_evidence_ids: list[str], llm: AgentLLMRunner) -> BriefOutput:
    _ = await llm.complete_json('brief', {'verified_decision_json': decision.model_dump(), 'route_risk_reports_json': {'route_risk_reports': [risk.model_dump()]}, 'mitigation_plans_json': {'mitigation_plans': [mitigation.model_dump()]}, 'allowed_evidence_ids': allowed_evidence_ids}, SYSTEM_PROMPT_BRIEF_WRITER)
    allowed = set(allowed_evidence_ids)
    used_ids = [eid for eid in decision.evidence_ids if eid in allowed]
    markdown = (
        '# Situation Brief\n\n'
        f'- Decision: **{decision.decision}**\n'
        f'- Risk total: **{risk.risk_total:.2f}**\n'
        f'- Mitigation: {"; ".join(mitigation.actions) if mitigation.actions else "none"}\n'
        f'- Evidence IDs: {", ".join(used_ids) if used_ids else "none"}\n'
    )
    return BriefOutput(markdown=markdown, json_output={'brief_highlights': [decision.decision], 'citations': [{'text': decision.reasoning, 'evidence_ids': used_ids}]}, evidence_ids=used_ids)
