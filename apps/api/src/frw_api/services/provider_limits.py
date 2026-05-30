from __future__ import annotations

import email.utils
import json
import re
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.core.settings import get_settings

ERROR_RATE_LIMITED = "rate_limited"
ERROR_QUOTA_EXHAUSTED = "quota_exhausted"
ERROR_AUTH_INVALID = "auth_invalid"
ERROR_FORBIDDEN_SCOPE = "forbidden_scope"
ERROR_PAID_NOT_ALLOWED = "paid_not_allowed"
ERROR_UPSTREAM_5XX = "upstream_5xx"
ERROR_TIMEOUT = "timeout"
ERROR_SCHEMA_CHANGED = "schema_changed"
ERROR_NO_DATA = "no_data"
ERROR_UNSUPPORTED = "unsupported"

RETRYABLE_ERROR_CLASSES = {
    ERROR_RATE_LIMITED,
    ERROR_QUOTA_EXHAUSTED,
    ERROR_UPSTREAM_5XX,
    ERROR_TIMEOUT,
}

QUOTA_ERROR_CLASSES = {ERROR_RATE_LIMITED, ERROR_QUOTA_EXHAUSTED}

_PRODUCTION_ENV_NAMES = {"production", "prod"}
_DURATION_RE = re.compile(r"(?:(?P<minutes>\d+(?:\.\d+)?)m)?(?:(?P<seconds>\d+(?:\.\d+)?)s)?$")


@dataclass(frozen=True)
class LimitRule:
    unit: str
    window_seconds: int
    limit: float
    source_limit: str
    conservative_limit: str


@dataclass(frozen=True)
class ProviderEndpointLimit:
    provider_key: str
    endpoint_key: str
    rules: tuple[LimitRule, ...]
    source_url: str
    source_checked_at: str
    notes: str = ""
    attribution_required: bool = False
    public_display_allowed: bool = True


@dataclass(frozen=True)
class ProviderReservation:
    reservation_id: str
    provider_key: str
    endpoint_key: str
    partition_key: str
    units: dict[str, float]
    idempotency_key: str | None
    acquired_at: datetime


class ProviderLimitError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_class: str,
        provider_key: str,
        endpoint_key: str,
        retry_after_seconds: int | None = None,
        next_allowed_at: datetime | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.provider_key = provider_key
        self.endpoint_key = endpoint_key
        self.retry_after_seconds = retry_after_seconds
        self.next_allowed_at = next_allowed_at
        self.status_code = status_code

    @property
    def retryable(self) -> bool:
        return self.error_class in RETRYABLE_ERROR_CLASSES

    @property
    def quota_related(self) -> bool:
        return self.error_class in QUOTA_ERROR_CLASSES


class ProviderLimitRegistry:
    def __init__(self, limits: tuple[ProviderEndpointLimit, ...] = ()) -> None:
        self._limits = {
            (limit.provider_key, limit.endpoint_key): limit
            for limit in limits or DEFAULT_PROVIDER_LIMITS
        }
        if not limits:
            self._apply_settings_overrides()

    def _apply_settings_overrides(self) -> None:
        key = ("nvidia_nim", "chat_completions")
        limit = self._limits.get(key)
        if limit is None:
            return
        rpm = get_settings().nvidia_nim_rate_limit_per_minute
        self._limits[key] = replace(
            limit,
            rules=(
                _rule(
                    "request",
                    60,
                    rpm,
                    limit.rules[0].source_limit if limit.rules else "account/model-specific",
                    f"{rpm} requests/minute",
                ),
            ),
        )

    def get(self, provider_key: str, endpoint_key: str) -> ProviderEndpointLimit | None:
        return (
            self._limits.get((provider_key, endpoint_key))
            or self._limits.get((provider_key, "*"))
        )

    def public_display_allowed(self, provider_key: str, endpoint_key: str = "*") -> bool:
        limit = self.get(provider_key, endpoint_key)
        return True if limit is None else limit.public_display_allowed

    def as_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "provider_key": limit.provider_key,
                "endpoint_key": limit.endpoint_key,
                "rules": [rule.__dict__ for rule in limit.rules],
                "source_url": limit.source_url,
                "source_checked_at": limit.source_checked_at,
                "notes": limit.notes,
                "attribution_required": limit.attribution_required,
                "public_display_allowed": limit.public_display_allowed,
            }
            for limit in self._limits.values()
        ]


class ProviderQuotaGuard:
    _default: ProviderQuotaGuard | None = None
    _memory_lock = threading.RLock()
    _memory_counts: dict[str, tuple[float, float]] = {}

    def __init__(self, registry: ProviderLimitRegistry | None = None) -> None:
        self.registry = registry or ProviderLimitRegistry()

    @classmethod
    def default(cls) -> ProviderQuotaGuard:
        if cls._default is None:
            cls._default = cls()
        return cls._default

    @classmethod
    def reset_memory(cls) -> None:
        with cls._memory_lock:
            cls._memory_counts.clear()

    def reserve(
        self,
        *,
        provider_key: str,
        endpoint_key: str,
        units: dict[str, float] | None = None,
        partition_key: str = "scheduled_public",
        idempotency_key: str | None = None,
        db: Session | None = None,
    ) -> ProviderReservation:
        clean_units = _clean_units(units or {"request": 1})
        self._raise_if_circuit_open(
            provider_key=provider_key,
            endpoint_key=endpoint_key,
            partition_key=partition_key,
            db=db,
        )
        limit = self.registry.get(provider_key, endpoint_key)
        rules = _rules_for_units(limit, clean_units) if limit else []
        if rules:
            denied = self._reserve_rules(
                provider_key=provider_key,
                endpoint_key=endpoint_key,
                partition_key=partition_key,
                units=clean_units,
                rules=rules,
            )
            if denied is not None:
                retry_after = max(1, int(denied))
                reservation = ProviderReservation(
                    reservation_id=f"prv_{uuid4().hex}",
                    provider_key=provider_key,
                    endpoint_key=endpoint_key,
                    partition_key=partition_key,
                    units=clean_units,
                    idempotency_key=idempotency_key,
                    acquired_at=datetime.now(timezone.utc),
                )
                self.finalize(
                    reservation,
                    status="failed",
                    db=db,
                    error_class=ERROR_QUOTA_EXHAUSTED,
                    retry_after_seconds=retry_after,
                )
                raise ProviderLimitError(
                    f"{provider_key}/{endpoint_key} free quota exhausted",
                    error_class=ERROR_QUOTA_EXHAUSTED,
                    provider_key=provider_key,
                    endpoint_key=endpoint_key,
                    retry_after_seconds=retry_after,
                    next_allowed_at=datetime.now(timezone.utc)
                    + _seconds_delta(retry_after),
                )
        return ProviderReservation(
            reservation_id=f"prv_{uuid4().hex}",
            provider_key=provider_key,
            endpoint_key=endpoint_key,
            partition_key=partition_key,
            units=clean_units,
            idempotency_key=idempotency_key,
            acquired_at=datetime.now(timezone.utc),
        )

    def finalize(
        self,
        reservation: ProviderReservation,
        *,
        status: str,
        db: Session | None = None,
        error_class: str | None = None,
        status_code: int | None = None,
        retry_after_seconds: int | None = None,
        actual_units: dict[str, float] | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if db is None:
            return
        units = actual_units or reservation.units
        quantity = float(units.get("request") or 1)
        event_details = details or {}
        if retry_after_seconds is not None:
            event_details["retry_after_seconds"] = retry_after_seconds
        db.execute(
            text(
                """
                insert into provider_usage_event(
                  provider_key, endpoint_key, partition_key, status, error_class,
                  idempotency_key, unit, quantity, estimated_cost_usd,
                  reserved_units, actual_units, retry_after_seconds, details
                )
                values (
                  :provider_key, :endpoint_key, :partition_key, :status, :error_class,
                  :idempotency_key, 'request', :quantity, 0,
                  cast(:reserved_units as jsonb), cast(:actual_units as jsonb),
                  :retry_after_seconds, cast(:details as jsonb)
                )
                """
            ),
            {
                "provider_key": reservation.provider_key,
                "endpoint_key": reservation.endpoint_key,
                "partition_key": reservation.partition_key,
                "status": status,
                "error_class": error_class,
                "idempotency_key": reservation.idempotency_key,
                "quantity": quantity,
                "reserved_units": json.dumps(reservation.units),
                "actual_units": json.dumps(units),
                "retry_after_seconds": retry_after_seconds,
                "details": json.dumps(event_details),
            },
        )
        _upsert_runtime_state(
            db,
            provider_key=reservation.provider_key,
            endpoint_key=reservation.endpoint_key,
            partition_key=reservation.partition_key,
            status=status,
            error_class=error_class,
            status_code=status_code,
            retry_after_seconds=retry_after_seconds,
            details=event_details,
        )

    def _reserve_rules(
        self,
        *,
        provider_key: str,
        endpoint_key: str,
        partition_key: str,
        units: dict[str, float],
        rules: list[LimitRule],
    ) -> int | None:
        settings = get_settings()
        if settings.app_env.lower() in _PRODUCTION_ENV_NAMES:
            try:
                return _redis_reserve(settings.redis_url, provider_key, endpoint_key, partition_key, units, rules)
            except Exception as exc:  # noqa: BLE001 - quota store failure must not leak provider calls
                raise ProviderLimitError(
                    f"quota store unavailable for {provider_key}/{endpoint_key}: {exc.__class__.__name__}",
                    error_class=ERROR_QUOTA_EXHAUSTED,
                    provider_key=provider_key,
                    endpoint_key=endpoint_key,
                    retry_after_seconds=60,
                ) from exc
        return _memory_reserve(provider_key, endpoint_key, partition_key, units, rules)

    def _raise_if_circuit_open(
        self,
        *,
        provider_key: str,
        endpoint_key: str,
        partition_key: str,
        db: Session | None,
    ) -> None:
        if db is None:
            return
        row = (
            db.execute(
                text(
                    """
                    select circuit_state, next_allowed_at, last_error_class
                    from provider_runtime_state
                    where provider_key = :provider_key
                      and endpoint_key = :endpoint_key
                      and partition_key = :partition_key
                    """
                ),
                {
                    "provider_key": provider_key,
                    "endpoint_key": endpoint_key,
                    "partition_key": partition_key,
                },
            )
            .mappings()
            .first()
        )
        if not row or row["circuit_state"] != "open":
            return
        next_allowed_at = row["next_allowed_at"]
        if next_allowed_at is not None and next_allowed_at <= datetime.now(timezone.utc):
            return
        retry_after = None
        if next_allowed_at is not None:
            retry_after = max(1, int((next_allowed_at - datetime.now(timezone.utc)).total_seconds()))
        error_class = row["last_error_class"] or ERROR_RATE_LIMITED
        raise ProviderLimitError(
            f"{provider_key}/{endpoint_key} circuit is open",
            error_class=error_class,
            provider_key=provider_key,
            endpoint_key=endpoint_key,
            retry_after_seconds=retry_after,
            next_allowed_at=next_allowed_at,
        )


async def provider_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider_key: str,
    endpoint_key: str,
    db: Session | None = None,
    units: dict[str, float] | None = None,
    partition_key: str = "scheduled_public",
    idempotency_key: str | None = None,
    **kwargs: Any,
) -> httpx.Response:
    guard = ProviderQuotaGuard.default()
    reservation = guard.reserve(
        provider_key=provider_key,
        endpoint_key=endpoint_key,
        units=units,
        partition_key=partition_key,
        idempotency_key=idempotency_key,
        db=db,
    )
    try:
        response = await client.request(method, url, **kwargs)
    except httpx.TimeoutException as exc:
        guard.finalize(
            reservation,
            status="failed",
            db=db,
            error_class=ERROR_TIMEOUT,
            retry_after_seconds=30,
        )
        raise ProviderLimitError(
            f"{provider_key}/{endpoint_key} timed out",
            error_class=ERROR_TIMEOUT,
            provider_key=provider_key,
            endpoint_key=endpoint_key,
            retry_after_seconds=30,
        ) from exc
    except httpx.TransportError as exc:
        guard.finalize(
            reservation,
            status="failed",
            db=db,
            error_class=ERROR_UPSTREAM_5XX,
            retry_after_seconds=60,
        )
        raise ProviderLimitError(
            f"{provider_key}/{endpoint_key} transport error",
            error_class=ERROR_UPSTREAM_5XX,
            provider_key=provider_key,
            endpoint_key=endpoint_key,
            retry_after_seconds=60,
        ) from exc

    provider_error = provider_error_from_response(response, provider_key, endpoint_key)
    if provider_error is not None:
        guard.finalize(
            reservation,
            status="failed",
            db=db,
            error_class=provider_error.error_class,
            status_code=response.status_code,
            retry_after_seconds=provider_error.retry_after_seconds,
            actual_units=_actual_units(response, reservation.units),
        )
        raise provider_error

    guard.finalize(
        reservation,
        status="succeeded",
        db=db,
        status_code=response.status_code,
        actual_units=_actual_units(response, reservation.units),
    )
    return response


def provider_error_from_response(
    response: httpx.Response,
    provider_key: str,
    endpoint_key: str,
) -> ProviderLimitError | None:
    status_code = response.status_code
    if status_code < 400:
        return None
    retry_after = _retry_after_seconds(response)
    error_class = ERROR_SCHEMA_CHANGED
    if status_code == 429:
        error_class = ERROR_RATE_LIMITED
        retry_after = retry_after or 60
    elif status_code == 401:
        error_class = ERROR_AUTH_INVALID
    elif status_code == 402:
        error_class = ERROR_PAID_NOT_ALLOWED
    elif status_code == 403:
        error_class = ERROR_FORBIDDEN_SCOPE
    elif status_code == 404:
        error_class = ERROR_NO_DATA
    elif status_code in {408, 504}:
        error_class = ERROR_TIMEOUT
        retry_after = retry_after or 30
    elif status_code >= 500:
        error_class = ERROR_UPSTREAM_5XX
        retry_after = retry_after or 60
    message = f"{provider_key}/{endpoint_key} returned HTTP {status_code}"
    return ProviderLimitError(
        message,
        error_class=error_class,
        provider_key=provider_key,
        endpoint_key=endpoint_key,
        retry_after_seconds=retry_after,
        next_allowed_at=(
            datetime.now(timezone.utc) + _seconds_delta(retry_after)
            if retry_after is not None
            else None
        ),
        status_code=status_code,
    )


def provider_limits_snapshot() -> list[dict[str, Any]]:
    return ProviderLimitRegistry().as_dicts()


def _rule(
    unit: str,
    window_seconds: int,
    limit: float,
    source_limit: str,
    conservative_limit: str,
) -> LimitRule:
    return LimitRule(unit, window_seconds, limit, source_limit, conservative_limit)


def _limit(
    provider_key: str,
    endpoint_key: str,
    rules: tuple[LimitRule, ...],
    source_url: str,
    notes: str = "",
    *,
    attribution_required: bool = False,
    public_display_allowed: bool = True,
) -> ProviderEndpointLimit:
    return ProviderEndpointLimit(
        provider_key=provider_key,
        endpoint_key=endpoint_key,
        rules=rules,
        source_url=source_url,
        source_checked_at="2026-05-25",
        notes=notes,
        attribution_required=attribution_required,
        public_display_allowed=public_display_allowed,
    )


DEFAULT_PROVIDER_LIMITS: tuple[ProviderEndpointLimit, ...] = (
    _limit(
        "fred",
        "series_observations",
        (_rule("request", 1, 1, "2 requests/second", "1 request/second"),),
        "https://fred.stlouisfed.org/docs/api/fred/v2/errors.html",
    ),
    _limit(
        "bls",
        "timeseries",
        (
            _rule("request", 10, 40, "50 requests/10 seconds", "40 requests/10 seconds"),
            _rule("request", 86_400, 450, "500 requests/day", "450 requests/day"),
        ),
        "https://www.bls.gov/bls/api_features.htm",
    ),
    _limit(
        "eia",
        "v2_data",
        (
            _rule("request", 1, 2, "not fixed in docs", "2 requests/second"),
            _rule("record", 1, 5_000, "5,000 JSON rows/request", "5,000 records/request"),
        ),
        "https://www.eia.gov/opendata/documentation.php",
    ),
    _limit(
        "sec_edgar",
        "submissions",
        (_rule("request", 1, 5, "10 requests/second", "5 requests/second"),),
        "https://www.sec.gov/edgar/searchedgar/accessing-edgar-data.htm",
    ),
    _limit(
        "sec_edgar",
        "filing_document",
        (_rule("request", 1, 5, "10 requests/second", "5 requests/second"),),
        "https://www.sec.gov/edgar/searchedgar/accessing-edgar-data.htm",
    ),
    _limit(
        "sec_edgar",
        "ticker_map",
        (_rule("request", 60, 1, "periodically updated ticker file", "1 request/minute"),),
        "https://www.sec.gov/edgar/searchedgar/accessing-edgar-data.htm",
    ),
    _limit(
        "oge_disclosures",
        "index",
        (_rule("request", 2, 1, "undocumented endpoint; be polite", "1 request/2 seconds"),),
        "https://www.oge.gov/web/oge.nsf/Officials%20Individual%20Disclosures%20Search%20Collection?OpenForm=",
    ),
    _limit(
        "oge_disclosures",
        "document_pdf",
        (_rule("request", 2, 1, "undocumented endpoint; be polite", "1 request/2 seconds"),),
        "https://www.oge.gov/web/oge.nsf/Officials%20Individual%20Disclosures%20Search%20Collection?OpenForm=",
    ),
    _limit(
        "finra",
        "oauth_token",
        (_rule("request", 60, 30, "platform throttling applies", "30 requests/minute"),),
        "https://developer.finra.org/node/1146",
    ),
    _limit(
        "finra",
        "query_sync",
        (
            _rule("request", 60, 600, "1,200 requests/minute/IP", "600 requests/minute/IP"),
            _rule("record", 1, 5_000, "5,000 records/sync request", "5,000 records/request"),
            _rule("byte", 2_592_000, 8_000_000_000, "10GB/month/credential", "8GB/30 days"),
        ),
        "https://developer.finra.org/node/1146",
    ),
    _limit(
        "twelve_data",
        "daily_prices",
        (
            _rule("request", 60, 6, "8 API credits/minute", "6 requests/minute"),
            _rule("request", 86_400, 700, "800 API credits/day", "700 requests/day"),
        ),
        "https://support.twelvedata.com/en/articles/5335783-trial",
        attribution_required=True,
        public_display_allowed=False,
    ),
    _limit(
        "alpha_vantage",
        "daily_prices",
        (_rule("request", 86_400, 20, "25 requests/day", "20 requests/day"),),
        "https://www.alphavantage.co/premium/",
        public_display_allowed=False,
    ),
    _limit(
        "fmp",
        "daily_prices",
        (
            _rule("request", 86_400, 200, "250 calls/day", "200 calls/day"),
            _rule("byte", 2_592_000, 400_000_000, "500MB/30 days", "400MB/30 days"),
        ),
        "https://site.financialmodelingprep.com/pricing-plans",
        public_display_allowed=False,
    ),
    _limit(
        "finnhub",
        "*",
        (_rule("request", 60, 30, "60 API calls/minute", "30 API calls/minute"),),
        "https://finnhub.io/pricing",
        public_display_allowed=False,
    ),
    _limit(
        "nasdaq_data_link",
        "*",
        (
            _rule("request", 10, 100, "300 calls/10 seconds", "100 calls/10 seconds"),
            _rule("request", 600, 1_000, "2,000 calls/10 minutes", "1,000 calls/10 minutes"),
            _rule("request", 86_400, 10_000, "50,000 calls/day", "10,000 calls/day"),
        ),
        "https://docs.data.nasdaq.com/docs/rate-limits-1",
    ),
    _limit(
        "ecb",
        "data",
        (_rule("request", 60, 30, "not fixed in docs", "30 requests/minute"),),
        "https://data-api.ecb.europa.eu/service/data",
    ),
    _limit(
        "world_bank",
        "indicator",
        (_rule("request", 60, 30, "not fixed in docs", "30 requests/minute"),),
        "https://api.worldbank.org/v2",
    ),
    _limit(
        "gdelt",
        "doc",
        (_rule("request", 60, 10, "not fixed in docs", "10 requests/minute"),),
        "https://api.gdeltproject.org/api/v2/doc/doc",
        public_display_allowed=False,
    ),
    _limit(
        "google_news_rss",
        "search",
        (_rule("request", 60, 6, "undocumented RSS endpoint; use conservatively", "6 requests/minute"),),
        "https://news.google.com/rss",
        public_display_allowed=False,
    ),
    _limit(
        "yahoo_finance_rss",
        "rss",
        (_rule("request", 60, 6, "undocumented ticker RSS endpoint; use conservatively", "6 requests/minute"),),
        "https://feeds.finance.yahoo.com/rss/2.0/headline",
        notes="Ticker headline RSS is discovery metadata only; publisher pages remain source-of-record.",
        public_display_allowed=False,
    ),
    _limit(
        "federal_reserve",
        "fomc_calendar",
        (_rule("request", 60, 10, "not fixed in docs", "10 requests/minute"),),
        "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    ),
    _limit(
        "federal_reserve",
        "public_pages",
        (_rule("request", 60, 10, "not fixed in docs", "10 requests/minute"),),
        "https://www.federalreserve.gov/feeds/",
    ),
    _limit(
        "who",
        "rss",
        (_rule("request", 60, 6, "not fixed in docs", "6 requests/minute"),),
        "https://www.who.int/rss-feeds/",
    ),
    _limit(
        "company_ir",
        "rss",
        (_rule("request", 60, 6, "publisher-specific RSS; be polite", "6 requests/minute"),),
        "https://www.rssboard.org/rss-specification",
        notes="Per-publisher RSS/newsroom polling; official company pages are metadata-only and cached.",
    ),
    _limit(
        "company_ir",
        "html",
        (_rule("request", 60, 3, "publisher-specific web pages; be polite", "3 requests/minute"),),
        "https://www.rssboard.org/rss-autodiscovery",
        notes="Official company IR/newsroom HTML fallback only when RSS/API is unavailable.",
    ),
    _limit(
        "company_email",
        "webhook",
        (_rule("request", 60, 60, "local signed webhook; free inbound routing quota applies upstream", "60 emails/minute"),),
        "https://developers.cloudflare.com/email-routing/",
        notes="Inbound alert email is accepted only through signed webhooks and compressed local raw retention.",
    ),
    _limit(
        "gemini",
        "chat_completions",
        (
            _rule("request", 60, 10, "model/project-specific; view in AI Studio", "10 requests/minute"),
            _rule("request", 86_400, 800, "model/project-specific RPD", "800 requests/day"),
            _rule("token", 60, 200_000, "model/project-specific TPM", "200,000 tokens/minute"),
        ),
        "https://ai.google.dev/gemini-api/docs/rate-limits",
    ),
    _limit(
        "groq",
        "chat_completions",
        (
            _rule("request", 60, 20, "free plan often 30-60 RPM by model", "20 requests/minute"),
            _rule("request", 86_400, 200, "free plan model-specific RPD", "200 requests/day"),
            _rule("token", 60, 6_000, "free plan model-specific TPM", "6,000 tokens/minute"),
        ),
        "https://console.groq.com/docs/rate-limits",
    ),
    _limit(
        "cerebras",
        "chat_completions",
        (
            _rule("request", 60, 10, "free tier 10-30 RPM by model", "10 requests/minute"),
            _rule("request", 86_400, 100, "free tier 100-14,400 RPD by model", "100 requests/day"),
            _rule("token", 60, 60_000, "free tier 60K-64K TPM by model", "60,000 tokens/minute"),
        ),
        "https://inference-docs.cerebras.ai/support/rate-limits",
    ),
    _limit(
        "mistral",
        "chat_completions",
        (
            _rule("request", 1, 1, "account/model-specific RPS", "1 request/second"),
            _rule("token", 60, 10_000, "account/model-specific TPM", "10,000 tokens/minute"),
        ),
        "https://help.mistral.ai/en/articles/392924-how-do-api-rate-limits-work-and-how-can-i-increase-them",
    ),
    _limit(
        "openrouter",
        "chat_completions",
        (
            _rule("request", 60, 10, "20 free-model requests/minute", "10 requests/minute"),
            _rule("request", 86_400, 25, "50 free-model requests/day before credits", "25 requests/day"),
        ),
        "https://openrouter.ai/docs/api-reference/limits/",
    ),
    _limit(
        "nvidia_nim",
        "chat_completions",
        (
            _rule("request", 60, 40, "account/model-specific; no public header returned by live NIM probe", "40 requests/minute"),
        ),
        "https://docs.api.nvidia.com/nim/reference/minimaxai-minimax-m2.7",
        notes="NVIDIA NIM key is scoped to minimaxai/minimax-m2.7; enforce that model in the router.",
    ),
    _limit(
        "huggingface_hub",
        "*",
        (_rule("request", 300, 900, "1,000 API requests/5 minutes", "900 requests/5 minutes"),),
        "https://huggingface.co/docs/hub/en/rate-limits",
    ),
    _limit(
        "huggingface_inference",
        "chat_completions",
        (_rule("credit_usd", 2_592_000, 0.09, "$0.10 monthly free credits", "$0.09/30 days"),),
        "https://huggingface.co/docs/api-inference/en/rate-limits",
    ),
)


def _clean_units(units: dict[str, float]) -> dict[str, float]:
    clean: dict[str, float] = {}
    for key, value in units.items():
        amount = float(value)
        if amount > 0:
            clean[key] = amount
    return clean or {"request": 1}


def _rules_for_units(limit: ProviderEndpointLimit, units: dict[str, float]) -> list[LimitRule]:
    return [rule for rule in limit.rules if rule.unit in units]


def _memory_reserve(
    provider_key: str,
    endpoint_key: str,
    partition_key: str,
    units: dict[str, float],
    rules: list[LimitRule],
) -> int | None:
    now = time.time()
    with ProviderQuotaGuard._memory_lock:
        for key, (_, expires_at) in list(ProviderQuotaGuard._memory_counts.items()):
            if expires_at <= now:
                ProviderQuotaGuard._memory_counts.pop(key, None)
        for rule in rules:
            amount = units[rule.unit]
            bucket_key, expires_at = _bucket_key(
                provider_key,
                endpoint_key,
                partition_key,
                rule.unit,
                rule.window_seconds,
                now,
            )
            used, _ = ProviderQuotaGuard._memory_counts.get(bucket_key, (0.0, expires_at))
            if used + amount > rule.limit:
                return max(1, int(expires_at - now))
        for rule in rules:
            amount = units[rule.unit]
            bucket_key, expires_at = _bucket_key(
                provider_key,
                endpoint_key,
                partition_key,
                rule.unit,
                rule.window_seconds,
                now,
            )
            used, _ = ProviderQuotaGuard._memory_counts.get(bucket_key, (0.0, expires_at))
            ProviderQuotaGuard._memory_counts[bucket_key] = (used + amount, expires_at)
    return None


def _redis_reserve(
    redis_url: str,
    provider_key: str,
    endpoint_key: str,
    partition_key: str,
    units: dict[str, float],
    rules: list[LimitRule],
) -> int | None:
    import redis

    now = time.time()
    keys = []
    argv: list[str] = []
    for rule in rules:
        bucket_key, expires_at = _bucket_key(
            provider_key,
            endpoint_key,
            partition_key,
            rule.unit,
            rule.window_seconds,
            now,
        )
        keys.append(bucket_key)
        argv.extend([str(units[rule.unit]), str(rule.limit), str(max(1, int(expires_at - now)))])
    script = """
    for i = 1, #KEYS do
      local offset = (i - 1) * 3
      local current = tonumber(redis.call('GET', KEYS[i]) or '0')
      local amount = tonumber(ARGV[offset + 1])
      local limit = tonumber(ARGV[offset + 2])
      if current + amount > limit then
        local ttl = redis.call('TTL', KEYS[i])
        if ttl < 1 then
          ttl = tonumber(ARGV[offset + 3])
        end
        return {0, ttl}
      end
    end
    for i = 1, #KEYS do
      local offset = (i - 1) * 3
      redis.call('INCRBYFLOAT', KEYS[i], ARGV[offset + 1])
      redis.call('EXPIRE', KEYS[i], tonumber(ARGV[offset + 3]))
    end
    return {1, 0}
    """
    client = redis.Redis.from_url(redis_url, socket_timeout=1, socket_connect_timeout=1)
    allowed, ttl = client.eval(script, len(keys), *keys, *argv)
    return None if int(allowed) == 1 else int(ttl)


def _bucket_key(
    provider_key: str,
    endpoint_key: str,
    partition_key: str,
    unit: str,
    window_seconds: int,
    now: float,
) -> tuple[str, float]:
    bucket_start = int(now // window_seconds) * window_seconds
    expires_at = bucket_start + window_seconds
    key = f"provider_quota:{provider_key}:{endpoint_key}:{partition_key}:{unit}:{window_seconds}:{bucket_start}"
    return key, float(expires_at)


def _retry_after_seconds(response: httpx.Response) -> int | None:
    for header in (
        "retry-after",
        "x-ratelimit-reset-requests",
        "x-ratelimit-reset-tokens",
        "x-ratelimit-reset-requests-day",
        "x-ratelimit-reset-tokens-minute",
    ):
        value = response.headers.get(header)
        if not value:
            continue
        parsed = _parse_retry_value(value)
        if parsed is not None:
            return parsed
    return None


def _parse_retry_value(value: str) -> int | None:
    text_value = value.strip()
    try:
        return max(0, int(float(text_value)))
    except ValueError:
        pass
    match = _DURATION_RE.fullmatch(text_value)
    if match and match.group(0):
        minutes = float(match.group("minutes") or 0)
        seconds = float(match.group("seconds") or 0)
        return int(minutes * 60 + seconds)
    try:
        retry_at = email.utils.parsedate_to_datetime(text_value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0, int((retry_at - datetime.now(timezone.utc)).total_seconds()))


def _actual_units(response: httpx.Response, reserved_units: dict[str, float]) -> dict[str, float]:
    units = dict(reserved_units)
    units["byte"] = max(float(units.get("byte", 0)), float(len(response.content or b"")))
    return units


def _upsert_runtime_state(
    db: Session,
    *,
    provider_key: str,
    endpoint_key: str,
    partition_key: str,
    status: str,
    error_class: str | None,
    status_code: int | None,
    retry_after_seconds: int | None,
    details: dict[str, Any],
) -> None:
    if status == "succeeded":
        db.execute(
            text(
                """
                insert into provider_runtime_state(
                  provider_key, endpoint_key, partition_key, circuit_state,
                  last_success_at, failure_count, details
                )
                values (:provider_key, :endpoint_key, :partition_key, 'closed', now(), 0, cast(:details as jsonb))
                on conflict (provider_key, endpoint_key, partition_key) do update
                set circuit_state = 'closed',
                    next_allowed_at = null,
                    last_success_at = now(),
                    failure_count = 0,
                    last_error_class = null,
                    last_status_code = :status_code,
                    details = excluded.details,
                    updated_at = now()
                """
            ),
            {
                "provider_key": provider_key,
                "endpoint_key": endpoint_key,
                "partition_key": partition_key,
                "status_code": status_code,
                "details": json.dumps(details),
            },
        )
        return
    next_allowed_at = (
        datetime.now(timezone.utc) + _seconds_delta(retry_after_seconds)
        if retry_after_seconds is not None
        else None
    )
    open_indefinitely = error_class in {ERROR_AUTH_INVALID, ERROR_FORBIDDEN_SCOPE, ERROR_PAID_NOT_ALLOWED}
    circuit_state = "open" if open_indefinitely or retry_after_seconds is not None else "closed"
    db.execute(
        text(
            """
            insert into provider_runtime_state(
              provider_key, endpoint_key, partition_key, circuit_state,
              next_allowed_at, last_failure_at, last_error_class, last_status_code,
              failure_count, details
            )
            values (
              :provider_key, :endpoint_key, :partition_key, :circuit_state,
              :next_allowed_at, now(), :error_class, :status_code, 1, cast(:details as jsonb)
            )
            on conflict (provider_key, endpoint_key, partition_key) do update
            set circuit_state = :circuit_state,
                next_allowed_at = :next_allowed_at,
                last_failure_at = now(),
                last_error_class = :error_class,
                last_status_code = :status_code,
                failure_count = provider_runtime_state.failure_count + 1,
                details = excluded.details,
                updated_at = now()
            """
        ),
        {
            "provider_key": provider_key,
            "endpoint_key": endpoint_key,
            "partition_key": partition_key,
            "circuit_state": circuit_state,
            "next_allowed_at": next_allowed_at,
            "error_class": error_class,
            "status_code": status_code,
            "details": json.dumps(details),
        },
    )


def _seconds_delta(seconds: int | None):
    from datetime import timedelta

    return timedelta(seconds=seconds or 0)
