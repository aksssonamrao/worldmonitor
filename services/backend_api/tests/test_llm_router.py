import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.llm.kernel_factory import ModelRouter


def test_router_prefers_flash_for_dispatcher_retriever_and_brief() -> None:
    router = ModelRouter()
    assert router.choose_service('dispatcher') == 'gemini_flash'
    assert router.choose_service('retriever_summary', 'low') == 'gemini_flash'
    assert router.choose_service('brief writing', 'low') == 'gemini_flash'


def test_router_prefers_pro_for_risk_decision_and_verifier() -> None:
    router = ModelRouter()
    assert router.choose_service('risk analysis', 'high') == 'gemini_pro'
    assert router.choose_service('decision_step', 'medium') == 'gemini_pro'
    assert router.choose_service('verifier', 'high') == 'gemini_pro'


def test_router_defaults_to_flash_for_unknown_steps() -> None:
    router = ModelRouter()
    assert router.choose_service('misc', 'none') == 'gemini_flash'
