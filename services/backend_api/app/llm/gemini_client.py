from __future__ import annotations

import json
import logging
from typing import Any

from app.core.llm_config import llm_settings

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover - handled when runtime dependency is missing
    genai = None
    types = None

logger = logging.getLogger(__name__)


class GeminiClient:
    """Async wrapper around Google GenAI SDK used by backend orchestration."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = (api_key or llm_settings.GEMINI_API_KEY).strip()
        if not self._api_key:
            raise ValueError('GEMINI_API_KEY is required to initialize GeminiClient')
        if genai is None or types is None:
            raise RuntimeError('google-genai is not installed; install dependencies to use GeminiClient')
        self._client = genai.Client(api_key=self._api_key)

    async def list_models(self) -> list[str]:
        models = []
        async for model in self._client.aio.models.list():
            name = str(getattr(model, 'name', '')).strip()
            if name:
                models.append(name)
        return models

    async def generate_text(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        top_p: float = 0.95,
        top_k: int = 20,
    ) -> str:
        contents = self._build_contents(messages=messages)
        response = await self._client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=max_tokens,
                top_p=top_p,
                top_k=top_k,
            ),
        )
        return self._extract_text(response)

    async def generate_json(
        self,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        json_schema: dict[str, Any],
        temperature: float,
        max_tokens: int,
        top_p: float = 0.95,
        top_k: int = 20,
    ) -> dict[str, Any]:
        contents = self._build_contents(messages=messages)
        response = await self._client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=temperature,
                max_output_tokens=max_tokens,
                top_p=top_p,
                top_k=top_k,
                response_mime_type='application/json',
                response_schema=json_schema,
            ),
        )
        text = self._extract_text(response)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:  # pragma: no cover
            logger.warning('Gemini JSON parse failed: %s', exc)
            raise ValueError('Gemini returned non-JSON output for generate_json') from exc

    @staticmethod
    def _build_contents(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get('role', 'user')).strip().lower() or 'user'
            text = str(message.get('content', '')).strip()
            if text:
                contents.append({'role': role, 'parts': [{'text': text}]})
        if not contents:
            contents.append({'role': 'user', 'parts': [{'text': ''}]})
        return contents

    @staticmethod
    def _extract_text(response: Any) -> str:
        text = (getattr(response, 'text', '') or '').strip()
        if text:
            return text
        for candidate in getattr(response, 'candidates', None) or []:
            content = getattr(candidate, 'content', None)
            for part in getattr(content, 'parts', None) or []:
                part_text = (getattr(part, 'text', '') or '').strip()
                if part_text:
                    return part_text
        raise ValueError('Gemini response did not include assistant text')
