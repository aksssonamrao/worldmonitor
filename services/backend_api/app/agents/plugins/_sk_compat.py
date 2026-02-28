from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:  # pragma: no cover - exercised when semantic-kernel is installed
    from semantic_kernel.functions import kernel_function
except Exception:  # pragma: no cover - allow imports without semantic-kernel installed
    def kernel_function(*_args: Any, **_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func

        return _decorator

__all__ = ['kernel_function']
