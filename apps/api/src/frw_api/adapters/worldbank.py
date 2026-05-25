from __future__ import annotations

import httpx

from frw_api.adapters.base import AdapterResult
from frw_api.core.settings import get_settings
from frw_api.services.provider_limits import provider_request


class WorldBankAdapter:
    source_key = "world_bank"

    async def fetch(self, *, country: str, indicator: str) -> AdapterResult:
        base = get_settings().worldbank_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await provider_request(
                client,
                "GET",
                f"{base}/country/{country}/indicator/{indicator}",
                provider_key="world_bank",
                endpoint_key="indicator",
                params={"format": "json", "per_page": "100"},
            )
            data = response.json()
        observations = data[1] if isinstance(data, list) and len(data) > 1 else []
        return AdapterResult(self.source_key, f"worldbank_{country}_{indicator}", observations, [], [], [])
