from __future__ import annotations

import httpx

from frw_api.adapters.base import AdapterResult
from frw_api.core.settings import get_settings


class SECEdgarAdapter:
    source_key = "sec_edgar"

    async def fetch(self, *, cik: str) -> AdapterResult:
        settings = get_settings()
        headers = {"User-Agent": settings.sec_user_agent}
        padded = cik.zfill(10)
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            response = await client.get(f"https://data.sec.gov/submissions/CIK{padded}.json")
            response.raise_for_status()
            data = response.json()
        filings = data.get("filings", {}).get("recent", {})
        documents = []
        for idx, accession in enumerate(filings.get("accessionNumber", [])[:25]):
            form = filings.get("form", [None])[idx]
            filing_date = filings.get("filingDate", [None])[idx]
            documents.append(
                {
                    "title": f"{data.get('name', cik)} {form}",
                    "accession_number": accession,
                    "filing_date": filing_date,
                    "form": form,
                }
            )
        return AdapterResult(self.source_key, f"sec_{cik}", [], [], documents, [])
