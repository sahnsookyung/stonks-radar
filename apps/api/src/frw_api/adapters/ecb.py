from __future__ import annotations

import httpx

from frw_api.adapters.base import AdapterResult
from frw_api.core.settings import get_settings
from frw_api.services.provider_limits import provider_request


class ECBAdapter:
    source_key = "ecb"

    async def fetch(self, *, flow_ref: str, key: str, params: dict[str, str] | None = None) -> AdapterResult:
        base = get_settings().ecb_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await provider_request(
                client,
                "GET",
                f"{base}/{flow_ref}/{key}",
                provider_key="ecb",
                endpoint_key="data",
                params={"format": "jsondata", **(params or {})},
                headers={"Accept": "application/vnd.sdmx.data+json;version=1.0.0"},
            )
            data = response.json()
        return AdapterResult(self.source_key, f"ecb_{flow_ref}_{key}", [data], [], [], [])
