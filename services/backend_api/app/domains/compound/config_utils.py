from __future__ import annotations

from os import getenv


def required_env(name: str, service_name: str) -> str:
    value = getenv(name, '').strip()
    if not value:
        raise RuntimeError(f'{name} is required but missing. Set it in environment/.env before starting {service_name}.')
    return value
