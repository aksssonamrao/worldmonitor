from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, TypeVar

T = TypeVar('T')


class RateLimiter:
    def __init__(self, rate_per_second: float):
        if rate_per_second <= 0:
            raise ValueError('rate_per_second must be > 0')
        self._interval = 1.0 / rate_per_second
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = asyncio.get_running_loop().time()
            if now < self._next:
                await asyncio.sleep(self._next - now)
            self._next = max(now, self._next) + self._interval


@dataclass
class ProviderClient:
    provider: str
    max_retries: int
    backoff_base_seconds: float
    backoff_max_seconds: float
    jitter_seconds: float
    failure_threshold: int
    cooldown_seconds: int
    rate_limiter: RateLimiter

    async def run(
        self,
        op: Callable[[], Awaitable[T]],
        *,
        consecutive_failures: int,
        circuit_open_until: datetime | None,
    ) -> T:
        now = datetime.now(timezone.utc)
        if circuit_open_until and circuit_open_until > now:
            raise RuntimeError(f'circuit_open_until={circuit_open_until.isoformat()}')

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            await self.rate_limiter.wait()
            try:
                return await op()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self.max_retries:
                    break
                delay = min(self.backoff_max_seconds, self.backoff_base_seconds * (2 ** attempt))
                delay += random.uniform(0.0, self.jitter_seconds)
                await asyncio.sleep(delay)
        assert last_error is not None
        raise last_error

    def next_circuit_open_until(self, consecutive_failures: int) -> datetime | None:
        if consecutive_failures >= self.failure_threshold:
            return datetime.now(timezone.utc) + timedelta(seconds=self.cooldown_seconds)
        return None
