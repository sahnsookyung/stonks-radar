from __future__ import annotations

import httpx

from frw_api.adapters.base import AdapterResult
from frw_api.services.provider_limits import provider_request


class GDELTDiscoveryAdapter:
    source_key = "gdelt"

    async def fetch(self, *, query: str, mode: str = "artlist") -> AdapterResult:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await provider_request(
                client,
                "GET",
                "https://api.gdeltproject.org/api/v2/doc/doc",
                provider_key="gdelt",
                endpoint_key="doc",
                params={"query": query, "mode": mode, "format": "json", "maxrecords": "25"},
            )
            data = response.json()
        documents = data.get("articles", [])
        for document in documents:
            document["discovery_only"] = True
        return AdapterResult(self.source_key, f"gdelt_{query}", [], [], documents, ["discovery_only"])
