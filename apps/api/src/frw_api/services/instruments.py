from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from frw_api.core.settings import get_settings

INDEX_LAST_UPDATED_AT = "2026-05-30T00:00:00Z"
_SEARCH_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_INDEX: InstrumentIndex | None = None


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
    _set_cache(cache_key, sorted_results)
    return _response(query, sorted_results[:bounded_limit], [], cache="miss")


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
    global _INDEX
    _INDEX = None
    _SEARCH_CACHE.clear()
    index = _instrument_index()
    return {
        "status": "refreshed",
        "source": source,
        "mode": mode,
        "instrument_count": len(index.by_instrument_id),
        "listing_count": len(index.by_listing_id),
        "cache_entries": len(_SEARCH_CACHE),
        "instrumentIndexLastUpdatedAt": INDEX_LAST_UPDATED_AT,
    }


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
        return _INDEX
    entries: list[SearchEntry] = []
    by_instrument_id: dict[str, Instrument] = {}
    by_listing_id: dict[str, tuple[Instrument, InstrumentListing]] = {}
    by_reference: dict[str, tuple[Instrument, InstrumentListing]] = {}
    for instrument in instrument_catalog():
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
    identifier = token.kind in {"ISIN", "FIGI", "CUSIP", "SEDOL", "RIC"}
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
        "score": score,
        "matchedOn": matched_on,
        "tooltipKeys": tooltip_keys,
    }


def _response(query: str, results: list[dict[str, Any]], warnings: list[str], *, cache: str = "none") -> dict[str, Any]:
    return {
        "query": query,
        "results": results,
        "warnings": warnings,
        "cache": cache,
        "dataFreshness": {
            "instrumentIndexLastUpdatedAt": INDEX_LAST_UPDATED_AT,
            "status": "FRESH" if _fresh_index() else "STALE",
            "source": "local_scheduled_index",
        },
    }


def _fresh_index() -> bool:
    try:
        updated = datetime.fromisoformat(INDEX_LAST_UPDATED_AT.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - updated).total_seconds() <= 7 * 86400


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
