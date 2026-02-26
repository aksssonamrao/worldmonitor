from __future__ import annotations

import asyncio
from datetime import datetime

import httpx


class TokenBucket:
    def __init__(self, rate: float):
        if rate <= 0:
            raise ValueError(f"TokenBucket rate must be positive, got {rate!r}")
        self._interval = 1.0 / rate
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def consume(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if now < self._next:
                await asyncio.sleep(self._next - now)
            self._next = max(now, self._next) + self._interval


class GoogleWeatherClient:
    def __init__(self, base_url: str, api_key: str, max_qps: float = 5.0):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.bucket = TokenBucket(max_qps)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0))

    async def fetch_hourly(self, lat: float, lon: float, hours: int) -> list[dict]:
        params = {
            'key': self.api_key,
            'location.latitude': lat,
            'location.longitude': lon,
            'hours': hours,
        }
        attempt = 0
        while True:
            attempt += 1
            await self.bucket.consume()
            try:
                resp = await self.client.get(f'{self.base_url}/forecast/hours:lookup', params=params)
            except httpx.HTTPError as exc:
                if attempt <= 3:
                    await asyncio.sleep(2 ** (attempt - 1))
                    continue
                raise RuntimeError(f'google weather request failed for ({lat},{lon}): {exc!s}') from exc

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt <= 3:
                    await asyncio.sleep(2 ** (attempt - 1))
                    continue
                raise RuntimeError(
                    f'google weather exhausted retries for ({lat},{lon}), status={resp.status_code}, body={resp.text[:200]}'
                )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f'google weather error for ({lat},{lon}), status={resp.status_code}, body={resp.text[:200]}'
                )

            payload = resp.json()
            records = payload.get('hours', [])
            return [
                {
                    'forecast_ts': datetime.fromisoformat(r['interval']['startTime'].replace('Z', '+00:00')),
                    'wind_kph': float(r.get('wind', {}).get('speed', {}).get('value', 0.0)),
                    'precip_mm_hr': float(r.get('precipitation', {}).get('qpf', {}).get('value', 0.0)),
                    'temp_c': float(r.get('temperature', {}).get('degrees', 0.0)),
                    'humidity': float(r.get('relativeHumidity', {}).get('value', 0.0)),
                }
                for r in records
            ]
