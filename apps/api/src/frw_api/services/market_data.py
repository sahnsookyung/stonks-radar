from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from frw_api.core.settings import get_settings

SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-:]{0,19}$")
TRADING_DAYS_PER_YEAR = 252


class MarketDataError(Exception):
    pass


class MarketDataInputError(MarketDataError):
    pass


class MarketDataUnavailable(MarketDataError):
    def __init__(self, message: str, *, provider_status: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.provider_status = provider_status


@dataclass(frozen=True)
class HistoryPoint:
    date: str
    close: float
    volume: float | None = None


_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()


async def fetch_market_history(
    *,
    symbols: list[str],
    start: date,
    end: date,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    normalized = _normalize_symbols(symbols, settings.market_data_max_symbols)
    if start > end:
        raise MarketDataInputError("start date must be before end date")
    if (end - start).days > settings.market_data_max_history_days:
        raise MarketDataInputError(
            f"date range exceeds {settings.market_data_max_history_days} days"
        )

    cache_key = f"{','.join(normalized)}:{start.isoformat()}:{end.isoformat()}:{_provider_order()}"
    now = time.time()
    cached_payload = _cache_get(cache_key, now=now)
    if cached_payload:
        payload = deepcopy(cached_payload)
        payload["cache"] = "hit"
        return payload

    provider_status = _provider_status()
    provider_order = [item for item in _provider_order() if item in {"twelve_data", "alpha_vantage", "fmp"}]
    failures: list[str] = []

    for provider in provider_order:
        key = _api_key(provider)
        if not key:
            failures.append(f"{provider}: missing API key")
            continue
        try:
            series = await _fetch_provider(provider, key, normalized, start, end, transport)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            failures.append(f"{provider}: {exc}")
            continue
        if all(item["points"] for item in series):
            payload = {
                "status": "ok",
                "provider": provider,
                "source_note": _source_note(provider),
                "cache": "miss",
                "symbols": normalized,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "series": series,
                "warnings": failures,
            }
            _cache_set(
                cache_key,
                payload,
                expires_at=now + settings.market_data_cache_ttl_seconds,
                max_entries=settings.market_data_cache_max_entries,
                now=now,
            )
            return payload
        failures.append(f"{provider}: one or more symbols returned no usable daily closes")

    raise MarketDataUnavailable(
        "No configured market-data provider returned usable historical closes",
        provider_status=provider_status
        + [{"provider": "fallback", "status": "failed", "detail": "; ".join(failures)}],
    )


def _normalize_symbols(symbols: list[str], max_symbols: int) -> list[str]:
    values = []
    for raw in symbols:
        for part in raw.split(","):
            symbol = part.strip().upper()
            if not symbol:
                continue
            if not SYMBOL_RE.match(symbol):
                raise MarketDataInputError(f"unsupported symbol format: {symbol}")
            values.append(symbol)
    unique = list(dict.fromkeys(values))
    if not unique:
        raise MarketDataInputError("at least one symbol is required")
    if len(unique) > max_symbols:
        raise MarketDataInputError(f"at most {max_symbols} symbols are allowed")
    return unique


def _provider_order() -> list[str]:
    settings = get_settings()
    raw = settings.market_data_provider_order or settings.market_data_provider or ""
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return values or ["twelve_data", "alpha_vantage", "fmp"]


def _api_key(provider: str) -> str | None:
    settings = get_settings()
    if provider == "twelve_data":
        return settings.twelve_data_api_key or (
            settings.market_data_api_key if settings.market_data_provider == "twelve_data" else None
        )
    if provider == "alpha_vantage":
        return settings.alpha_vantage_api_key or (
            settings.market_data_api_key if settings.market_data_provider == "alpha_vantage" else None
        )
    if provider == "fmp":
        return settings.fmp_api_key or (
            settings.market_data_api_key if settings.market_data_provider == "fmp" else None
        )
    return None


def _provider_status() -> list[dict[str, str]]:
    return [
        {
            "provider": provider,
            "status": "configured" if _api_key(provider) else "missing_credentials",
            "detail": _source_note(provider),
        }
        for provider in _provider_order()
    ]


async def _fetch_provider(
    provider: str,
    key: str,
    symbols: list[str],
    start: date,
    end: date,
    transport: httpx.AsyncBaseTransport | None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.market_data_timeout_seconds)
    limits = httpx.Limits(
        max_connections=max(1, min(len(symbols), settings.market_data_max_symbols)),
        max_keepalive_connections=max(1, min(len(symbols), settings.market_data_max_symbols)),
    )
    async with httpx.AsyncClient(timeout=timeout, limits=limits, transport=transport) as client:
        tasks = [_fetch_symbol(client, provider, key, symbol, start, end) for symbol in symbols]
        return await asyncio.gather(*tasks)


async def _fetch_symbol(
    client: httpx.AsyncClient,
    provider: str,
    key: str,
    symbol: str,
    start: date,
    end: date,
) -> dict[str, Any]:
    if provider == "twelve_data":
        points = await _fetch_twelve_data(client, key, symbol, start, end)
    elif provider == "alpha_vantage":
        points = await _fetch_alpha_vantage(client, key, symbol, start, end)
    elif provider == "fmp":
        points = await _fetch_fmp(client, key, symbol, start, end)
    else:
        raise ValueError(f"unsupported market-data provider {provider}")
    return {"symbol": symbol, "points": [point.__dict__ for point in points]}


async def _fetch_twelve_data(
    client: httpx.AsyncClient,
    key: str,
    symbol: str,
    start: date,
    end: date,
) -> list[HistoryPoint]:
    response = await client.get(
        "https://api.twelvedata.com/time_series",
        params={
            "symbol": symbol,
            "interval": "1day",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "order": "ASC",
            "outputsize": 5000,
            "apikey": key,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") == "error":
        raise ValueError(str(payload.get("message", "Twelve Data error")))
    values = payload.get("values")
    if not isinstance(values, list):
        raise ValueError("Twelve Data returned no values")
    return _points_from_rows(values, date_field="datetime", close_fields=("close",))


async def _fetch_alpha_vantage(
    client: httpx.AsyncClient,
    key: str,
    symbol: str,
    start: date,
    end: date,
) -> list[HistoryPoint]:
    response = await client.get(
        "https://www.alphavantage.co/query",
        params={
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "compact",
            "apikey": key,
        },
    )
    response.raise_for_status()
    payload = response.json()
    if "Note" in payload or "Information" in payload or "Error Message" in payload:
        raise ValueError(str(payload.get("Note") or payload.get("Information") or payload.get("Error Message")))
    rows = payload.get("Time Series (Daily)")
    if not isinstance(rows, dict):
        raise ValueError("Alpha Vantage returned no daily time series")
    values = [
        {"date": row_date, "close": row.get("4. close"), "volume": row.get("5. volume")}
        for row_date, row in rows.items()
        if start.isoformat() <= row_date <= end.isoformat()
    ]
    return _points_from_rows(values, date_field="date", close_fields=("close",), descending=False)


async def _fetch_fmp(
    client: httpx.AsyncClient,
    key: str,
    symbol: str,
    start: date,
    end: date,
) -> list[HistoryPoint]:
    response = await client.get(
        "https://financialmodelingprep.com/stable/historical-price-eod/full",
        params={"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "apikey": key},
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("historical") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("FMP returned no historical rows")
    return _points_from_rows(rows, date_field="date", close_fields=("adjClose", "close"))


def _points_from_rows(
    rows: list[dict[str, Any]],
    *,
    date_field: str,
    close_fields: tuple[str, ...],
    descending: bool = False,
) -> list[HistoryPoint]:
    points: list[HistoryPoint] = []
    for row in rows:
        row_date = str(row.get(date_field, ""))[:10]
        close_value = next((row.get(field) for field in close_fields if row.get(field) is not None), None)
        if not row_date or close_value is None:
            continue
        try:
            close = float(close_value)
            volume = float(row["volume"]) if row.get("volume") not in (None, "") else None
        except (TypeError, ValueError):
            continue
        if close > 0:
            points.append(HistoryPoint(date=row_date, close=close, volume=volume))
    points.sort(key=lambda item: item.date, reverse=descending)
    return points


def _cache_get(cache_key: str, *, now: float) -> dict[str, Any] | None:
    cached = _cache.get(cache_key)
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at <= now:
        _cache.pop(cache_key, None)
        return None
    _cache.move_to_end(cache_key)
    return payload


def _cache_set(
    cache_key: str,
    payload: dict[str, Any],
    *,
    expires_at: float,
    max_entries: int,
    now: float,
) -> None:
    _prune_cache(now=now)
    _cache[cache_key] = (expires_at, deepcopy(payload))
    _cache.move_to_end(cache_key)
    while len(_cache) > max_entries:
        _cache.popitem(last=False)


def _prune_cache(*, now: float) -> None:
    expired_keys = [key for key, (expires_at, _) in _cache.items() if expires_at <= now]
    for key in expired_keys:
        _cache.pop(key, None)


def clear_market_data_cache() -> None:
    _cache.clear()


def _source_note(provider: str) -> str:
    notes = {
        "twelve_data": "Primary free-key candidate; daily/weekly/monthly prices are split-adjusted by provider docs.",
        "alpha_vantage": "Secondary free-key candidate; compact daily endpoint avoids premium full-history mode.",
        "fmp": "Tertiary free-key candidate; useful for EOD prices plus fundamentals, constrained by free-call limits.",
    }
    return notes.get(provider, "Configured provider")
