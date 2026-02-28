from __future__ import annotations

from typing import Any

from app.core.llm_config import llm_settings
from app.llm.gemini_client import GeminiClient

try:  # pragma: no cover
    from semantic_kernel.services.ai_service_client_base import AIServiceClientBase
except Exception:  # pragma: no cover
    AIServiceClientBase = object  # type: ignore[assignment]


class SKGeminiChatAdapter(AIServiceClientBase):
    """Minimal Semantic Kernel-compatible adapter backed by GeminiClient."""

    def __init__(self, service_id: str, default_model: str, gemini_client: GeminiClient) -> None:
        self.service_id = service_id
        self.default_model = default_model
        self._gemini_client = gemini_client
        if hasattr(super(), '__init__'):
            try:
                super().__init__(service_id=service_id)
            except TypeError:
                super().__init__()

    async def complete_chat(self, messages: list[dict[str, Any]], settings: Any | None = None) -> str:
        model = self.default_model
        system = ''
        if self.service_id == 'gemini_pro':
            temperature = 0.25
            max_tokens = 2200
            top_k = 40
        else:
            temperature = 0.2
            max_tokens = 1200
            top_k = 20
        top_p = 0.95

        if isinstance(settings, dict):
            model = str(settings.get('model', model))
            system = str(settings.get('system', system))
            temperature = float(settings.get('temperature', temperature))
            max_tokens = int(settings.get('max_tokens', max_tokens))
            top_p = float(settings.get('top_p', top_p))
            top_k = int(settings.get('top_k', top_k))

        if model == self.default_model:
            model = llm_settings.GEMINI_PRO_MODEL if self.service_id == 'gemini_pro' else llm_settings.GEMINI_FLASH_MODEL

        return await self._gemini_client.generate_text(
            model=model,
            system=system,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            top_k=top_k,
        )
