from __future__ import annotations

import httpx
from selectolax.parser import HTMLParser

from frw_api.adapters.base import AdapterResult


class FederalReserveCalendarAdapter:
    source_key = "federal_reserve"
    url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

    async def fetch(self) -> AdapterResult:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.get(self.url)
            response.raise_for_status()
        parser = HTMLParser(response.text)
        releases = []
        for node in parser.css("div.panel.panel-default"):
            text = node.text(separator=" ", strip=True)
            if "FOMC" in text or "Meeting" in text:
                releases.append(
                    {
                        "release_key": "FED_FOMC_CALENDAR_DISCOVERY",
                        "title": text[:240],
                        "source_url": self.url,
                    }
                )
        return AdapterResult(self.source_key, "fed_fomc_calendar", [], releases, [], [])
