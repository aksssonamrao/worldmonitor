from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.provider_client import ProviderClient, RateLimiter


class GoogleWeatherClient:
    def __init__(self, settings, storage):
        self.settings = settings
        self.storage = storage
        self.provider_name = 'google_weather'
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.provider_read_timeout_seconds, connect=settings.provider_connect_timeout_seconds)
        )
        self.provider_client = ProviderClient(
            max_retries=settings.provider_max_retries,
            backoff_base_seconds=settings.provider_backoff_base_seconds,
            backoff_max_seconds=settings.provider_backoff_max_seconds,
            jitter_seconds=settings.provider_backoff_jitter_seconds,
            failure_threshold=settings.provider_circuit_failure_threshold,
            cooldown_seconds=settings.provider_circuit_cooldown_seconds,
            rate_limiter=RateLimiter(settings.provider_rate_limit_per_second),
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> GoogleWeatherClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def fetch_hourly(self, lat: float, lon: float, hours: int) -> dict:
        params = {
            'key': self.settings.google_weather_api_key,
            'location.latitude': lat,
            'location.longitude': lon,
            'hours': hours,
        }
        cache_key = f'{round(lat,4)}:{round(lon,4)}:{hours}'
        status = await self.storage.get_provider_status(self.provider_name)

        async def _request() -> list[dict]:
            resp = await self.client.get(f'{self.settings.google_weather_base_url}/forecast/hours:lookup', params=params)
            if resp.status_code >= 400:
                raise RuntimeError(f'status={resp.status_code} body={resp.text[:200]}')
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

        try:
            rows = await self.provider_client.run(_request, status.get('circuit_open_until'))
            await self.storage.upsert_provider_cache(
                self.provider_name,
                cache_key,
                {
                    'rows': [
                        {**row, 'forecast_ts': row['forecast_ts'].isoformat()}
                        for row in rows
                    ]
                },
                self.settings.provider_cache_ttl_seconds,
            )
            await self.storage.mark_provider_success(self.provider_name)
            return {'rows': rows, 'degraded': False, 'fetched_at': datetime.now(timezone.utc), 'error': None}
        except Exception as exc:  # noqa: BLE001
            failures = await self.storage.mark_provider_failure(self.provider_name, str(exc), None)
            circuit_open_until = self.provider_client.maybe_open_circuit(failures)
            if circuit_open_until is not None:
                await self.storage.mark_provider_failure(self.provider_name, str(exc), circuit_open_until)
            cache = await self.storage.get_provider_cache(self.provider_name, cache_key)
            if cache:
                age_seconds = (datetime.now(timezone.utc) - cache['fetched_at']).total_seconds()
                if age_seconds <= self.settings.provider_max_stale_seconds:
                    rows = [
                        {**row, 'forecast_ts': datetime.fromisoformat(row['forecast_ts'].replace('Z', '+00:00'))}
                        for row in cache['payload_json'].get('rows', [])
                    ]
                    return {'rows': rows, 'degraded': True, 'fetched_at': cache['fetched_at'], 'error': str(exc)}
            return {'rows': [], 'degraded': True, 'fetched_at': None, 'error': str(exc)}
