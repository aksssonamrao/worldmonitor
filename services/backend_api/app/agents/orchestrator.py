from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

from app.agents import store
from app.agents.schemas import BriefOutput, CaseFile, Decision, MitigationPlan, RiskReport, VerificationResult
from app.agents.workflow_agents import (
    AgentLLMRunner,
    brief_writer_agent,
    decision_agent,
    dispatcher_agent,
    mitigation_agent,
    retriever_agent,
    risk_analyst_agent,
    verifier_agent,
)
from app.main_state import get_db_pool

_subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)


def _emit(run_id: str, event: dict[str, Any]) -> None:
    for queue in list(_subscribers.get(run_id, [])):
        queue.put_nowait(event)


async def subscribe(run_id: str) -> AsyncIterator[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    _subscribers[run_id].append(queue)
    try:
        while True:
            item = await queue.get()
            yield item
            if item.get('final'):
                break
    finally:
        _subscribers[run_id].remove(queue)


async def _run_step(pool: Any, run_id: str, step_name: str, fn: Any) -> Any:
    step_id = await store.create_step(pool, run_id, step_name)
    _emit(run_id, {'type': 'step_started', 'step': step_name})
    try:
        output = await fn()
        payload = output.model_dump() if hasattr(output, 'model_dump') else dict(output)
        await store.finish_step(pool, step_id, 'completed', output=payload)
        await store.upsert_output(pool, run_id, step_name, payload)
        _emit(run_id, {'type': 'step_completed', 'step': step_name, 'output': payload})
        return output
    except Exception as exc:
        await store.finish_step(pool, step_id, 'failed', output={}, error=str(exc))
        _emit(run_id, {'type': 'step_failed', 'step': step_name, 'error': str(exc)})
        raise


async def execute_workflow(run_id: str, request: dict[str, Any], llm: AgentLLMRunner | None = None) -> None:
    pool = get_db_pool()
    await store.ensure_schema(pool)
    llm_runner = llm or AgentLLMRunner()
    await store.update_run_status(pool, run_id, 'running')
    _emit(run_id, {'type': 'run_started', 'run_id': run_id})
    try:
        dispatch = await _run_step(pool, run_id, 'dispatcher', lambda: dispatcher_agent(request, llm_runner))
        steps = set(dispatch.get('run_steps', []))

        case_file: CaseFile = await _run_step(pool, run_id, 'retrieve', lambda: retriever_agent(request, llm_runner)) if 'retrieve' in steps else CaseFile(route_id=str(request.get('route_id', 'unknown')))
        risk: RiskReport = await _run_step(pool, run_id, 'risk', lambda: risk_analyst_agent(case_file, request, llm_runner)) if 'risk' in steps else RiskReport(route_id=case_file.route_id)
        mitigation: MitigationPlan = await _run_step(pool, run_id, 'mitigation', lambda: mitigation_agent(risk, llm_runner)) if 'mitigation' in steps else MitigationPlan(route_id=risk.route_id)
        decision: Decision = await _run_step(pool, run_id, 'decision', lambda: decision_agent(risk, mitigation, llm_runner)) if 'decision' in steps else Decision(route_id=risk.route_id, decision='hold')

        allowed_evidence_ids = sorted(set(case_file.evidence_ids + risk.evidence_ids + mitigation.evidence_ids))
        verification: VerificationResult = await _run_step(pool, run_id, 'verify', lambda: verifier_agent(decision, allowed_evidence_ids, llm_runner)) if 'verify' in steps else VerificationResult(verified=True)

        if not verification.verified:
            decision = await _run_step(pool, run_id, 'decision_retry', lambda: decision_agent(risk, mitigation, llm_runner, strict=True))
            verification = await _run_step(pool, run_id, 'verify_retry', lambda: verifier_agent(decision, allowed_evidence_ids, llm_runner))

        if 'brief' in steps:
            brief: BriefOutput = await _run_step(pool, run_id, 'brief', lambda: brief_writer_agent(decision, risk, mitigation, allowed_evidence_ids, llm_runner))
            _ = brief

        await store.update_run_status(pool, run_id, 'succeeded')
        _emit(run_id, {'type': 'run_completed', 'run_id': run_id, 'final': True})
    except Exception as exc:
        await store.update_run_status(pool, run_id, 'failed')
        _emit(run_id, {'type': 'run_failed', 'run_id': run_id, 'error': str(exc), 'final': True})


async def run_workflow(request: dict[str, Any], llm: AgentLLMRunner | None = None) -> str:
    pool = get_db_pool()
    await store.ensure_schema(pool)
    run_id = await store.create_run(pool, request)
    asyncio.create_task(execute_workflow(run_id, request, llm=llm))
    return run_id
