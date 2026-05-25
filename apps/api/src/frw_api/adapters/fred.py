from __future__ import annotations

import httpx

from frw_api.adapters.base import AdapterResult, empty_result
from frw_api.core.settings import get_settings
from frw_api.services.provider_limits import provider_request


class FREDAdapter:
    source_key = "fred"

    async def fetch(self, *, series_id: str, observation_start: str | None = None) -> AdapterResult:
        settings = get_settings()
        if not settings.fred_api_key:
            return empty_result(self.source_key, series_id, ["FRED_API_KEY is required"])
        params = {
            "series_id": series_id,
            "api_key": settings.fred_api_key,
            "file_type": "json",
        }
        if observation_start:
            params["observation_start"] = observation_start
        async with httpx.AsyncClient(timeout=30) as client:
            response = await provider_request(
                client,
                "GET",
                "https://api.stlouisfed.org/fred/series/observations",
                provider_key="fred",
                endpoint_key="series_observations",
                params=params,
            )
            data = response.json()
        observations = [
            {
                "series_key": f"FRED_{series_id}",
                "date": item["date"],
                "value": item["value"],
                "realtime_start": item.get("realtime_start"),
                "realtime_end": item.get("realtime_end"),
            }
            for item in data.get("observations", [])
        ]
        return AdapterResult(self.source_key, f"fred_{series_id}", observations, [], [], [])
