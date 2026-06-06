from __future__ import annotations

import csv
import json
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from frw_api.core.settings import get_settings

INDEX_SCHEMA_VERSION = 1
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
NASDAQ_OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
SEC_COMPANY_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
INDEX_LAST_UPDATED_AT = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
INSTRUMENT_INDEX_HARD_EXPIRES_SECONDS = 7 * 86400
_SEARCH_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_INDEX: InstrumentIndex | None = None
_DYNAMIC_INSTRUMENTS: tuple[Instrument, ...] = ()
_DYNAMIC_INDEX_PATH: str | None = None
_DYNAMIC_INDEX_MTIME: int | None = None
_INDEX_SOURCE_STATUSES: list[dict[str, Any]] = [
    {
        "source": "local_static_seed",
        "status": "loaded",
        "generated_at": INDEX_LAST_UPDATED_AT,
        "instrument_count": 0,
    }
]


@dataclass(frozen=True)
class InstrumentIdentifier:
    type: str
    value: str


@dataclass(frozen=True)
class InstrumentListing:
    listing_id: str
    symbol: str
    exchange: str
    country: str
    currency: str
    local_code: str | None = None
    is_primary: bool = True
    is_active: bool = True


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    symbol: str
    name: str
    exchange: str
    country: str
    currency: str
    asset_class: str
    instrument_type: str
    sector: str
    quality_level: str = "COMPLETE"
    quality_message: str = "Complete data"
    is_active: bool = True
    leverage_flag: bool = False
    inverse_flag: bool = False
    aliases: tuple[str, ...] = ()
    identifiers: tuple[InstrumentIdentifier, ...] = ()
    listings: tuple[InstrumentListing, ...] = ()
    price_as_of: str = INDEX_LAST_UPDATED_AT[:10]
    theme_tags: tuple[str, ...] = ()
    source_providers: tuple[str, ...] = ("local_static_seed",)


@dataclass(frozen=True)
class SearchToken:
    value: str
    kind: str
    normalized: str
    compact: str


@dataclass(frozen=True)
class SearchEntry:
    instrument: Instrument
    listing: InstrumentListing
    tokens: tuple[SearchToken, ...]
    is_primary_listing: bool
    is_active: bool


@dataclass(frozen=True)
class InstrumentIndex:
    entries: tuple[SearchEntry, ...]
    by_instrument_id: dict[str, Instrument]
    by_listing_id: dict[str, tuple[Instrument, InstrumentListing]]
    by_reference: dict[str, tuple[Instrument, InstrumentListing]]


def instrument_catalog() -> tuple[Instrument, ...]:
    return (
        _instrument(
            "AAPL",
            "Apple Inc.",
            "NASDAQ",
            "US",
            "USD",
            "Equity",
            "stock",
            "Information Technology",
            aliases=("Apple", "Apple Computer"),
            identifiers=(InstrumentIdentifier("ISIN", "US0378331005"), InstrumentIdentifier("FIGI", "BBG000B9XRY4")),
        ),
        _instrument(
            "MSFT",
            "Microsoft Corp.",
            "NASDAQ",
            "US",
            "USD",
            "Equity",
            "stock",
            "Information Technology",
            aliases=("Microsoft",),
            identifiers=(InstrumentIdentifier("ISIN", "US5949181045"), InstrumentIdentifier("FIGI", "BBG000BPH459")),
        ),
        _instrument(
            "NVDA",
            "NVIDIA Corporation",
            "NASDAQ",
            "US",
            "USD",
            "Equity",
            "stock",
            "Information Technology",
            aliases=("Nvidia", "NVIDIA Corp"),
            identifiers=(InstrumentIdentifier("ISIN", "US67066G1040"),),
        ),
        _instrument(
            "TSLA",
            "Tesla, Inc.",
            "NASDAQ",
            "US",
            "USD",
            "Equity",
            "stock",
            "Consumer Discretionary",
            aliases=("Tesla",),
            identifiers=(InstrumentIdentifier("ISIN", "US88160R1014"),),
        ),
        Instrument(
            instrument_id="005930.KS",
            symbol="005930.KS",
            name="Samsung Electronics Co., Ltd.",
            exchange="KRX",
            country="Korea",
            currency="KRW",
            asset_class="Equity",
            instrument_type="stock",
            sector="Information Technology",
            quality_level="PARTIAL",
            quality_message="Partial data: sector classification confirmed; holdings look-through not applicable.",
            aliases=("Samsung Electronics", "삼성전자"),
            identifiers=(InstrumentIdentifier("ISIN", "KR7005930003"), InstrumentIdentifier("LOCAL_CODE", "005930")),
            listings=(
                InstrumentListing(
                    listing_id="KRX:005930",
                    symbol="005930.KS",
                    exchange="KRX",
                    country="Korea",
                    currency="KRW",
                    local_code="005930",
                ),
            ),
        ),
        _instrument(
            "VXUS",
            "Vanguard Total International Stock ETF",
            "NASDAQ",
            "Global ex-US",
            "USD",
            "Equity",
            "etf",
            "Multi-sector",
            aliases=("Vanguard VXUS", "Total International Stock ETF"),
            identifiers=(InstrumentIdentifier("FIGI", "BBG001SHTTZ6"),),
            quality_level="PARTIAL",
            quality_message="Partial data: latest fund holdings may be delayed.",
        ),
        _instrument(
            "TLT",
            "iShares 20+ Year Treasury Bond ETF",
            "NASDAQ",
            "US",
            "USD",
            "Fixed Income",
            "etf",
            "Government bonds",
            aliases=("20 Year Treasury Bond ETF",),
        ),
        _instrument(
            "SGOV",
            "iShares 0-3 Month Treasury Bond ETF",
            "NYSE",
            "US",
            "USD",
            "Cash & Cash Equivalents",
            "etf",
            "Government bonds",
            aliases=("T-Bill ETF", "Short Treasury ETF"),
        ),
        _instrument(
            "QQQ",
            "Invesco QQQ Trust",
            "NASDAQ",
            "US",
            "USD",
            "Equity",
            "etf",
            "Information Technology",
            aliases=("Nasdaq 100 ETF",),
        ),
        _instrument(
            "BTC",
            "Bitcoin",
            "Crypto",
            "Global",
            "USD",
            "Crypto / Digital Assets",
            "crypto",
            "Crypto",
            aliases=("Bitcoin BTC",),
            quality_level="PROXY",
            quality_message="Proxy used: crypto reference price classification is approximate.",
        ),
        _instrument(
            "TQQQ",
            "ProShares UltraPro QQQ",
            "NASDAQ",
            "US",
            "USD",
            "Derivatives / Leveraged Products",
            "leveraged",
            "Leveraged ETF",
            aliases=("3x QQQ ETF",),
            leverage_flag=True,
            quality_level="PARTIAL",
            quality_message="Partial data. This is a leveraged or inverse product. It may behave very differently from the underlying asset, especially over longer periods.",
        ),
        _instrument(
            "AAPL.WS",
            "Apple warrant",
            "NASDAQ",
            "US",
            "USD",
            "Derivatives / Leveraged Products",
            "manual",
            "Warrant",
            aliases=("Apple warrant",),
            quality_level="UNAVAILABLE",
            quality_message="Data unavailable: advanced instrument requires manual verification.",
        ),
    )


def instrument_universe() -> tuple[Instrument, ...]:
    static_instruments = instrument_catalog()
    dynamic_instruments = _load_dynamic_instruments()
    combined: dict[str, Instrument] = {}
    for instrument in (*static_instruments, *dynamic_instruments):
        normalized = normalize_symbol(instrument.instrument_id)
        if not normalized:
            continue
        combined[normalized] = _merge_instruments(combined[normalized], instrument) if normalized in combined else instrument
    return tuple(combined.values())


def _load_dynamic_instruments(*, force: bool = False) -> tuple[Instrument, ...]:
    global INDEX_LAST_UPDATED_AT, _DYNAMIC_INDEX_MTIME, _DYNAMIC_INDEX_PATH, _DYNAMIC_INSTRUMENTS, _INDEX_SOURCE_STATUSES
    settings = get_settings()
    path = str(settings.instrument_universe_cache_path)
    if not path:
        return ()
    artifact_path = Path(path)
    try:
        stat = artifact_path.stat()
    except FileNotFoundError:
        return _DYNAMIC_INSTRUMENTS if _DYNAMIC_INDEX_PATH == path else ()
    except OSError as exc:
        _INDEX_SOURCE_STATUSES = [{"source": "instrument_universe_artifact", "status": "unreadable", "error": str(exc)}]
        return _DYNAMIC_INSTRUMENTS
    artifact_mtime = stat.st_mtime_ns
    if not force and _DYNAMIC_INDEX_PATH == path and _DYNAMIC_INDEX_MTIME == artifact_mtime:
        return _DYNAMIC_INSTRUMENTS
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        if int(payload.get("schema_version") or 0) != INDEX_SCHEMA_VERSION:
            raise ValueError("unsupported instrument universe schema")
        instruments = tuple(
            instrument
            for row in payload.get("instruments", [])
            if isinstance(row, dict)
            for instrument in [_instrument_from_payload(row)]
            if instrument is not None
        )
        _DYNAMIC_INSTRUMENTS = instruments
        _DYNAMIC_INDEX_PATH = path
        _DYNAMIC_INDEX_MTIME = artifact_mtime
        generated_at = str(payload.get("generated_at") or INDEX_LAST_UPDATED_AT)
        INDEX_LAST_UPDATED_AT = generated_at
        _INDEX_SOURCE_STATUSES = list(payload.get("sources") or [])
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        _INDEX_SOURCE_STATUSES = [{"source": "instrument_universe_artifact", "status": "invalid", "error": str(exc)}]
    return _DYNAMIC_INSTRUMENTS


def _instrument_from_payload(row: dict[str, Any]) -> Instrument | None:
    try:
        identifiers = tuple(InstrumentIdentifier(**identifier) for identifier in row.get("identifiers", []) if isinstance(identifier, dict))
        listings = tuple(InstrumentListing(**listing) for listing in row.get("listings", []) if isinstance(listing, dict))
        return Instrument(
            instrument_id=str(row["instrument_id"]),
            symbol=str(row["symbol"]),
            name=str(row["name"]),
            exchange=str(row["exchange"]),
            country=str(row["country"]),
            currency=str(row["currency"]),
            asset_class=str(row["asset_class"]),
            instrument_type=str(row["instrument_type"]),
            sector=str(row.get("sector") or "Unclassified"),
            quality_level=str(row.get("quality_level") or "PARTIAL"),
            quality_message=str(row.get("quality_message") or "Source-backed listing metadata; classification may be incomplete."),
            is_active=bool(row.get("is_active", True)),
            leverage_flag=bool(row.get("leverage_flag", False)),
            inverse_flag=bool(row.get("inverse_flag", False)),
            aliases=tuple(str(alias) for alias in row.get("aliases", []) if alias),
            identifiers=identifiers,
            listings=listings,
            price_as_of=str(row.get("price_as_of") or INDEX_LAST_UPDATED_AT[:10]),
            theme_tags=tuple(str(tag) for tag in row.get("theme_tags", []) if tag),
            source_providers=tuple(str(provider) for provider in row.get("source_providers", ["instrument_universe_artifact"]) if provider),
        )
    except (KeyError, TypeError, ValueError):
        return None


def search_instruments(
    query: str,
    *,
    limit: int = 10,
    include_advanced: bool = False,
    include_inactive: bool = False,
    country: str | None = None,
    exchange: str | None = None,
    asset_class: str | None = None,
    instrument_type: str | None = None,
    context: str = "HOLDING_ENTRY",
) -> dict[str, Any]:
    settings = get_settings()
    normalized = normalize_search_query(query)
    if not normalized:
        return _response(query, [], [])
    max_len = settings.instrument_autocomplete_max_query_length
    if len(query) > max_len:
        raise ValueError(f"query exceeds maximum length of {max_len}")
    min_length = 1 if _is_likely_symbol_query(normalized) else 2
    if len(normalized) < min_length:
        return _response(query, [], [f"{min_length}-character minimum for this query type"])
    bounded_limit = max(1, min(limit, settings.instrument_autocomplete_max_results))
    cache_key = "|".join(
        [
            normalized,
            str(bounded_limit),
            str(include_advanced),
            str(include_inactive),
            (country or "").upper(),
            (exchange or "").upper(),
            (asset_class or "").upper(),
            (instrument_type or "").upper(),
            context,
        ]
    )
    cached = _SEARCH_CACHE.get(cache_key)
    now = time.time()
    if cached and cached[0] > now:
        return _response(query, cached[1][:bounded_limit], [], cache="hit")
    if cached:
        _SEARCH_CACHE.pop(cache_key, None)

    index = _instrument_index()
    query_symbol = normalize_symbol(normalized)
    results: dict[str, dict[str, Any]] = {}
    for entry in index.entries:
        instrument = entry.instrument
        listing = entry.listing
        if country and listing.country.upper() != country.upper():
            continue
        if exchange and listing.exchange.upper() != exchange.upper():
            continue
        if asset_class and instrument.asset_class.upper() != asset_class.upper():
            continue
        if instrument_type and instrument.instrument_type.upper() != instrument_type.upper():
            continue
        if not entry.is_active and not include_inactive:
            continue
        advanced = _is_advanced(instrument)
        exact_symbol = normalize_symbol(listing.symbol) == query_symbol or normalize_symbol(instrument.symbol) == query_symbol
        exact_name = normalize_search_query(instrument.name) == normalized
        if advanced and not include_advanced and not exact_symbol and not exact_name:
            continue

        score = 0
        matched_on: list[str] = []
        for token in entry.tokens:
            token_score, matched = _score_token(token, normalized, query_symbol)
            score += token_score
            if matched:
                matched_on.append(matched)
        if score <= 0:
            continue
        if entry.is_active:
            score += 150
        if entry.is_primary_listing:
            score += 100
        if listing.currency == "USD":
            score += 20
        if context == "BUILDER" and instrument.instrument_type in {"etf", "stock"}:
            score += 60
        if context == "TAX_LOT" and exact_symbol:
            score += 60
        if instrument.quality_level == "STALE":
            score -= 100
        if instrument.quality_level == "UNAVAILABLE":
            score -= 200

        result = _result_for(entry, score, sorted(set(matched_on)))
        previous = results.get(result["listingId"])
        if not previous or float(result["score"]) > float(previous["score"]):
            results[result["listingId"]] = result

    sorted_results = sorted(results.values(), key=lambda row: (-float(row["score"]), str(row["displaySymbol"])))
    limited_results = sorted_results[:bounded_limit]
    _set_cache(cache_key, limited_results)
    return _response(query, limited_results, [], cache="miss")


def resolve_instrument(
    *,
    symbol: str,
    name: str | None = None,
    exchange: str | None = None,
    currency: str | None = None,
    isin: str | None = None,
    context: str = "CSV_IMPORT",
) -> dict[str, Any]:
    query = isin or symbol or name or ""
    response = search_instruments(
        query,
        limit=10,
        include_advanced=True,
        include_inactive=False,
        exchange=exchange,
        context=context,
    )
    results = response["results"]
    if currency:
        currency_matches = [row for row in results if str(row["currency"]).upper() == currency.upper()]
        if currency_matches:
            results = currency_matches
    if not results:
        return {"status": "NO_MATCH", "confidence": "LOW", "matches": []}
    exact = [
        row
        for row in results
        if normalize_symbol(row["displaySymbol"]) == normalize_symbol(symbol)
        or (isin and "IDENTIFIER_EXACT" in row.get("matchedOn", []))
    ]
    matches = exact or results
    status = "MATCHED" if len(matches) == 1 else "MULTIPLE_MATCHES"
    confidence = "HIGH" if exact or len(matches) == 1 else "MEDIUM"
    return {"status": status, "confidence": confidence, "matches": matches}


def instrument_detail(instrument_id: str, listing_id: str | None = None) -> dict[str, Any] | None:
    normalized = normalize_symbol(instrument_id)
    index = _instrument_index()
    instrument = index.by_instrument_id.get(normalized)
    if not instrument:
        referenced = index.by_reference.get(normalized)
        instrument = referenced[0] if referenced else None
    if not instrument:
        return None
    listings = [_listing_payload(instrument, listing) for listing in _listing_set(instrument)]
    if listing_id:
        listings = [listing for listing in listings if normalize_symbol(listing["listingId"]) == normalize_symbol(listing_id)]
    return {
        "instrumentId": instrument.instrument_id,
        "symbol": instrument.symbol,
        "name": instrument.name,
        "assetClass": instrument.asset_class,
        "instrumentType": instrument.instrument_type,
        "country": instrument.country,
        "currency": instrument.currency,
        "sector": instrument.sector,
        "themeTags": list(instrument.theme_tags),
        "isActive": instrument.is_active,
        "isAdvancedInstrument": _is_advanced(instrument),
        "dataQualityLevel": instrument.quality_level,
        "dataQualityMessage": instrument.quality_message,
        "aliases": list(instrument.aliases),
        "identifiers": [identifier.__dict__ for identifier in instrument.identifiers],
        "listings": listings,
        "dataQualityIssues": _data_quality_issues(instrument),
    }


def refresh_instrument_index(*, source: str = "LOCAL_STATIC_INDEX", mode: str = "INCREMENTAL") -> dict[str, Any]:
    global _DYNAMIC_INSTRUMENTS, _INDEX, _INDEX_SOURCE_STATUSES
    settings = get_settings()
    source_key = source.strip().lower()
    statuses: list[dict[str, Any]] = []
    fetched_instruments: tuple[Instrument, ...] = ()
    provider_refresh_failed = False
    if source_key not in {"local_static_index", "static", "local"}:
        source_names = settings.instrument_universe_source_list
        if source_key not in {"configured_free_sources", "free_sources", "all"}:
            source_names = [source_key]
        fetched_instruments, statuses = _fetch_dynamic_instrument_universe(source_names, settings=settings)
        if fetched_instruments:
            _DYNAMIC_INSTRUMENTS = fetched_instruments
            _write_dynamic_instrument_artifact(fetched_instruments, statuses, settings=settings)
        elif statuses:
            _INDEX_SOURCE_STATUSES = statuses
            provider_refresh_failed = True
    _INDEX = None
    _SEARCH_CACHE.clear()
    _load_dynamic_instruments(force=True)
    if provider_refresh_failed:
        fallback_status = {
            "source": "instrument_universe_artifact",
            "status": "stale_fallback" if _DYNAMIC_INSTRUMENTS else "unavailable",
            "instrument_count": len(_DYNAMIC_INSTRUMENTS),
            "generated_at": INDEX_LAST_UPDATED_AT,
        }
        _INDEX_SOURCE_STATUSES = [*statuses, fallback_status]
    index = _instrument_index()
    return {
        "status": "refreshed",
        "source": source,
        "mode": mode,
        "instrument_count": len(index.by_instrument_id),
        "listing_count": len(index.by_listing_id),
        "cache_entries": len(_SEARCH_CACHE),
        "instrumentIndexLastUpdatedAt": INDEX_LAST_UPDATED_AT,
        "provider_statuses": _INDEX_SOURCE_STATUSES,
    }


def _fetch_dynamic_instrument_universe(source_names: list[str], *, settings) -> tuple[tuple[Instrument, ...], list[dict[str, Any]]]:
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    statuses: list[dict[str, Any]] = []
    instruments: list[Instrument] = []
    headers = {
        "User-Agent": settings.sec_user_agent,
        "Accept": "text/plain,application/json;q=0.9,*/*;q=0.1",
    }
    timeout = httpx.Timeout(settings.instrument_universe_fetch_timeout_seconds)
    limits = httpx.Limits(max_connections=2, max_keepalive_connections=1)
    with httpx.Client(timeout=timeout, limits=limits, headers=headers, follow_redirects=True, trust_env=False) as client:
        if "nasdaq_trader" in source_names:
            source_instruments, source_statuses = _fetch_nasdaq_trader_symbols(client, generated_at=generated_at)
            instruments.extend(source_instruments)
            statuses.extend(source_statuses)
        if "sec_company_tickers" in source_names:
            source_instruments, source_status = _fetch_sec_company_tickers(client, generated_at=generated_at)
            instruments.extend(source_instruments)
            statuses.append(source_status)
    deduped: dict[str, Instrument] = {}
    for instrument in instruments:
        key = normalize_symbol(instrument.instrument_id)
        if not key:
            continue
        deduped[key] = _merge_instruments(deduped[key], instrument) if key in deduped else instrument
    limited = tuple(list(deduped.values())[: settings.instrument_universe_max_dynamic_instruments])
    if len(deduped) > len(limited):
        statuses.append(
            {
                "source": "instrument_universe_limit",
                "status": "truncated",
                "instrument_count": len(limited),
                "available_count": len(deduped),
            }
        )
    return limited, statuses


def _fetch_nasdaq_trader_symbols(client: httpx.Client, *, generated_at: str) -> tuple[list[Instrument], list[dict[str, Any]]]:
    instruments: list[Instrument] = []
    statuses: list[dict[str, Any]] = []
    for source_name, url, parser in [
        ("nasdaq_trader:nasdaqlisted", NASDAQ_LISTED_URL, _parse_nasdaq_listed),
        ("nasdaq_trader:otherlisted", NASDAQ_OTHER_LISTED_URL, _parse_nasdaq_other_listed),
    ]:
        try:
            response = client.get(url)
            response.raise_for_status()
            parsed, file_creation_time = parser(response.text, generated_at=generated_at)
            instruments.extend(parsed)
            statuses.append(
                {
                    "source": source_name,
                    "status": "ok",
                    "url": url,
                    "instrument_count": len(parsed),
                    "generated_at": generated_at,
                    "file_creation_time": file_creation_time,
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                }
            )
        except (httpx.HTTPError, ValueError, csv.Error) as exc:
            statuses.append({"source": source_name, "status": "error", "url": url, "error": str(exc), "generated_at": generated_at})
    return instruments, statuses


def _fetch_sec_company_tickers(client: httpx.Client, *, generated_at: str) -> tuple[list[Instrument], dict[str, Any]]:
    try:
        response = client.get(SEC_COMPANY_TICKERS_EXCHANGE_URL, headers={"Accept": "application/json"})
        response.raise_for_status()
        instruments = _parse_sec_company_tickers_exchange(response.json(), generated_at=generated_at)
        return instruments, {
            "source": "sec_company_tickers",
            "status": "ok",
            "url": SEC_COMPANY_TICKERS_EXCHANGE_URL,
            "instrument_count": len(instruments),
            "generated_at": generated_at,
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
        }
    except (httpx.HTTPError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return [], {"source": "sec_company_tickers", "status": "error", "url": SEC_COMPANY_TICKERS_EXCHANGE_URL, "error": str(exc), "generated_at": generated_at}


def _parse_nasdaq_listed(text: str, *, generated_at: str) -> tuple[list[Instrument], str | None]:
    lines, file_creation_time = _symbol_directory_lines(text)
    reader = csv.DictReader(lines, delimiter="|")
    instruments: list[Instrument] = []
    for row in reader:
        if row.get("Test Issue") == "Y":
            continue
        symbol = (row.get("Symbol") or "").strip()
        name = (row.get("Security Name") or "").strip()
        if not symbol or not name:
            continue
        instruments.append(
            _source_instrument(
                symbol=symbol,
                name=name,
                exchange="NASDAQ",
                etf=row.get("ETF") == "Y",
                generated_at=generated_at,
                source_provider="nasdaq_trader",
            )
        )
    return instruments, file_creation_time


def _parse_nasdaq_other_listed(text: str, *, generated_at: str) -> tuple[list[Instrument], str | None]:
    lines, file_creation_time = _symbol_directory_lines(text)
    reader = csv.DictReader(lines, delimiter="|")
    instruments: list[Instrument] = []
    for row in reader:
        if row.get("Test Issue") == "Y":
            continue
        symbol = (row.get("ACT Symbol") or row.get("NASDAQ Symbol") or "").strip()
        name = (row.get("Security Name") or "").strip()
        exchange = _exchange_name(row.get("Exchange") or "")
        if not symbol or not name:
            continue
        instruments.append(
            _source_instrument(
                symbol=symbol,
                name=name,
                exchange=exchange,
                etf=row.get("ETF") == "Y",
                generated_at=generated_at,
                source_provider="nasdaq_trader",
            )
        )
    return instruments, file_creation_time


def _parse_sec_company_tickers_exchange(payload: Any, *, generated_at: str) -> list[Instrument]:
    fields = payload.get("fields") if isinstance(payload, dict) else None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(fields, list) or not isinstance(data, list):
        return []
    rows: list[Instrument] = []
    for raw in data:
        if not isinstance(raw, list):
            continue
        row = dict(zip(fields, raw, strict=False))
        ticker = str(row.get("ticker") or "").strip()
        name = str(row.get("name") or "").strip()
        exchange = str(row.get("exchange") or "").strip() or "SEC"
        cik = str(row.get("cik") or "").strip()
        if not ticker or not name:
            continue
        rows.append(
            _source_instrument(
                symbol=ticker,
                name=name,
                exchange=exchange,
                etf=False,
                generated_at=generated_at,
                identifiers=(InstrumentIdentifier("CIK", cik.zfill(10)),) if cik else (),
                quality_message="SEC company ticker mapping; listing classification may be incomplete.",
                source_provider="sec_company_tickers",
            )
        )
    return rows


def _symbol_directory_lines(text: str) -> tuple[list[str], str | None]:
    lines: list[str] = []
    file_creation_time: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("File Creation Time:"):
            file_creation_time = stripped.split("|", 1)[0].replace("File Creation Time:", "").strip()
            continue
        lines.append(stripped)
    return lines, file_creation_time


def _source_instrument(
    *,
    symbol: str,
    name: str,
    exchange: str,
    etf: bool,
    generated_at: str,
    identifiers: tuple[InstrumentIdentifier, ...] = (),
    quality_message: str = "Source-backed listing metadata; sector and price fields require separate market data.",
    source_provider: str = "instrument_universe",
) -> Instrument:
    symbol = symbol.upper()
    instrument_type = "etf" if etf else "stock"
    listing = InstrumentListing(
        listing_id=f"{exchange}:{symbol}",
        symbol=symbol,
        exchange=exchange,
        country="US",
        currency="USD",
        local_code=symbol,
    )
    return Instrument(
        instrument_id=symbol,
        symbol=symbol,
        name=name,
        exchange=exchange,
        country="US",
        currency="USD",
        asset_class="Equity",
        instrument_type=instrument_type,
        sector="Unclassified",
        quality_level="PARTIAL",
        quality_message=quality_message,
        aliases=(name,),
        identifiers=identifiers,
        listings=(listing,),
        price_as_of=generated_at[:10],
        source_providers=(source_provider,),
    )


def _exchange_name(code: str) -> str:
    return {
        "A": "NYSE American",
        "N": "NYSE",
        "P": "NYSE Arca",
        "Z": "Cboe BZX",
        "V": "IEX",
    }.get(code.strip().upper(), code.strip().upper() or "US")


def _merge_instruments(left: Instrument, right: Instrument) -> Instrument:
    identifiers: dict[str, InstrumentIdentifier] = {}
    for identifier in (*left.identifiers, *right.identifiers):
        key = f"{identifier.type.upper()}:{normalize_symbol(identifier.value)}"
        if key and key not in identifiers:
            identifiers[key] = identifier

    listings: dict[str, InstrumentListing] = {}
    for listing in (*left.listings, *right.listings):
        key = normalize_symbol(listing.listing_id)
        if key and key not in listings:
            listings[key] = listing

    aliases = tuple(dict.fromkeys(alias for alias in (*left.aliases, *right.aliases, right.name) if alias))
    source_providers = tuple(dict.fromkeys(provider for provider in (*left.source_providers, *right.source_providers) if provider))
    sector = right.sector if left.sector == "Unclassified" and right.sector != "Unclassified" else left.sector
    theme_tags = tuple(dict.fromkeys(tag for tag in (*left.theme_tags, *right.theme_tags) if tag))
    return replace(
        left,
        identifiers=tuple(identifiers.values()),
        listings=tuple(listings.values()) or left.listings,
        aliases=aliases,
        source_providers=source_providers,
        sector=sector,
        theme_tags=theme_tags,
    )


def _write_dynamic_instrument_artifact(instruments: tuple[Instrument, ...], statuses: list[dict[str, Any]], *, settings) -> None:
    global INDEX_LAST_UPDATED_AT, _INDEX_SOURCE_STATUSES
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": generated_at,
        "sources": statuses,
        "instruments": [asdict(instrument) for instrument in instruments],
    }
    target = Path(settings.instrument_universe_cache_path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(f"{target.suffix}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(target)
        INDEX_LAST_UPDATED_AT = generated_at
        _INDEX_SOURCE_STATUSES = statuses
    except OSError as exc:
        _INDEX_SOURCE_STATUSES = [
            *statuses,
            {
                "source": "instrument_universe_artifact",
                "status": "write_failed",
                "path": str(target),
                "error": str(exc),
                "generated_at": generated_at,
            },
        ]


def normalize_search_query(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = "".join(ch for ch in normalized if ch.isprintable())
    normalized = normalized.strip().casefold()
    normalized = re.sub(r"[^\w.\-/\s가-힣]", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_symbol(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9]", "", unicodedata.normalize("NFKC", value).upper())


def _instrument(
    symbol: str,
    name: str,
    exchange: str,
    country: str,
    currency: str,
    asset_class: str,
    instrument_type: str,
    sector: str,
    *,
    aliases: tuple[str, ...] = (),
    identifiers: tuple[InstrumentIdentifier, ...] = (),
    quality_level: str = "COMPLETE",
    quality_message: str = "Complete data",
    leverage_flag: bool = False,
    inverse_flag: bool = False,
) -> Instrument:
    return Instrument(
        instrument_id=symbol,
        symbol=symbol,
        name=name,
        exchange=exchange,
        country=country,
        currency=currency,
        asset_class=asset_class,
        instrument_type=instrument_type,
        sector=sector,
        quality_level=quality_level,
        quality_message=quality_message,
        leverage_flag=leverage_flag,
        inverse_flag=inverse_flag,
        aliases=aliases,
        identifiers=identifiers,
        listings=(
            InstrumentListing(
                listing_id=f"{exchange}:{symbol}",
                symbol=symbol,
                exchange=exchange,
                country=country,
                currency=currency,
                local_code=symbol,
            ),
        ),
    )


def _instrument_index() -> InstrumentIndex:
    global _INDEX
    if _INDEX is not None:
        before = (_DYNAMIC_INDEX_PATH, _DYNAMIC_INDEX_MTIME)
        _load_dynamic_instruments()
        after = (_DYNAMIC_INDEX_PATH, _DYNAMIC_INDEX_MTIME)
        if before == after:
            return _INDEX
        _INDEX = None
        _SEARCH_CACHE.clear()
    entries: list[SearchEntry] = []
    by_instrument_id: dict[str, Instrument] = {}
    by_listing_id: dict[str, tuple[Instrument, InstrumentListing]] = {}
    by_reference: dict[str, tuple[Instrument, InstrumentListing]] = {}
    for instrument in instrument_universe():
        by_instrument_id[normalize_symbol(instrument.instrument_id)] = instrument
        for listing in _listing_set(instrument):
            pair = (instrument, listing)
            for ref in [instrument.instrument_id, instrument.symbol, instrument.name, listing.listing_id, listing.symbol, listing.local_code]:
                _add_reference(by_reference, ref, pair)
            for alias in instrument.aliases:
                _add_reference(by_reference, alias, pair)
            for identifier in instrument.identifiers:
                _add_reference(by_reference, identifier.value, pair)
            by_listing_id[normalize_symbol(listing.listing_id)] = pair
            tokens = tuple(
                token
                for token in [
                    _token(listing.symbol, "SYMBOL"),
                    _token(listing.local_code, "LOCAL_CODE"),
                    _token(instrument.name, "NAME"),
                    *[_token(alias, "ALIAS") for alias in instrument.aliases],
                    *[_token(identifier.value, identifier.type) for identifier in instrument.identifiers],
                ]
                if token is not None
            )
            entries.append(
                SearchEntry(
                    instrument=instrument,
                    listing=listing,
                    tokens=tokens,
                    is_primary_listing=listing.is_primary,
                    is_active=instrument.is_active and listing.is_active,
                )
            )
    _INDEX = InstrumentIndex(tuple(entries), by_instrument_id, by_listing_id, by_reference)
    return _INDEX


def _add_reference(target: dict[str, tuple[Instrument, InstrumentListing]], value: str | None, pair: tuple[Instrument, InstrumentListing]) -> None:
    normalized = normalize_symbol(value)
    if normalized and normalized not in target:
        target[normalized] = pair


def _listing_set(instrument: Instrument) -> tuple[InstrumentListing, ...]:
    return instrument.listings or (
        InstrumentListing(
            listing_id=f"{instrument.exchange}:{instrument.symbol}",
            symbol=instrument.symbol,
            exchange=instrument.exchange,
            country=instrument.country,
            currency=instrument.currency,
            local_code=instrument.symbol,
        ),
    )


def _token(value: str | None, kind: str) -> SearchToken | None:
    normalized = normalize_search_query(value or "")
    if not normalized:
        return None
    return SearchToken(value=value or "", kind=kind, normalized=normalized, compact=normalize_symbol(normalized))


def _score_token(token: SearchToken, normalized: str, query_symbol: str) -> tuple[int, str | None]:
    exact = token.normalized == normalized or token.compact == query_symbol
    prefix = token.normalized.startswith(normalized) or token.compact.startswith(query_symbol)
    includes = normalized in token.normalized or query_symbol in token.compact
    identifier = token.kind in {"ISIN", "FIGI", "CUSIP", "SEDOL", "RIC", "CIK"}
    if exact:
        if token.kind == "SYMBOL":
            return 1000, "SYMBOL_EXACT"
        if token.kind == "LOCAL_CODE":
            return 1000, "LOCAL_CODE_EXACT"
        if identifier:
            return 950, "IDENTIFIER_EXACT"
        if token.kind == "NAME":
            return 700, "NAME_EXACT"
        return 450, f"{token.kind}_EXACT"
    if prefix:
        if token.kind == "SYMBOL":
            return 800, "SYMBOL_PREFIX"
        if token.kind == "LOCAL_CODE":
            return 800, "LOCAL_CODE_PREFIX"
        if identifier:
            return 720, "IDENTIFIER_PREFIX"
        if token.kind == "NAME":
            return 500, "NAME_PREFIX"
        return 420, f"{token.kind}_PREFIX"
    if includes:
        if token.kind == "SYMBOL":
            return 550, "SYMBOL_MATCH"
        if token.kind == "LOCAL_CODE":
            return 550, "LOCAL_CODE_MATCH"
        if identifier:
            return 500, "IDENTIFIER_MATCH"
        if token.kind == "NAME":
            return 350, "NAME_MATCH"
        return 300, f"{token.kind}_MATCH"
    return 0, None


def _is_likely_symbol_query(normalized: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9.\-/]+", normalized))


def _is_advanced(instrument: Instrument) -> bool:
    source = f"{instrument.instrument_type} {instrument.asset_class} {instrument.sector} {instrument.name}".casefold()
    return instrument.leverage_flag or instrument.inverse_flag or any(term in source for term in ("warrant", "preferred", "right", "unit", "option", "future", "leveraged"))


def _result_for(entry: SearchEntry, score: int, matched_on: list[str]) -> dict[str, Any]:
    instrument = entry.instrument
    listing = entry.listing
    quality = instrument.quality_level
    tooltip_keys = ["ticker", "exchange", "asset_class", "instrument_type", "currency", "country", "data_quality", "sector"]
    if _is_advanced(instrument):
        tooltip_keys.append("advanced_instrument")
    if not entry.is_active:
        tooltip_keys.append("inactive_security")
    if quality == "STALE":
        tooltip_keys.append("stale_data")
    if quality == "PARTIAL":
        tooltip_keys.append("partial_data")
    if quality == "USER_PROVIDED":
        tooltip_keys.append("user_provided_data")
    return {
        "instrumentId": instrument.instrument_id,
        "listingId": listing.listing_id,
        "displaySymbol": listing.symbol.upper(),
        "name": instrument.name,
        "exchange": listing.exchange,
        "country": listing.country,
        "currency": listing.currency,
        "assetClass": instrument.asset_class,
        "instrumentType": instrument.instrument_type,
        "sector": instrument.sector,
        "isPrimaryListing": entry.is_primary_listing,
        "isAdvancedInstrument": _is_advanced(instrument),
        "isActive": entry.is_active,
        "isStale": quality == "STALE",
        "qualityLevel": quality,
        "qualityMessage": instrument.quality_message,
        "metadataCoverage": "full" if quality == "COMPLETE" else "partial" if quality in {"PARTIAL", "STALE", "PROXY", "ESTIMATED"} else "unavailable",
        "priceCoverage": "unavailable",
        "calculationEligible": False,
        "requiresUserPrice": True,
        "sourceProviders": list(instrument.source_providers),
        "sourceObservedAt": INDEX_LAST_UPDATED_AT,
        "score": score,
        "matchedOn": matched_on,
        "tooltipKeys": tooltip_keys,
    }


def _response(query: str, results: list[dict[str, Any]], warnings: list[str], *, cache: str = "none") -> dict[str, Any]:
    freshness = _index_freshness()
    return {
        "query": query,
        "results": results,
        "warnings": warnings,
        "cache": cache,
        "dataFreshness": {
            "instrumentIndexLastUpdatedAt": INDEX_LAST_UPDATED_AT,
            "observedAt": freshness["observedAt"],
            "status": str(freshness["stalenessState"]).upper(),
            "stalenessState": freshness["stalenessState"],
            "ageSeconds": freshness["ageSeconds"],
            "staleAfter": freshness["staleAfter"],
            "hardExpiresAt": freshness["hardExpiresAt"],
            "source": "local_scheduled_index",
            "schemaVersion": INDEX_SCHEMA_VERSION,
            "providerStatuses": _INDEX_SOURCE_STATUSES,
        },
    }


def _fresh_index() -> bool:
    return _index_freshness()["stalenessState"] == "fresh"


def _index_freshness() -> dict[str, Any]:
    settings = get_settings()
    refresh_seconds = max(3600, int(getattr(settings, "instrument_universe_refresh_seconds", 14400) or 14400))
    stale_after_seconds = max(2 * refresh_seconds, 7200)
    try:
        updated = datetime.fromisoformat(INDEX_LAST_UPDATED_AT.replace("Z", "+00:00"))
    except ValueError:
        return {
            "observedAt": INDEX_LAST_UPDATED_AT,
            "stalenessState": "hard_stale",
            "ageSeconds": None,
            "staleAfter": None,
            "hardExpiresAt": None,
        }
    now = datetime.now(timezone.utc)
    age_seconds = max(0, int((now - updated).total_seconds()))
    state = "fresh" if age_seconds <= stale_after_seconds else "stale" if age_seconds <= INSTRUMENT_INDEX_HARD_EXPIRES_SECONDS else "hard_stale"
    return {
        "observedAt": INDEX_LAST_UPDATED_AT,
        "stalenessState": state,
        "ageSeconds": age_seconds,
        "staleAfter": (updated + timedelta(seconds=stale_after_seconds)).isoformat().replace("+00:00", "Z"),
        "hardExpiresAt": (updated + timedelta(seconds=INSTRUMENT_INDEX_HARD_EXPIRES_SECONDS)).isoformat().replace("+00:00", "Z"),
    }


def _set_cache(cache_key: str, results: list[dict[str, Any]]) -> None:
    settings = get_settings()
    now = time.time()
    expired = [key for key, value in _SEARCH_CACHE.items() if value[0] <= now]
    for key in expired:
        _SEARCH_CACHE.pop(key, None)
    while len(_SEARCH_CACHE) >= 200:
        oldest = next(iter(_SEARCH_CACHE))
        _SEARCH_CACHE.pop(oldest, None)
    _SEARCH_CACHE[cache_key] = (now + settings.instrument_autocomplete_index_ttl_seconds, results)


def _listing_payload(instrument: Instrument, listing: InstrumentListing) -> dict[str, Any]:
    return {
        "listingId": listing.listing_id,
        "instrumentId": instrument.instrument_id,
        "displaySymbol": listing.symbol,
        "exchangeCode": listing.exchange,
        "exchangeName": listing.exchange,
        "country": listing.country,
        "tradingCurrency": listing.currency,
        "listingType": "PRIMARY" if listing.is_primary else "SECONDARY",
        "isPrimaryListing": listing.is_primary,
        "isActive": listing.is_active,
        "localCode": listing.local_code,
    }


def _data_quality_issues(instrument: Instrument) -> list[dict[str, Any]]:
    if instrument.quality_level == "COMPLETE":
        return []
    return [
        {
            "entityType": "INSTRUMENT",
            "entityId": instrument.instrument_id,
            "severity": "WARNING" if instrument.quality_level in {"PARTIAL", "STALE"} else "INFO",
            "issueType": instrument.quality_level,
            "message": instrument.quality_message,
            "detectedAt": INDEX_LAST_UPDATED_AT,
            "status": "OPEN",
        }
    ]
