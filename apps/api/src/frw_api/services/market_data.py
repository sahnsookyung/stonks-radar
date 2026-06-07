from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from frw_api.core.settings import get_settings
from frw_api.services.provider_limits import (
    ERROR_RATE_LIMITED,
    ProviderLimitError,
    ProviderLimitRegistry,
    provider_request,
)
from frw_api.services.market_history_store import (
    load_stored_market_history,
    mark_market_history_refresh_failed,
    market_history_calculation_readiness,
    store_market_history_series,
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
    adjusted_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    currency: str = "USD"
    exchange: str | None = None
    timezone: str = "America/New_York"
    provider_timestamp: str | None = None
    source_revision: str | None = None


_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()


async def fetch_market_history(
    *,
    symbols: list[str],
    start: date,
    end: date,
    transport: httpx.AsyncBaseTransport | None = None,
    db: Session | None = None,
    public_only: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    normalized = _normalize_symbols(symbols, settings.market_data_max_symbols)
    if start > end:
        raise MarketDataInputError("start date must be before end date")
    if (end - start).days > settings.market_data_max_history_days:
        raise MarketDataInputError(
            f"date range exceeds {settings.market_data_max_history_days} days"
        )

    display_mode = "public" if public_only else settings.resolved_market_data_display_mode
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
    provider_order = [
        item
        for item in _provider_order()
        if item in {"twelve_data", "alpha_vantage", "fmp", "yahoo_admin"}
    ]
    stored_payload = _stored_payload(
        db=db,
        symbols=normalized,
        start=start,
        end=end,
        provider_order=provider_order,
        display_mode=display_mode,
        public_display_allowlist=settings.market_data_public_display_allowlist_values,
    )
    if stored_payload:
        stored_payload["cache"] = "persistent_hit"
        _cache_set(
            cache_key,
            stored_payload,
            expires_at=now + settings.market_data_cache_ttl_seconds,
            max_entries=settings.market_data_cache_max_entries,
            now=now,
        )
        return deepcopy(stored_payload)

    if display_mode == "public":
        payload = _license_limited_payload(
            symbols=normalized,
            start=start,
            end=end,
            provider_order=provider_order,
            reason=(
                "No source-policy-approved stored daily bars are available for public display. "
                "Public routes do not spend provider quota or fetch live licensed market data on demand; "
                "use the TradingView widget for public visual market display until scheduled stored data is approved."
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
                    requested_end=end,
                    display_mode=display_mode,
                    public_display_allowed=True,
                ),
                "provider_budget_status": _provider_budget_status(provider),
                "symbols": normalized,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "series": series,
                "storage": store_market_history_series(
                    db,
                    provider_key=provider,
                    series=series,
                    requested_start=start,
                    requested_end=end,
                ),
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


async def refresh_market_history(
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
    provider_order = [
        item
        for item in _provider_order()
        if item in {"twelve_data", "alpha_vantage", "fmp", "yahoo_admin"}
    ]
    failures: list[str] = []
    quota_failure: ProviderLimitError | None = None
    non_quota_failure_seen = False
    for provider in provider_order:
        key = _api_key(provider)
        if not key:
            failures.append(f"{provider}: missing API key")
            continue
        try:
            series = await _fetch_provider(provider, key, normalized, start, end, transport, db)
        except ProviderLimitError as exc:
            quota_failure = quota_failure or exc
            detail = exc.error_class
            if exc.retry_after_seconds is not None:
                detail = f"{detail}; retry after {exc.retry_after_seconds}s"
            failures.append(f"{provider}: {detail}")
            continue
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            failures.append(f"{provider}: {exc}")
            non_quota_failure_seen = True
            continue
        if all(item["points"] for item in series):
            storage = store_market_history_series(
                db,
                provider_key=provider,
                series=series,
                requested_start=start,
                requested_end=end,
            )
            clear_market_data_cache()
            return {
                "status": "stored"
                if storage.get("stored", 0)
                else str(storage.get("quality_state") or "fetched_not_stored"),
                "provider": provider,
                "symbols": normalized,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "storage": storage,
                "warnings": failures,
            }
        failures.append(f"{provider}: one or more symbols returned no usable daily closes")
        non_quota_failure_seen = True
    if quota_failure is not None and not non_quota_failure_seen:
        mark_market_history_refresh_failed(
            db,
            symbols=normalized,
            provider_key=quota_failure.provider_key,
        )
        raise quota_failure
    mark_market_history_refresh_failed(
        db,
        symbols=normalized,
    )
    raise MarketDataUnavailable(
        "No configured market-data provider returned usable historical closes",
        provider_status=_provider_status()
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
            settings.market_data_api_key
            if settings.market_data_provider == "alpha_vantage"
            else None
        )
    if provider == "fmp":
        return settings.fmp_api_key or (
            settings.market_data_api_key if settings.market_data_provider == "fmp" else None
        )
    if provider == "yahoo_admin":
        return "enabled" if settings.yahoo_admin_enabled else None
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


def _stored_payload(
    *,
    db: Session | None,
    symbols: list[str],
    start: date,
    end: date,
    provider_order: list[str],
    display_mode: str,
    public_display_allowlist: set[str],
) -> dict[str, Any] | None:
    stored = load_stored_market_history(
        db,
        symbols=symbols,
        start=start,
        end=end,
        provider_order=provider_order,
        display_mode=display_mode,
        public_display_allowlist=public_display_allowlist,
    )
    if stored is None:
        return None
    fetched_at = datetime.now(timezone.utc)
    public_display_allowed = display_mode == "public"
    calculation_readiness = market_history_calculation_readiness(
        stored,
        symbols=symbols,
        start=start,
        end=end,
    )
    return {
        "status": "ok",
        "provider": stored.provider,
        "source_note": (
            "Stored normalized daily bars. Public requests read cached database rows only; "
            "they do not fetch provider data or spend provider quota."
        ),
        "cache": "miss",
        "display_mode": display_mode,
        "display_status": "stored_public_allowed" if public_display_allowed else "internal_stored",
        "data_freshness": _data_freshness(
            provider=stored.provider,
            series=stored.series,
            fetched_at=_parse_datetime(stored.fetched_at) or fetched_at,
            requested_end=end,
            display_mode=display_mode,
            public_display_allowed=public_display_allowed,
            source_observed_at=stored.source_observed_at,
            complete_through=stored.complete_through,
        ),
        "provider_budget_status": [
            budget for provider in provider_order for budget in _provider_budget_status(provider)
        ],
        "symbols": symbols,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "series": stored.series,
        "coverage": stored.coverage,
        "source_policy_digest": stored.source_policy_digest,
        "market_data_version": stored.data_version,
        "market_data_snapshot_id": stored.snapshot_id,
        "market_data_snapshot_ids": stored.snapshot_ids,
        "calculation_manifest": stored.calculation_manifest or [],
        "coherence_status": stored.coherence_status,
        "quality_state": stored.quality_state,
        "calculation_readiness": calculation_readiness.as_dict(),
        "warnings": stored.warnings,
    }


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
            "source_observed_at": None,
            "market_session_date": None,
            "complete_through": None,
            "hard_expires_at": None,
            "staleness_state": "license_limited",
            "calculation_eligible": False,
            "delayed_by_seconds": None,
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
    requested_end: date,
    display_mode: str,
    public_display_allowed: bool,
    source_observed_at: str | None = None,
    complete_through: str | None = None,
) -> dict[str, Any]:
    market_session_date = _latest_market_session_date(series)
    observed_at = source_observed_at or market_session_date
    complete = complete_through or market_session_date
    hard_expires_at = _history_hard_expires_at(complete)
    staleness_state = _history_staleness_state(complete, requested_end)
    calculation_eligible = staleness_state in {"active", "delayed"} and bool(complete)
    return {
        "provider": provider,
        "provider_timestamp": market_session_date,
        "fetched_at": fetched_at.isoformat(),
        "source_observed_at": observed_at,
        "market_session_date": market_session_date,
        "complete_through": complete,
        "hard_expires_at": hard_expires_at,
        "staleness_state": staleness_state,
        "calculation_eligible": calculation_eligible,
        "delayed_by_seconds": _history_delayed_by_seconds(complete, requested_end),
        "exchange_timezone": "America/New_York",
        "delay_label": _delay_label(provider, display_mode, market_session_date),
        "is_same_day_valid": False,
        "is_public_display_allowed": public_display_allowed,
        "staleness_reason": (
            "Daily candle history only; not same-day intraday data and not a realtime quote."
            if market_session_date
            else "Provider returned no market session date."
        ),
        "license_mode": "private_or_internal"
        if display_mode == "private"
        else "public_display_allowed",
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
    return (
        f"public-display allowed daily snapshot; latest session {market_session_date or 'pending'}"
    )


def _provider_source_url(provider: str) -> str:
    for item in ProviderLimitRegistry().as_dicts():
        if item["provider_key"] == provider and item["endpoint_key"] in {"daily_prices", "*"}:
            return _sanitize_public_source_url(str(item["source_url"]))
    return ""


def _sanitize_public_source_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port else host
    return parsed._replace(netloc=netloc, query="", fragment="").geturl()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _history_hard_expires_at(complete_through: str | None) -> str | None:
    parsed = _parse_date(complete_through)
    if parsed is None:
        return None
    expires = datetime.combine(parsed + timedelta(days=3), datetime_time(23, 59, 59), tzinfo=timezone.utc)
    return expires.isoformat()


def _history_staleness_state(complete_through: str | None, requested_end: date) -> str:
    parsed = _parse_date(complete_through)
    if parsed is None:
        return "unavailable"
    lag_days = max(0, (requested_end - parsed).days)
    if lag_days == 0:
        return "active"
    if lag_days <= 3:
        return "delayed"
    return "stale_fallback"


def _history_delayed_by_seconds(complete_through: str | None, requested_end: date) -> int | None:
    parsed = _parse_date(complete_through)
    if parsed is None:
        return None
    return max(0, (requested_end - parsed).days) * 86_400


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


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
    async with httpx.AsyncClient(timeout=timeout, limits=limits, transport=transport, trust_env=False) as client:
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
    elif provider == "yahoo_admin":
        points = await _fetch_yahoo_admin(client, symbol, start, end, db)
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
    idempotency_key = _provider_call_idempotency_key("twelve_data", symbol, start, end)
    response = await provider_request(
        client,
        "GET",
        "https://api.twelvedata.com/time_series",
        provider_key="twelve_data",
        endpoint_key="daily_prices",
        db=db,
        idempotency_key=idempotency_key,
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
    return _points_from_rows(
        values,
        date_field="datetime",
        close_fields=("close",),
        open_field="open",
        high_field="high",
        low_field="low",
        source_revision=_response_source_revision(response),
    )


async def _fetch_alpha_vantage(
    client: httpx.AsyncClient,
    key: str,
    symbol: str,
    start: date,
    end: date,
    db: Session | None,
) -> list[HistoryPoint]:
    idempotency_key = _provider_call_idempotency_key("alpha_vantage", symbol, start, end)
    response = await provider_request(
        client,
        "GET",
        "https://www.alphavantage.co/query",
        provider_key="alpha_vantage",
        endpoint_key="daily_prices",
        db=db,
        idempotency_key=idempotency_key,
        params={
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "compact",
            "apikey": key,
        },
    )
    payload = response.json()
    if "Note" in payload or "Information" in payload or "Error Message" in payload:
        message = str(
            payload.get("Note") or payload.get("Information") or payload.get("Error Message")
        )
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
        {
            "date": row_date,
            "open": row.get("1. open"),
            "high": row.get("2. high"),
            "low": row.get("3. low"),
            "close": row.get("4. close"),
            "volume": row.get("5. volume"),
        }
        for row_date, row in rows.items()
        if start.isoformat() <= row_date <= end.isoformat()
    ]
    return _points_from_rows(
        values,
        date_field="date",
        close_fields=("close",),
        open_field="open",
        high_field="high",
        low_field="low",
        descending=False,
        source_revision=_response_source_revision(response),
    )


async def _fetch_fmp(
    client: httpx.AsyncClient,
    key: str,
    symbol: str,
    start: date,
    end: date,
    db: Session | None,
) -> list[HistoryPoint]:
    idempotency_key = _provider_call_idempotency_key("fmp", symbol, start, end)
    response = await provider_request(
        client,
        "GET",
        "https://financialmodelingprep.com/stable/historical-price-eod/full",
        provider_key="fmp",
        endpoint_key="daily_prices",
        db=db,
        idempotency_key=idempotency_key,
        units={"request": 1, "byte": 500_000},
        params={"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(), "apikey": key},
    )
    payload = response.json()
    rows = payload.get("historical") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("FMP returned no historical rows")
    return _points_from_rows(
        rows,
        date_field="date",
        close_fields=("adjClose", "close"),
        adjusted_close_field="adjClose",
        open_field="open",
        high_field="high",
        low_field="low",
        source_revision=_response_source_revision(response),
    )


async def _fetch_yahoo_admin(
    client: httpx.AsyncClient,
    symbol: str,
    start: date,
    end: date,
    db: Session | None,
) -> list[HistoryPoint]:
    settings = get_settings()
    period1 = int(datetime.combine(start, datetime_time.min, tzinfo=timezone.utc).timestamp())
    period2 = int(
        datetime.combine(end + timedelta(days=1), datetime_time.min, tzinfo=timezone.utc).timestamp()
    )
    response = await provider_request(
        client,
        "GET",
        f"{settings.yahoo_admin_base_url.rstrip('/')}/v8/finance/chart/{symbol}",
        provider_key="yahoo_admin",
        endpoint_key="daily_prices",
        db=db,
        idempotency_key=_provider_call_idempotency_key("yahoo_admin", symbol, start, end),
        params={
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        },
    )
    payload = response.json()
    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict) or chart.get("error"):
        raise ValueError("Yahoo admin chart response did not include usable data")
    results = chart.get("result")
    if not isinstance(results, list) or not results:
        raise ValueError("Yahoo admin chart returned no result rows")
    result = results[0]
    if not isinstance(result, dict):
        raise ValueError("Yahoo admin chart returned malformed result")
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    if not isinstance(timestamps, list) or not isinstance(indicators, dict):
        raise ValueError("Yahoo admin chart returned no daily timestamps")
    quote_rows = indicators.get("quote")
    quote = quote_rows[0] if isinstance(quote_rows, list) and quote_rows else {}
    adj_rows = indicators.get("adjclose")
    adjusted = adj_rows[0] if isinstance(adj_rows, list) and adj_rows else {}
    if not isinstance(quote, dict):
        raise ValueError("Yahoo admin chart returned no quote rows")
    closes = quote.get("close") if isinstance(quote.get("close"), list) else []
    opens = quote.get("open") if isinstance(quote.get("open"), list) else []
    highs = quote.get("high") if isinstance(quote.get("high"), list) else []
    lows = quote.get("low") if isinstance(quote.get("low"), list) else []
    volumes = quote.get("volume") if isinstance(quote.get("volume"), list) else []
    adjusted_closes = (
        adjusted.get("adjclose")
        if isinstance(adjusted, dict) and isinstance(adjusted.get("adjclose"), list)
        else []
    )
    rows: list[dict[str, Any]] = []
    for index, raw_timestamp in enumerate(timestamps):
        try:
            row_date = datetime.fromtimestamp(int(raw_timestamp), tz=timezone.utc).date()
        except (TypeError, ValueError, OSError):
            continue
        if row_date < start or row_date > end:
            continue
        rows.append(
            {
                "date": row_date.isoformat(),
                "open": opens[index] if index < len(opens) else None,
                "high": highs[index] if index < len(highs) else None,
                "low": lows[index] if index < len(lows) else None,
                "close": closes[index] if index < len(closes) else None,
                "volume": volumes[index] if index < len(volumes) else None,
                "adjclose": adjusted_closes[index] if index < len(adjusted_closes) else None,
            }
        )
    return _points_from_rows(
        rows,
        date_field="date",
        close_fields=("adjclose", "close"),
        adjusted_close_field="adjclose",
        open_field="open",
        high_field="high",
        low_field="low",
        source_revision=_response_source_revision(response),
    )


def _provider_call_idempotency_key(provider: str, symbol: str, start: date, end: date) -> str:
    return f"market-history:{provider}:{symbol}:{start.isoformat()}:{end.isoformat()}"


def _response_source_revision(response: httpx.Response) -> str | None:
    reservation_id = response.extensions.get("provider_reservation_id")
    if reservation_id:
        return str(reservation_id)
    return response.headers.get("etag") or response.headers.get("last-modified")


def _points_from_rows(
    rows: list[dict[str, Any]],
    *,
    date_field: str,
    close_fields: tuple[str, ...],
    adjusted_close_field: str | None = None,
    open_field: str | None = None,
    high_field: str | None = None,
    low_field: str | None = None,
    descending: bool = False,
    source_revision: str | None = None,
) -> list[HistoryPoint]:
    points: list[HistoryPoint] = []
    for row in rows:
        row_date = str(row.get(date_field, ""))[:10]
        close_value = next(
            (row.get(field) for field in close_fields if row.get(field) is not None), None
        )
        if not row_date or close_value is None:
            continue
        try:
            close = float(close_value)
            volume = float(row["volume"]) if row.get("volume") not in (None, "") else None
            adjusted_close = (
                float(row[adjusted_close_field])
                if adjusted_close_field and row.get(adjusted_close_field) not in (None, "")
                else None
            )
            open_value = (
                float(row[open_field])
                if open_field and row.get(open_field) not in (None, "")
                else None
            )
            high = (
                float(row[high_field])
                if high_field and row.get(high_field) not in (None, "")
                else None
            )
            low = (
                float(row[low_field])
                if low_field and row.get(low_field) not in (None, "")
                else None
            )
        except (TypeError, ValueError):
            continue
        if close > 0:
            points.append(
                HistoryPoint(
                    date=row_date,
                    close=close,
                    volume=volume,
                    adjusted_close=adjusted_close,
                    open=open_value,
                    high=high,
                    low=low,
                    source_revision=source_revision,
                )
            )
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
        "yahoo_admin": "Private/admin-only chart history. Disabled by default and excluded from public snapshots.",
    }
    return notes.get(provider, "Configured provider")
