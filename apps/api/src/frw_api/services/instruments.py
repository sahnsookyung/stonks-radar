from __future__ import annotations

import csv
import json
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import httpx

from frw_api.core.settings import get_settings

INDEX_SCHEMA_VERSION = 1
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
NASDAQ_OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
SEC_COMPANY_TICKERS_EXCHANGE_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
UTC_OFFSET_SUFFIX = "+00:00"
UTC_Z_SUFFIX = "Z"
INFO_TECH_SECTOR = "Information Technology"
SAMSUNG_ELECTRONICS_SYMBOL = "005930.KS"
INDEX_LAST_UPDATED_AT = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(UTC_OFFSET_SUFFIX, UTC_Z_SUFFIX)
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


@dataclass(frozen=True)
class SearchFilters:
    include_advanced: bool
    include_inactive: bool
    country: str | None
    exchange: str | None
    asset_class: str | None
    instrument_type: str | None
    context: str


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
            INFO_TECH_SECTOR,
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
            INFO_TECH_SECTOR,
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
            INFO_TECH_SECTOR,
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
            instrument_id=SAMSUNG_ELECTRONICS_SYMBOL,
            symbol=SAMSUNG_ELECTRONICS_SYMBOL,
            name="Samsung Electronics Co., Ltd.",
            exchange="KRX",
            country="Korea",
            currency="KRW",
            asset_class="Equity",
            instrument_type="stock",
            sector=INFO_TECH_SECTOR,
            quality_level="PARTIAL",
            quality_message="Partial data: sector classification confirmed; holdings look-through not applicable.",
            aliases=("Samsung Electronics", "삼성전자"),
            identifiers=(InstrumentIdentifier("ISIN", "KR7005930003"), InstrumentIdentifier("LOCAL_CODE", "005930")),
            listings=(
                InstrumentListing(
                    listing_id="KRX:005930",
                    symbol=SAMSUNG_ELECTRONICS_SYMBOL,
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
            INFO_TECH_SECTOR,
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
    except (OSError, ValueError, TypeError) as exc:
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
    minimum_warning = _search_validation_warning(query, normalized, settings.instrument_autocomplete_max_query_length)
    if minimum_warning:
        return _response(query, [], [minimum_warning])
    bounded_limit = max(1, min(limit, settings.instrument_autocomplete_max_results))
    filters = SearchFilters(
        include_advanced=include_advanced,
        include_inactive=include_inactive,
        country=country,
        exchange=exchange,
        asset_class=asset_class,
        instrument_type=instrument_type,
        context=context,
    )
    cache_key = _search_cache_key(normalized, bounded_limit, filters)
    now = time.time()
    cached_results = _cached_search_results(cache_key, bounded_limit, now=now)
    if cached_results is not None:
        return _response(query, cached_results, [], cache="hit")
    sorted_results = _search_index_results(normalized, filters)
    limited_results = sorted_results[:bounded_limit]
    _set_cache(cache_key, limited_results)
    return _response(query, limited_results, [], cache="miss")


def _search_validation_warning(query: str, normalized: str, max_length: int) -> str | None:
    if len(query) > max_length:
        raise ValueError(f"query exceeds maximum length of {max_length}")
    min_length = 1 if _is_likely_symbol_query(normalized) else 2
    if len(normalized) < min_length:
        return f"{min_length}-character minimum for this query type"
    return None


def _search_cache_key(normalized: str, bounded_limit: int, filters: SearchFilters) -> str:
    return "|".join(
        [
            normalized,
            str(bounded_limit),
            str(filters.include_advanced),
            str(filters.include_inactive),
            (filters.country or "").upper(),
            (filters.exchange or "").upper(),
            (filters.asset_class or "").upper(),
            (filters.instrument_type or "").upper(),
            filters.context,
        ]
    )


def _cached_search_results(cache_key: str, bounded_limit: int, *, now: float) -> list[dict[str, Any]] | None:
    cached = _SEARCH_CACHE.get(cache_key)
    if cached and cached[0] > now:
        return cached[1][:bounded_limit]
    if cached:
        _SEARCH_CACHE.pop(cache_key, None)
    return None


def _search_index_results(normalized: str, filters: SearchFilters) -> list[dict[str, Any]]:
    query_symbol = normalize_symbol(normalized)
    results: dict[str, dict[str, Any]] = {}
    for entry in _instrument_index().entries:
        result = _search_result_for_entry(entry, normalized, query_symbol, filters)
        if result is not None:
            _keep_best_search_result(results, result)
    return sorted(results.values(), key=lambda row: (-float(row["score"]), str(row["displaySymbol"])))


def _search_result_for_entry(
    entry: SearchEntry,
    normalized: str,
    query_symbol: str,
    filters: SearchFilters,
) -> dict[str, Any] | None:
    if not _entry_matches_filters(entry, filters):
        return None
    exact_symbol = _entry_exact_symbol(entry, query_symbol)
    exact_name = normalize_search_query(entry.instrument.name) == normalized
    if _is_advanced(entry.instrument) and not filters.include_advanced and not exact_symbol and not exact_name:
        return None
    score, matched_on = _entry_search_score(entry, normalized, query_symbol, exact_symbol, filters.context)
    if score <= 0:
        return None
    return _result_for(entry, score, sorted(set(matched_on)))


def _entry_matches_filters(entry: SearchEntry, filters: SearchFilters) -> bool:
    instrument = entry.instrument
    listing = entry.listing
    return (
        _matches_upper(filters.country, listing.country)
        and _matches_upper(filters.exchange, listing.exchange)
        and _matches_upper(filters.asset_class, instrument.asset_class)
        and _matches_upper(filters.instrument_type, instrument.instrument_type)
        and (entry.is_active or filters.include_inactive)
    )


def _matches_upper(expected: str | None, actual: str) -> bool:
    return not expected or actual.upper() == expected.upper()


def _entry_exact_symbol(entry: SearchEntry, query_symbol: str) -> bool:
    return normalize_symbol(entry.listing.symbol) == query_symbol or normalize_symbol(entry.instrument.symbol) == query_symbol


def _entry_search_score(
    entry: SearchEntry,
    normalized: str,
    query_symbol: str,
    exact_symbol: bool,
    context: str,
) -> tuple[int, list[str]]:
    score, matched_on = _token_match_score(entry.tokens, normalized, query_symbol)
    if score <= 0:
        return score, matched_on
    return score + _entry_rank_bonus(entry, exact_symbol, context), matched_on


def _token_match_score(tokens: tuple[SearchToken, ...], normalized: str, query_symbol: str) -> tuple[int, list[str]]:
    score = 0
    matched_on: list[str] = []
    for token in tokens:
        token_score, matched = _score_token(token, normalized, query_symbol)
        score += token_score
        if matched:
            matched_on.append(matched)
    return score, matched_on


def _entry_rank_bonus(entry: SearchEntry, exact_symbol: bool, context: str) -> int:
    score = 0
    if entry.is_active:
        score += 150
    if entry.is_primary_listing:
        score += 100
    if entry.listing.currency == "USD":
        score += 20
    if context == "BUILDER" and entry.instrument.instrument_type in {"etf", "stock"}:
        score += 60
    if context == "TAX_LOT" and exact_symbol:
        score += 60
    return score + _quality_rank_adjustment(entry.instrument.quality_level)


def _quality_rank_adjustment(quality_level: str) -> int:
    if quality_level == "STALE":
        return -100
    if quality_level == "UNAVAILABLE":
        return -200
    return 0


def _keep_best_search_result(results: dict[str, dict[str, Any]], result: dict[str, Any]) -> None:
    previous = results.get(result["listingId"])
    if not previous or float(result["score"]) > float(previous["score"]):
        results[result["listingId"]] = result


def resolve_instrument(
    *,
    symbol: str,  # NOSONAR - seed helper intentionally mirrors the Instrument constructor shape.
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
    generated_at = _utc_now_label()
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
    except (httpx.HTTPError, ValueError, TypeError) as exc:
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
    return [
        instrument
        for raw in data
        if (instrument := _sec_company_ticker_instrument(fields, raw, generated_at=generated_at)) is not None
    ]


def _sec_company_ticker_instrument(fields: list[Any], raw: Any, *, generated_at: str) -> Instrument | None:
    if not isinstance(raw, list):
        return None
    row = dict(zip(fields, raw, strict=False))
    ticker = str(row.get("ticker") or "").strip()
    name = str(row.get("name") or "").strip()
    if not ticker or not name:
        return None
    exchange = str(row.get("exchange") or "").strip() or "SEC"
    cik = str(row.get("cik") or "").strip()
    return _source_instrument(
        symbol=ticker,
        name=name,
        exchange=exchange,
        etf=False,
        generated_at=generated_at,
        identifiers=(InstrumentIdentifier("CIK", cik.zfill(10)),) if cik else (),
        quality_message="SEC company ticker mapping; listing classification may be incomplete.",
        source_provider="sec_company_tickers",
    )


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
    merged = cast(
        Instrument,
        replace(
            left,
            identifiers=tuple(identifiers.values()),
            listings=tuple(listings.values()) or left.listings,
            aliases=aliases,
            source_providers=source_providers,
            sector=sector,
            theme_tags=theme_tags,
        ),
    )
    return merged


def _write_dynamic_instrument_artifact(instruments: tuple[Instrument, ...], statuses: list[dict[str, Any]], *, settings) -> None:
    global INDEX_LAST_UPDATED_AT, _INDEX_SOURCE_STATUSES
    generated_at = _utc_now_label()
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
    *parts: str,
    aliases: tuple[str, ...] = (),
    identifiers: tuple[InstrumentIdentifier, ...] = (),
    quality_level: str = "COMPLETE",
    quality_message: str = "Complete data",
    leverage_flag: bool = False,
    inverse_flag: bool = False,
) -> Instrument:
    if len(parts) != 8:
        raise ValueError("static instrument seed requires symbol, name, exchange, country, currency, asset_class, instrument_type, and sector")
    symbol, name, exchange, country, currency, asset_class, instrument_type, sector = parts
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
            _add_instrument_references(by_reference, instrument, listing, pair)
            by_listing_id[normalize_symbol(listing.listing_id)] = pair
            entries.append(
                SearchEntry(
                    instrument=instrument,
                    listing=listing,
                    tokens=_instrument_search_tokens(instrument, listing),
                    is_primary_listing=listing.is_primary,
                    is_active=instrument.is_active and listing.is_active,
                )
            )
    _INDEX = InstrumentIndex(tuple(entries), by_instrument_id, by_listing_id, by_reference)
    return _INDEX


def _add_instrument_references(
    target: dict[str, tuple[Instrument, InstrumentListing]],
    instrument: Instrument,
    listing: InstrumentListing,
    pair: tuple[Instrument, InstrumentListing],
) -> None:
    for ref in (
        instrument.instrument_id,
        instrument.symbol,
        instrument.name,
        listing.listing_id,
        listing.symbol,
        listing.local_code,
        *instrument.aliases,
        *(identifier.value for identifier in instrument.identifiers),
    ):
        _add_reference(target, ref, pair)


def _instrument_search_tokens(instrument: Instrument, listing: InstrumentListing) -> tuple[SearchToken, ...]:
    return tuple(
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
    if exact:
        return _score_token_match(token.kind, "EXACT")
    if prefix:
        return _score_token_match(token.kind, "PREFIX")
    if includes:
        return _score_token_match(token.kind, "MATCH")
    return 0, None


TOKEN_IDENTIFIER_KINDS = frozenset({"ISIN", "FIGI", "CUSIP", "SEDOL", "RIC", "CIK"})

TOKEN_MATCH_SCORES: dict[str, dict[str, int]] = {
    "EXACT": {"SYMBOL": 1000, "LOCAL_CODE": 1000, "IDENTIFIER": 950, "NAME": 700, "DEFAULT": 450},
    "PREFIX": {"SYMBOL": 800, "LOCAL_CODE": 800, "IDENTIFIER": 720, "NAME": 500, "DEFAULT": 420},
    "MATCH": {"SYMBOL": 550, "LOCAL_CODE": 550, "IDENTIFIER": 500, "NAME": 350, "DEFAULT": 300},
}


def _score_token_match(kind: str, match_type: str) -> tuple[int, str]:
    score_key = "IDENTIFIER" if kind in TOKEN_IDENTIFIER_KINDS else kind
    score = TOKEN_MATCH_SCORES[match_type].get(score_key, TOKEN_MATCH_SCORES[match_type]["DEFAULT"])
    label = f"{score_key}_{match_type}" if score_key == "IDENTIFIER" else f"{kind}_{match_type}"
    return score, label


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
        "metadataCoverage": _metadata_coverage_for_quality(quality),
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
        updated = datetime.fromisoformat(INDEX_LAST_UPDATED_AT.replace(UTC_Z_SUFFIX, UTC_OFFSET_SUFFIX))
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
    if age_seconds <= stale_after_seconds:
        state = "fresh"
    elif age_seconds <= INSTRUMENT_INDEX_HARD_EXPIRES_SECONDS:
        state = "stale"
    else:
        state = "hard_stale"
    return {
        "observedAt": INDEX_LAST_UPDATED_AT,
        "stalenessState": state,
        "ageSeconds": age_seconds,
        "staleAfter": (updated + timedelta(seconds=stale_after_seconds)).isoformat().replace(UTC_OFFSET_SUFFIX, UTC_Z_SUFFIX),
        "hardExpiresAt": (updated + timedelta(seconds=INSTRUMENT_INDEX_HARD_EXPIRES_SECONDS)).isoformat().replace(UTC_OFFSET_SUFFIX, UTC_Z_SUFFIX),
    }


def _utc_now_label() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(UTC_OFFSET_SUFFIX, UTC_Z_SUFFIX)


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


def _metadata_coverage_for_quality(quality: str) -> str:
    if quality == "COMPLETE":
        return "full"
    if quality in {"PARTIAL", "STALE", "PROXY", "ESTIMATED"}:
        return "partial"
    return "unavailable"


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
