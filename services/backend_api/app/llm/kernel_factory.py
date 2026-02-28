from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.llm_config import llm_settings
from app.llm.gemini_client import GeminiClient
from app.llm.sk_gemini_adapter import SKGeminiChatAdapter

if TYPE_CHECKING:  # pragma: no cover
    from semantic_kernel import Kernel


class ModelRouter:
    FLASH_SERVICE_ID = 'gemini_flash'
    PRO_SERVICE_ID = 'gemini_pro'

    def choose_service(self, step_name: str, complexity_hint: str = '') -> str:
        key = f'{step_name} {complexity_hint}'.lower()
        if any(token in key for token in ('dispatcher', 'retriever', 'retrieve', 'brief', 'summary', 'summarizer')):
            return self.FLASH_SERVICE_ID
        if any(token in key for token in ('risk', 'decision', 'verifier', 'verify', 'analysis')):
            return self.PRO_SERVICE_ID
        return self.FLASH_SERVICE_ID


def build_kernel() -> 'Kernel':
    from semantic_kernel import Kernel

    gemini_client = GeminiClient()
    flash_service = SKGeminiChatAdapter('gemini_flash', llm_settings.GEMINI_FLASH_MODEL, gemini_client)
    pro_service = SKGeminiChatAdapter('gemini_pro', llm_settings.GEMINI_PRO_MODEL, gemini_client)

    kernel = Kernel()
    kernel.add_service(flash_service)
    kernel.add_service(pro_service)
    return kernel
