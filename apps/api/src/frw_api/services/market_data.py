from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from frw_api.core.settings import get_settings
from frw_api.services.provider_limits import (
    ERROR_RATE_LIMITED,
    ProviderLimitError,
    ProviderLimitRegistry,
    provider_request,
)

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
    db: Session | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    normalized = _normalize_symbols(symbols, settings.market_data_max_symbols)
    if start > end:
        raise MarketDataInputError("start date must be before end date")
    if (end - start).days > settings.market_data_max_history_days:
        raise MarketDataInputError(
            f"date range exceeds {settings.market_data_max_history_days} days"
        )

    display_mode = settings.resolved_market_data_display_mode
    display_allowlist = ",".join(sorted(settings.market_data_public_display_allowlist_values))
    cache_key = (
        f"{','.join(normalized)}:{start.isoformat()}:{end.isoformat()}:"
        f"{_provider_order()}:{display_mode}:{display_allowlist}"
    )
    now = time.time()
    cached_payload = _cache_get(cache_key, now=now)
    if cached_payload:
        payload = deepcopy(cached_payload)
        payload["cache"] = "hit"
        return payload

    provider_status = _provider_status()
    provider_order = [item for item in _provider_order() if item in {"twelve_data", "alpha_vantage", "fmp"}]
    display_allowed_providers = [
        provider
        for provider in provider_order
        if _provider_public_display_allowed(provider) or provider in settings.market_data_public_display_allowlist_values
    ]
    if display_mode == "public" and not display_allowed_providers:
        payload = _license_limited_payload(
            symbols=normalized,
            start=start,
            end=end,
            provider_order=provider_order,
            reason=(
                "Configured free market-data providers are not approved for public quote/candle "
                "redistribution. Use TradingView for public visual market display or explicitly "
                "allow a provider after legal/source-policy review."
            ),
        )
        _cache_set(
            cache_key,
            payload,
            expires_at=now + min(settings.market_data_cache_ttl_seconds, 300),
            max_entries=settings.market_data_cache_max_entries,
            now=now,
        )
        return payload
    if display_mode == "public":
        provider_order = [provider for provider in provider_order if provider in display_allowed_providers]
    failures: list[str] = []

    for provider in provider_order:
        key = _api_key(provider)
        if not key:
            failures.append(f"{provider}: missing API key")
            continue
        try:
            series = await _fetch_provider(provider, key, normalized, start, end, transport, db)
        except ProviderLimitError as exc:
            detail = exc.error_class
            if exc.retry_after_seconds is not None:
                detail = f"{detail}; retry after {exc.retry_after_seconds}s"
            failures.append(f"{provider}: {detail}")
            continue
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            failures.append(f"{provider}: {exc}")
            continue
        if all(item["points"] for item in series):
            payload = {
                "status": "ok",
                "provider": provider,
                "source_note": _source_note(provider),
                "cache": "miss",
                "display_mode": display_mode,
                "display_status": "display_allowed",
                "data_freshness": _data_freshness(
                    provider=provider,
                    series=series,
                    fetched_at=datetime.now(timezone.utc),
                    display_mode=display_mode,
                    public_display_allowed=True,
                ),
                "provider_budget_status": _provider_budget_status(provider),
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


def _provider_public_display_allowed(provider: str) -> bool:
    return ProviderLimitRegistry().public_display_allowed(provider, "daily_prices")


def _provider_budget_status(provider: str) -> list[dict[str, Any]]:
    return [
        _public_provider_budget(item)
        for item in ProviderLimitRegistry().as_dicts()
        if item["provider_key"] == provider and item["endpoint_key"] in {"daily_prices", "*"}
    ]


def _public_provider_budget(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_key": item["provider_key"],
        "endpoint_key": item["endpoint_key"],
        "public_display_allowed": item["public_display_allowed"],
        "attribution_required": item["attribution_required"],
        "refresh_interval": _provider_refresh_interval(item.get("rules", [])),
        "source_checked_at": item["source_checked_at"],
    }


def _provider_refresh_interval(rules: list[dict[str, Any]]) -> str:
    request_rules = [
        rule for rule in rules if rule.get("unit") == "request" and rule.get("window_seconds")
    ]
    if not request_rules:
        return "policy-defined"
    rule = max(request_rules, key=lambda item: int(item.get("window_seconds") or 0))
    window_seconds = int(rule.get("window_seconds") or 0)
    limit = float(rule.get("limit") or 0)
    if window_seconds <= 0 or limit <= 0:
        return "policy-defined"
    seconds_per_request = max(1, round(window_seconds / limit))
    if seconds_per_request < 60:
        return f"at most every {seconds_per_request}s"
    minutes = round(seconds_per_request / 60)
    if minutes < 60:
        return f"at most every {minutes}m"
    hours = round(minutes / 60)
    return f"at most every {hours}h"


def _license_limited_payload(
    *,
    symbols: list[str],
    start: date,
    end: date,
    provider_order: list[str],
    reason: str,
) -> dict[str, Any]:
    fetched_at = datetime.now(timezone.utc)
    return {
        "status": "license_limited",
        "provider": "tradingview_widget_only",
        "source_note": reason,
        "cache": "miss",
        "display_mode": "public",
        "display_status": "license_limited",
        "data_freshness": {
            "provider": "tradingview_widget_only",
            "provider_timestamp": None,
            "fetched_at": fetched_at.isoformat(),
            "market_session_date": None,
            "exchange_timezone": "America/New_York",
            "delay_label": "license-limited",
            "is_same_day_valid": False,
            "is_public_display_allowed": False,
            "staleness_reason": reason,
            "license_mode": "public_display_not_allowed",
            "source_url": "https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/",
        },
        "provider_budget_status": [
            _public_provider_budget(item)
            for item in ProviderLimitRegistry().as_dicts()
            if item["provider_key"] in set(provider_order)
        ],
        "symbols": symbols,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "series": [{"symbol": symbol, "points": []} for symbol in symbols],
        "warnings": [reason],
    }


def _data_freshness(
    *,
    provider: str,
    series: list[dict[str, Any]],
    fetched_at: datetime,
    display_mode: str,
    public_display_allowed: bool,
) -> dict[str, Any]:
    market_session_date = _latest_market_session_date(series)
    return {
        "provider": provider,
        "provider_timestamp": market_session_date,
        "fetched_at": fetched_at.isoformat(),
        "market_session_date": market_session_date,
        "exchange_timezone": "America/New_York",
        "delay_label": _delay_label(provider, display_mode, market_session_date),
        "is_same_day_valid": False,
        "is_public_display_allowed": public_display_allowed,
        "staleness_reason": (
            "Daily candle history only; not same-day intraday data and not a realtime quote."
            if market_session_date
            else "Provider returned no market session date."
        ),
        "license_mode": "private_or_internal" if display_mode == "private" else "public_display_allowed",
        "source_url": _provider_source_url(provider),
    }


def _latest_market_session_date(series: list[dict[str, Any]]) -> str | None:
    dates = [
        str(point.get("date"))
        for item in series
        for point in item.get("points", [])
        if point.get("date")
    ]
    return max(dates) if dates else None


def _delay_label(provider: str, display_mode: str, market_session_date: str | None) -> str:
    if display_mode == "private":
        return f"daily historical/private-mode; latest session {market_session_date or 'pending'}"
    return f"public-display allowed daily snapshot; latest session {market_session_date or 'pending'}"


def _provider_source_url(provider: str) -> str:
    for item in ProviderLimitRegistry().as_dicts():
        if item["provider_key"] == provider and item["endpoint_key"] in {"daily_prices", "*"}:
            return str(item["source_url"])
    return ""


async def _fetch_provider(
    provider: str,
    key: str,
    symbols: list[str],
    start: date,
    end: date,
    transport: httpx.AsyncBaseTransport | None,
    db: Session | None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.market_data_timeout_seconds)
    limits = httpx.Limits(
        max_connections=max(1, min(len(symbols), settings.market_data_max_symbols)),
        max_keepalive_connections=max(1, min(len(symbols), settings.market_data_max_symbols)),
    )
    async with httpx.AsyncClient(timeout=timeout, limits=limits, transport=transport) as client:
        series = []
        for symbol in symbols:
            series.append(await _fetch_symbol(client, provider, key, symbol, start, end, db))
        return series


async def _fetch_symbol(
    client: httpx.AsyncClient,
    provider: str,
    key: str,
    symbol: str,
    start: date,
    end: date,
    db: Session | None,
) -> dict[str, Any]:
    if provider == "twelve_data":
        points = await _fetch_twelve_data(client, key, symbol, start, end, db)
    elif provider == "alpha_vantage":
        points = await _fetch_alpha_vantage(client, key, symbol, start, end, db)
    elif provider == "fmp":
        points = await _fetch_fmp(client, key, symbol, start, end, db)
    else:
        raise ValueError(f"unsupported market-data provider {provider}")
    return {"symbol": symbol, "points": [point.__dict__ for point in points]}


async def _fetch_twelve_data(
    client: httpx.AsyncClient,
    key: str,
    symbol: str,
    start: date,
    end: date,
    db: Session | None,
) -> list[HistoryPoint]:
    response = await provider_request(
        client,
        "GET",
        "https://api.twelvedata.com/time_series",
        provider_key="twelve_data",
        endpoint_key="daily_prices",
        db=db,
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
    payload = response.json()
    if payload.get("status") == "error":
        message = str(payload.get("message", "Twelve Data error"))
        if "credit" in message.lower() or "rate" in message.lower():
            raise ProviderLimitError(
                message,
                error_class=ERROR_RATE_LIMITED,
                provider_key="twelve_data",
                endpoint_key="daily_prices",
                retry_after_seconds=60,
            )
        raise ValueError(message)
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
    db: Session | None,
) -> list[HistoryPoint]:
    response = await provider_request(
        client,
        "GET",
        "https://www.alphavantage.co/query",
        provider_key="alpha_vantage",
        endpoint_key="daily_prices",
        db=db,
        params={
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "compact",
            "apikey": key,
        },
    )
    payload = response.json()
    if "Note" in payload or "Information" in payload or "Error Message" in payload:
        message = str(payload.get("Note") or payload.get("Information") or payload.get("Error Message"))
        if "rate limit" in message.lower() or "frequency" in message.lower():
            raise ProviderLimitError(
                message,
                error_class=ERROR_RATE_LIMITED,
                provider_key="alpha_vantage",
                endpoint_key="daily_prices",
                retry_after_seconds=86_400,
            )
        raise ValueError(message)
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
    db: Session | None,
) -> list[HistoryPoint]:
    response = await provider_request(
        client,
        "GET",
        "https://financialmodelingprep.com/stable/historical-price-eod/full",
        provider_key="fmp",
        endpoint_key="daily_prices",
        db=db,
        units={"request": 1, "byte": 500_000},
        params={"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "apikey": key},
    )
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
