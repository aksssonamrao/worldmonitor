from __future__ import annotations

import os

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - fallback for environments without optional deps installed
    class BaseSettings:
        def __init__(self, **_: object) -> None:
            for name, value in self.__class__.__dict__.items():
                if name.isupper() and not name.startswith('_'):
                    env_value = os.getenv(name)
                    if env_value is None:
                        setattr(self, name, value)
                        continue
                    current = value
                    if isinstance(current, bool):
                        setattr(self, name, env_value.lower() in {'1', 'true', 'yes', 'on'})
                    elif isinstance(current, int):
                        setattr(self, name, int(env_value))
                    elif isinstance(current, float):
                        setattr(self, name, float(env_value))
                    else:
                        setattr(self, name, env_value)

    def SettingsConfigDict(**_: object) -> dict[str, object]:
        return {}


class LLMSettings(BaseSettings):
    """LLM runtime settings for Semantic Kernel + Gemini integrations."""

    model_config = SettingsConfigDict(extra='ignore')

    GEMINI_API_KEY: str = ''
    GEMINI_FLASH_MODEL: str = 'gemini-3-flash-preview'
    GEMINI_PRO_MODEL: str = 'gemini-3.1-pro-preview'
    AGENT_DEFAULT_MODEL: str = 'flash'
    AGENT_TEMPERATURE: float = 0.2
    AGENT_MAX_TOKENS: int = 1200
    AGENT_TIMEOUT_SECONDS: int = 45
    AGENT_MAX_TOOL_CALLS: int = 6
    AGENT_MAX_EVIDENCE_PER_ROUTE: int = 30


llm_settings = LLMSettings()
