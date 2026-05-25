from __future__ import annotations

import httpx

from frw_api.adapters.base import AdapterResult
from frw_api.core.settings import get_settings
from frw_api.services.provider_limits import provider_request


class BLSAdapter:
    source_key = "bls"

    async def fetch(self, *, series_ids: list[str], start_year: int, end_year: int) -> AdapterResult:
        settings = get_settings()
        payload: dict[str, object] = {
            "seriesid": series_ids,
            "startyear": str(start_year),
            "endyear": str(end_year),
        }
        if settings.bls_api_key:
            payload["registrationkey"] = settings.bls_api_key
        async with httpx.AsyncClient(timeout=30) as client:
            response = await provider_request(
                client,
                "POST",
                "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                provider_key="bls",
                endpoint_key="timeseries",
                json=payload,
            )
            data = response.json()
        observations = []
        for series in data.get("Results", {}).get("series", []):
            for item in series.get("data", []):
                observations.append(
                    {
                        "series_key": f"BLS_{series['seriesID']}",
                        "provider_observation_key": item.get("footnotes", ""),
                        "period": item.get("period"),
                        "year": item.get("year"),
                        "value": item.get("value"),
                    }
                )
        return AdapterResult(self.source_key, "bls_timeseries", observations, [], [], [])
