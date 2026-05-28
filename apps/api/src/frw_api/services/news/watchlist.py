from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

_WATCHLIST_PATH = Path(__file__).with_name("ticker_watchlist.json")


@lru_cache(maxsize=1)
def ticker_watchlist_payload() -> dict[str, Any]:
    payload = json.loads(_WATCHLIST_PATH.read_text())
    if not isinstance(payload, dict) or not isinstance(payload.get("entities"), list):
        raise ValueError("ticker_watchlist.json must contain an entities array")
    return payload


def watchlist_entity_dicts() -> tuple[dict[str, Any], ...]:
    seen: set[str] = set()
    entities: list[dict[str, Any]] = []
    for raw in ticker_watchlist_payload()["entities"]:
        if not isinstance(raw, dict):
            raise ValueError("ticker watchlist entities must be objects")
        symbol = _required_string(raw, "symbol").upper()
        if symbol in seen:
            raise ValueError(f"Duplicate ticker watchlist symbol: {symbol}")
        seen.add(symbol)
        entity = dict(raw)
        entity["symbol"] = symbol
        entity["legal_name"] = str(entity.get("legal_name") or symbol)
        for key in ("aliases", "official_domains", "sector_terms"):
            entity[key] = _string_tuple(entity.get(key))
        entities.append(entity)
    return tuple(entities)


def watchlist_source_dicts() -> tuple[dict[str, Any], ...]:
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    for entity in watchlist_entity_dicts():
        symbol = str(entity["symbol"])
        for raw_source in entity.get("sources") or []:
            if not isinstance(raw_source, dict):
                raise ValueError(f"Ticker watchlist sources for {symbol} must be objects")
            source = dict(raw_source)
            source_key = _required_string(source, "source_key")
            if source_key in seen:
                raise ValueError(f"Duplicate ticker watchlist source_key: {source_key}")
            seen.add(source_key)
            source.setdefault("symbols", (symbol,))
            source.setdefault("entity_type", "ticker")
            source.setdefault("enabled", True)
            source.setdefault("scheduled_fetch", True)
            source.setdefault("fetch_kind", "feed")
            source.setdefault("discovery_only", False)
            source.setdefault("retention_class", "metadata_only")
            source.setdefault("fallback_source_keys", ())
            for key in (
                "region_coverage",
                "topic_coverage",
                "symbols",
                "official_domains",
                "fallback_source_keys",
            ):
                source[key] = _string_tuple(source.get(key))
            sources.append(source)
        for source in _default_sec_sources(entity):
            source_key = _required_string(source, "source_key")
            if source_key in seen:
                continue
            seen.add(source_key)
            sources.append(source)
        for source in _default_discovery_sources(entity):
            source_key = _required_string(source, "source_key")
            if source_key in seen:
                raise ValueError(f"Duplicate ticker watchlist source_key: {source_key}")
            seen.add(source_key)
            sources.append(source)
    return tuple(sources)


def watchlist_symbols() -> tuple[str, ...]:
    return tuple(entity["symbol"] for entity in watchlist_entity_dicts())


def _required_string(value: dict[str, Any], key: str) -> str:
    item = str(value.get(key) or "").strip()
    if not item:
        raise ValueError(f"ticker_watchlist.json missing required field: {key}")
    return item


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, list | tuple):
        return tuple(str(item).strip() for item in value if str(item).strip())
    raise ValueError("ticker watchlist list fields must be arrays or comma-separated strings")


def _default_discovery_sources(entity: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    if entity.get("default_discovery_sources") is False:
        return ()
    symbol = str(entity["symbol"])
    legal_name = str(entity.get("legal_name") or symbol)
    symbol_key = _source_symbol_key(symbol)
    query_parts = [symbol, f'"{legal_name}"']
    for alias in entity.get("aliases") or ():
        query_parts.append(f'"{alias}"')
    sources: list[dict[str, Any]] = [
        {
            "source_key": f"google_news_{symbol_key}",
            "source_name": f"Google News RSS - {symbol}",
            "source_type": "rss_discovery",
            "base_url": "https://news.google.com/rss",
            "trust_tier": "T4_WEAK_SIGNAL",
            "region_coverage": ("GLOBAL",),
            "topic_coverage": ("stocks", "filings", "geopolitics"),
            "rate_limit_provider_key": "google_news_rss",
            "rate_limit_endpoint_key": "search",
            "copyright_mode": "metadata_only",
            "fetch_kind": "google_news_search",
            "default_query": f"({' OR '.join(query_parts)}) stock news when:7d",
            "symbols": (symbol,),
            "entity_type": "ticker",
            "scheduled_fetch": True,
            "discovery_only": True,
            "retention_class": "metadata_only",
            "official_domains": (),
            "fallback_source_keys": (),
        },
    ]
    if entity.get("yahoo_discovery_enabled") is not False:
        sources.append(
            {
                "source_key": f"yahoo_finance_{symbol_key}",
                "source_name": f"Yahoo Finance RSS - {symbol}",
                "source_type": "rss_discovery",
                "base_url": "https://feeds.finance.yahoo.com",
                "trust_tier": "T4_WEAK_SIGNAL",
                "region_coverage": ("GLOBAL",),
                "topic_coverage": ("stocks",),
                "rate_limit_provider_key": "yahoo_finance_rss",
                "rate_limit_endpoint_key": "rss",
                "copyright_mode": "metadata_only",
                "feed_url": (
                    "https://feeds.finance.yahoo.com/rss/2.0/headline"
                    f"?s={quote(symbol)}&region=US&lang=en-US"
                ),
                "fetch_kind": "feed",
                "symbols": (symbol,),
                "entity_type": "ticker",
                "scheduled_fetch": True,
                "discovery_only": True,
                "retention_class": "metadata_only",
                "official_domains": (),
                "fallback_source_keys": (),
            }
        )
    return tuple(sources)


def _default_sec_sources(entity: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    cik = str(entity.get("sec_cik") or "").strip()
    if not cik:
        return ()
    symbol = str(entity["symbol"])
    symbol_key = _source_symbol_key(symbol).lower()
    cik10 = cik.zfill(10)
    return (
        {
            "source_key": f"sec_{symbol_key}_filings",
            "source_name": f"SEC EDGAR - {symbol}",
            "source_type": "regulated_filing",
            "base_url": "https://data.sec.gov",
            "trust_tier": "T1_REGULATED_FILING",
            "region_coverage": ("USA",),
            "topic_coverage": ("filings", "stocks"),
            "rate_limit_provider_key": "sec_edgar",
            "rate_limit_endpoint_key": "submissions",
            "copyright_mode": "public_filing_metadata",
            "feed_url": f"https://data.sec.gov/submissions/CIK{cik10}.json",
            "fetch_kind": "sec_submissions",
            "symbols": (symbol,),
            "entity_type": "ticker",
            "scheduled_fetch": True,
            "discovery_only": False,
            "retention_class": "structured_fact_only",
            "official_domains": ("sec.gov",),
            "fallback_source_keys": (),
        },
    )


def _source_symbol_key(symbol: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in symbol.upper()).strip("_")
