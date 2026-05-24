from __future__ import annotations

import httpx

from frw_api.adapters.base import AdapterResult, empty_result
from frw_api.core.settings import get_settings


class EIAAdapter:
    source_key = "eia"

    async def fetch(self, *, route: str, params: dict[str, str] | None = None) -> AdapterResult:
        settings = get_settings()
        if not settings.eia_api_key:
            return empty_result(self.source_key, route, ["EIA_API_KEY is required"])
        query = {"api_key": settings.eia_api_key, **(params or {})}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"https://api.eia.gov/v2/{route.lstrip('/')}", params=query)
            response.raise_for_status()
            data = response.json()
        observations = data.get("response", {}).get("data", [])
        return AdapterResult(self.source_key, f"eia_{route}", observations, [], [], [])
