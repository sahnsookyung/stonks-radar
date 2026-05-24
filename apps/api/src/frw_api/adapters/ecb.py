from __future__ import annotations

import httpx

from frw_api.adapters.base import AdapterResult
from frw_api.core.settings import get_settings


class ECBAdapter:
    source_key = "ecb"

    async def fetch(self, *, flow_ref: str, key: str, params: dict[str, str] | None = None) -> AdapterResult:
        base = get_settings().ecb_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{base}/{flow_ref}/{key}",
                params={"format": "jsondata", **(params or {})},
                headers={"Accept": "application/vnd.sdmx.data+json;version=1.0.0"},
            )
            response.raise_for_status()
            data = response.json()
        return AdapterResult(self.source_key, f"ecb_{flow_ref}_{key}", [data], [], [], [])
