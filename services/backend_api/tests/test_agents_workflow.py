import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.orchestrator import execute_workflow
from app.agents.schemas import Decision, MitigationPlan, RiskReport
from app.agents.workflow_agents import AgentLLMRunner, brief_writer_agent, verifier_agent


class DummyLLM(AgentLLMRunner):
    def __init__(self) -> None:
        pass

    async def complete_json(self, step_name: str, payload: dict, system_prompt: str, strict: bool = False) -> dict:
        _ = (step_name, payload, system_prompt, strict)
        return {}


def test_verifier_rejects_uncited_claims() -> None:
    llm = DummyLLM()
    decision = Decision(route_id='r1', decision='proceed', reasoning='high risk', evidence_ids=[])
    result = asyncio.run(verifier_agent(decision, allowed_evidence_ids=['ev-1'], llm=llm))
    assert result.verified is False
    assert 'missing_evidence_ids' in result.issues


def test_brief_writer_cannot_add_new_evidence_ids() -> None:
    llm = DummyLLM()
    decision = Decision(route_id='r1', decision='proceed', evidence_ids=['ev-1', 'ev-x'])
    risk = RiskReport(route_id='r1', risk_total=1.0, evidence_ids=['ev-1'])
    mitigation = MitigationPlan(route_id='r1', actions=['watch'], evidence_ids=['ev-1'])

    brief = asyncio.run(brief_writer_agent(decision, risk, mitigation, allowed_evidence_ids=['ev-1'], llm=llm))

    assert brief.evidence_ids == ['ev-1']
    assert brief.json_output['citations'][0]['evidence_ids'] == ['ev-1']


def test_orchestrator_records_steps_and_statuses(monkeypatch) -> None:
    import app.agents.orchestrator as orch

    events = {'run_status': [], 'steps': []}

    class FakeStore:
        async def ensure_schema(self, pool):
            return None

        async def update_run_status(self, pool, run_id, status):
            events['run_status'].append(status)

        async def create_step(self, pool, run_id, step_name):
            events['steps'].append((step_name, 'running'))
            return len(events['steps'])

        async def finish_step(self, pool, step_id, status, output=None, error=None):
            step_name = events['steps'][step_id - 1][0]
            events['steps'][step_id - 1] = (step_name, status)

        async def upsert_output(self, pool, run_id, key, value):
            return None

    monkeypatch.setattr(orch, 'store', FakeStore())
    monkeypatch.setattr(orch, 'get_db_pool', lambda: object())

    asyncio.run(orch.execute_workflow('run-1', {'route_id': 'r1'}, llm=DummyLLM()))

    assert events['run_status'][0] == 'running'
    assert events['run_status'][-1] == 'succeeded'
    step_names = [name for name, _ in events['steps']]
    assert 'dispatcher' in step_names
    assert 'retrieve' in step_names
    assert 'verify' in step_names
    assert all(status == 'completed' for _, status in events['steps'])
