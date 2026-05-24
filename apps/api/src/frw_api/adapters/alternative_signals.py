from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx
from selectolax.parser import HTMLParser

from frw_api.adapters.base import AdapterResult, empty_result
from frw_api.core.settings import get_settings
from frw_api.services.market_data import SYMBOL_RE

DEFAULT_SHORT_RESEARCH_SOURCES = {
    "hindenburg": "https://hindenburgresearch.com/",
    "muddy_waters": "https://www.muddywatersresearch.com/",
    "viceroy": "https://viceroyresearch.org/",
    "spruce_point": "https://www.sprucepointcap.com/",
    "kerrisdale": "https://www.kerrisdalecap.com/",
    "culper": "https://culperresearch.com/",
    "blue_orca": "https://www.blueorcacapital.com/",
    "grizzly": "https://grizzlyreports.com/",
}

DEFAULT_TRUMP_CIKS = {
    "DJT": "0001849635",
}


class FINRAShortInterestAdapter:
    source_key = "finra_short_interest"

    async def fetch(
        self,
        *,
        symbols: list[str] | None = None,
        limit: int = 50,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> AdapterResult:
        settings = get_settings()
        if not settings.finra_api_token:
            return empty_result(self.source_key, "finra_short_interest", ["FINRA_API_TOKEN is required"])
        rows = await _get_finra_rows(
            "otcMarket",
            "consolidatedShortInterest",
            symbols=_symbols(symbols),
            limit=limit,
            transport=transport,
        )
        observations = [
            _short_interest_observation(row)
            for row in rows[:limit]
            if _row_symbol(row) and _short_interest_value(row) is not None
        ]
        documents = [
            {
                "title": "FINRA short interest dataset",
                "url": f"{settings.finra_api_base_url.rstrip('/')}/data/group/otcMarket/name/consolidatedShortInterest",
                "publisher": "FINRA",
                "row_count": len(rows),
                "symbols": symbols or [],
            }
        ]
        return AdapterResult(self.source_key, "finra_short_interest", observations, [], documents, [])


class FINRAShortVolumeAdapter:
    source_key = "finra_reg_sho_short_volume"

    async def fetch(
        self,
        *,
        symbols: list[str] | None = None,
        limit: int = 250,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> AdapterResult:
        settings = get_settings()
        if not settings.finra_api_token:
            return empty_result(self.source_key, "finra_reg_sho_short_volume", ["FINRA_API_TOKEN is required"])
        rows = await _get_finra_rows(
            "otcMarket",
            "regShoDaily",
            symbols=_symbols(symbols),
            limit=limit,
            transport=transport,
        )
        observations = [
            _short_volume_observation(row)
            for row in rows[:limit]
            if _row_symbol(row) and _short_volume_value(row) is not None
        ]
        documents = [
            {
                "title": "FINRA Reg SHO daily short sale volume dataset",
                "url": f"{settings.finra_api_base_url.rstrip('/')}/data/group/otcMarket/name/regShoDaily",
                "publisher": "FINRA",
                "row_count": len(rows),
                "symbols": symbols or [],
            }
        ]
        return AdapterResult(self.source_key, "finra_reg_sho_short_volume", observations, [], documents, [])


class PublicShortResearchAdapter:
    source_key = "public_short_research"

    async def fetch(
        self,
        *,
        source_keys: list[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> AdapterResult:
        selected = _selected_short_research_sources(source_keys)
        if not selected:
            return empty_result(self.source_key, "public_short_research_watch", ["No supported short-research sources selected"])
        documents: list[dict[str, Any]] = []
        unsupported: list[str] = []
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, transport=transport) as client:
            for source_key, url in selected.items():
                try:
                    response = await client.get(url, headers={"User-Agent": get_settings().sec_user_agent})
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    unsupported.append(f"{source_key}: {exc}")
                    continue
                documents.append(_html_document(source_key, url, response.text, risk="medium"))
        return AdapterResult(self.source_key, "public_short_research_watch", [], [], documents, unsupported if not documents else [])


class PentagonPizzaAdapter:
    source_key = "pentagon_pizza"

    async def fetch(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> AdapterResult:
        settings = get_settings()
        if not settings.pentagon_pizza_base_url:
            return empty_result(self.source_key, "pentagon_pizza", ["PENTAGON_PIZZA_BASE_URL is disabled"])
        url = settings.pentagon_pizza_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, transport=transport) as client:
            try:
                response = await client.get(url, headers={"User-Agent": settings.sec_user_agent})
                response.raise_for_status()
            except httpx.HTTPError as exc:
                return empty_result(self.source_key, "pentagon_pizza", [str(exc)])
        observed_at = datetime.now(timezone.utc).isoformat()
        document = _html_document("pentagon_pizza", url, response.text, risk="high")
        observation = {
            "series_key": "PENTAGON_PIZZA_WEAK_OSINT_STATUS",
            "provider_observation_key": _stable_key("pentagon_pizza", observed_at, document["title"]),
            "observation_timestamp": observed_at,
            "publication_timestamp": observed_at,
            "value_schema_key": "weak_osint_status_v1",
            "signal_class": "weak_osint",
            "risk_level": "high",
            "source_url": url,
            "title": document["title"],
            "status": "observed",
            "raw_retained": False,
            "parse_confidence": 0.35,
        }
        return AdapterResult(self.source_key, "pentagon_pizza_index", [observation], [], [document], [])


class TrumpFilingsAdapter:
    source_key = "trump_filings"

    async def fetch(
        self,
        *,
        ciks: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> AdapterResult:
        settings = get_settings()
        targets = ciks or DEFAULT_TRUMP_CIKS
        documents: list[dict[str, Any]] = []
        unsupported: list[str] = []
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": settings.sec_user_agent}, transport=transport) as client:
            for label, cik in targets.items():
                padded = str(cik).zfill(10)
                try:
                    response = await client.get(f"https://data.sec.gov/submissions/CIK{padded}.json")
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    unsupported.append(f"{label}: {exc}")
                    continue
                documents.extend(_sec_recent_documents(label, padded, response.json()))
        if "Donald J. Trump Revocable Trust" in settings.trump_filing_monitored_entities:
            unsupported.append("Donald J. Trump Revocable Trust requires a confirmed public CIK/manager mapping")
        return AdapterResult(self.source_key, "trump_filings_watch", [], [], documents, unsupported)


async def _get_finra_rows(
    group: str,
    dataset: str,
    *,
    symbols: list[str],
    limit: int,
    transport: httpx.AsyncBaseTransport | None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    params: dict[str, str] = {"limit": str(max(1, min(limit, 5000)))}
    if symbols:
        params["where"] = " or ".join(f"symbol='{symbol}'" for symbol in symbols)
    async with httpx.AsyncClient(timeout=20, transport=transport) as client:
        response = await client.get(
            f"{settings.finra_api_base_url.rstrip('/')}/data/group/{group}/name/{dataset}",
            params=params,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {settings.finra_api_token}",
            },
        )
        response.raise_for_status()
        payload = response.json()
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("results") or payload.get("rows") or []
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _short_interest_observation(row: dict[str, Any]) -> dict[str, Any]:
    symbol = _row_symbol(row)
    settlement_date = _row_date(row)
    value = _short_interest_value(row)
    return {
        "series_key": f"FINRA_SHORT_INTEREST_{symbol}",
        "provider_observation_key": _stable_key("short_interest", symbol, settlement_date, value),
        "date": settlement_date,
        "value": value,
        "value_schema_key": "short_interest_v1",
        "symbol": symbol,
        "source_row": row,
        "delay_classification": "reference_or_delayed",
        "parse_confidence": 0.85,
    }


def _short_volume_observation(row: dict[str, Any]) -> dict[str, Any]:
    symbol = _row_symbol(row)
    trade_date = _row_date(row)
    value = _short_volume_value(row)
    return {
        "series_key": f"FINRA_SHORT_VOLUME_{symbol}",
        "provider_observation_key": _stable_key("short_volume", symbol, trade_date, value),
        "date": trade_date,
        "value": value,
        "value_schema_key": "short_volume_v1",
        "symbol": symbol,
        "source_row": row,
        "delay_classification": "reference_or_delayed",
        "parse_confidence": 0.85,
    }


def _symbols(symbols: list[str] | None) -> list[str]:
    values = []
    for symbol in symbols or []:
        normalized = symbol.strip().upper()
        if normalized and SYMBOL_RE.match(normalized):
            values.append(normalized)
    return list(dict.fromkeys(values))


def _row_symbol(row: dict[str, Any]) -> str:
    value = row.get("symbol") or row.get("issueSymbolIdentifier") or row.get("ticker") or row.get("securitiesInformationProcessorSymbolIdentifier")
    return str(value or "").strip().upper()


def _row_date(row: dict[str, Any]) -> str:
    value = row.get("settlementDate") or row.get("tradeReportDate") or row.get("date") or row.get("businessDate")
    text = str(value or datetime.now(timezone.utc).date().isoformat())
    return text[:10]


def _row_value(row: dict[str, Any], keys: tuple[str, ...]) -> float | int | str | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _short_interest_value(row: dict[str, Any]) -> float | int | str | None:
    return _row_value(
        row,
        (
            "currentShortPositionQuantity",
            "shortInterest",
            "short_interest",
            "currentShortPositionQty",
        ),
    )


def _short_volume_value(row: dict[str, Any]) -> float | int | str | None:
    return _row_value(row, ("shortParQuantity", "shortVolume", "short_volume", "shortSaleVolume"))


def _selected_short_research_sources(source_keys: list[str] | None) -> dict[str, str]:
    if not source_keys:
        configured = [
            item.strip()
            for item in get_settings().short_research_sources.split(",")
            if item.strip()
        ]
        source_keys = configured or list(DEFAULT_SHORT_RESEARCH_SOURCES)
    return {key: DEFAULT_SHORT_RESEARCH_SOURCES[key] for key in source_keys if key in DEFAULT_SHORT_RESEARCH_SOURCES}


def _html_document(source_key: str, url: str, html: str, *, risk: str) -> dict[str, Any]:
    parser = HTMLParser(html)
    title_node = parser.css_first("title") or parser.css_first("h1")
    description_node = parser.css_first("meta[name='description']")
    description = description_node.attributes.get("content") if description_node else None
    title = title_node.text(strip=True) if title_node else source_key.replace("_", " ").title()
    return {
        "title": title[:500],
        "url": url,
        "publisher": source_key,
        "description": (description or "")[:1000],
        "discovery_only": True,
        "risk_level": risk,
        "raw_retained": False,
    }


def _sec_recent_documents(label: str, cik: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    filings = payload.get("filings", {}).get("recent", {})
    documents = []
    accessions = filings.get("accessionNumber", [])
    for idx, accession in enumerate(accessions[:25]):
        form = _list_item(filings.get("form"), idx)
        filing_date = _list_item(filings.get("filingDate"), idx)
        documents.append(
            {
                "title": f"{payload.get('name', label)} {form}",
                "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{str(accession).replace('-', '')}/",
                "publisher": "SEC EDGAR",
                "entity_label": label,
                "cik": cik,
                "accession_number": accession,
                "filing_date": filing_date,
                "form": form,
                "discovery_only": False,
                "risk_level": "low",
            }
        )
    return documents


def _list_item(values: Any, idx: int) -> Any:
    return values[idx] if isinstance(values, list) and idx < len(values) else None


def _stable_key(*parts: Any) -> str:
    payload = "|".join(str(part) for part in parts)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
