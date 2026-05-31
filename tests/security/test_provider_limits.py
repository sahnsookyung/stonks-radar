from __future__ import annotations

import json

import httpx
import pytest

from frw_api.services.provider_limits import (
    ERROR_QUOTA_EXHAUSTED,
    ERROR_RATE_LIMITED,
    LimitRule,
    ProviderEndpointLimit,
    ProviderLimitError,
    ProviderLimitRegistry,
    ProviderQuotaGuard,
    _finalize_market_data_quota,
    _reserve_market_data_quota,
    provider_request,
)


@pytest.fixture(autouse=True)
def reset_quota_guard():
    ProviderQuotaGuard._default = None
    ProviderQuotaGuard.reset_memory()
    yield
    ProviderQuotaGuard._default = None
    ProviderQuotaGuard.reset_memory()


def _guard(limit: int) -> ProviderQuotaGuard:
    registry = ProviderLimitRegistry(
        (
            ProviderEndpointLimit(
                provider_key="test_provider",
                endpoint_key="test_endpoint",
                rules=(
                    LimitRule(
                        unit="request",
                        window_seconds=60,
                        limit=limit,
                        source_limit="test",
                        conservative_limit="test",
                    ),
                ),
                source_url="https://example.test",
                source_checked_at="2026-05-25",
            ),
        )
    )
    return ProviderQuotaGuard(registry)


def test_quota_guard_denies_before_second_request():
    guard = _guard(1)
    guard.reserve(provider_key="test_provider", endpoint_key="test_endpoint")

    with pytest.raises(ProviderLimitError) as exc_info:
        guard.reserve(provider_key="test_provider", endpoint_key="test_endpoint")

    assert exc_info.value.error_class == ERROR_QUOTA_EXHAUSTED
    assert exc_info.value.retry_after_seconds is not None


def test_nvidia_nim_default_limit_is_40_rpm():
    limit = ProviderLimitRegistry().get("nvidia_nim", "chat_completions")

    assert limit is not None
    request_rules = [
        rule
        for rule in limit.rules
        if rule.unit == "request" and rule.window_seconds == 60
    ]
    assert request_rules
    assert request_rules[0].limit == 40


class _ScalarResult:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def mappings(self):
        return self

    def one_or_none(self):
        return self.value

    def first(self):
        return self.value


class _QuotaDb:
    def __init__(self, *, used: float = 0, max_requests_per_minute: int = 1):
        self.used = used
        self.max_requests_per_minute = max_requests_per_minute
        self.rows: list[dict] = []
        self.inserts: list[dict] = []
        self.updates: list[dict] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        if "to_regclass" in sql:
            return _ScalarResult(params["table_name"])
        if "from provider_runtime_state" in sql:
            return _ScalarResult(None)
        if "from market_data_provider_capability" in sql:
            return _ScalarResult(
                {
                    "max_requests_per_minute": self.max_requests_per_minute,
                    "max_requests_per_day": None,
                    "cost_per_request": 1,
                }
            )
        if "pg_advisory_xact_lock" in sql:
            return _ScalarResult(None)
        if (
            "select reservation_token" in sql
            and "from market_data_quota_reservation" in sql
        ):
            for row in self.rows:
                if (
                    row["provider_key"] == params["provider_key"]
                    and row["endpoint_key"] == params["endpoint_key"]
                    and row["partition_key"] == params["partition_key"]
                    and row["idempotency_key"] == params["idempotency_key"]
                    and row["window_start"] == params["window_start"]
                    and row["window_seconds"] == params["window_seconds"]
                    and row["status"] in {"reserved", "succeeded"}
                ):
                    return _ScalarResult(row["reservation_token"])
            return _ScalarResult(None)
        if "coalesce(sum(cost)" in sql:
            total = self.used
            for row in self.rows:
                if (
                    row["provider_key"] == params["provider_key"]
                    and row["endpoint_key"] == params["endpoint_key"]
                    and row["partition_key"] == params["partition_key"]
                    and row["window_start"] == params["window_start"]
                    and row["window_seconds"] == params["window_seconds"]
                    and row["status"] in {"reserved", "succeeded"}
                ):
                    total += row["cost"]
            return _ScalarResult(total)
        if "insert into market_data_quota_reservation" in sql:
            if "on conflict" in sql and params["idempotency_key"]:
                for row in self.rows:
                    if (
                        row["provider_key"] == params["provider_key"]
                        and row["endpoint_key"] == params["endpoint_key"]
                        and row["partition_key"] == params["partition_key"]
                        and row["idempotency_key"] == params["idempotency_key"]
                        and row["window_start"] == params["window_start"]
                        and row["window_seconds"] == params["window_seconds"]
                        and row["status"] in {"reserved", "succeeded"}
                    ):
                        return _ScalarResult(row["reservation_token"])
            self.inserts.append(params)
            self.rows.append(dict(params))
            return _ScalarResult(params.get("reservation_token"))
        if "update market_data_quota_reservation" in sql:
            self.updates.append(params)
            for row in self.rows:
                if (
                    row["reservation_token"] == params["reservation_token"]
                    and row["status"] == "reserved"
                ):
                    row["status"] = params["status"]
            return _ScalarResult(None)
        raise AssertionError(sql)


def test_market_data_quota_reservation_inserts_reserved_rows():
    db = _QuotaDb()

    reservation_id = _reserve_market_data_quota(
        db,
        provider_key="twelve_data",
        endpoint_key="daily_prices",
        partition_key="scheduled_public",
        units={"request": 1},
        idempotency_key="job-1",
    )

    assert reservation_id is not None
    assert db.inserts[0]["status"] == "reserved"
    assert db.inserts[0]["idempotency_key"] == "job-1"

    _finalize_market_data_quota(
        db,
        reservation_id=reservation_id,
        status="succeeded",
        error_class=None,
        retry_after_seconds=None,
        actual_units={"request": 1},
        details={},
    )

    assert db.updates[0]["status"] == "succeeded"


def test_market_data_quota_reservation_denies_over_conservative_cap():
    db = _QuotaDb(used=1)

    with pytest.raises(ProviderLimitError) as exc_info:
        _reserve_market_data_quota(
            db,
            provider_key="twelve_data",
            endpoint_key="daily_prices",
            partition_key="scheduled_public",
            units={"request": 1},
            idempotency_key="job-2",
        )

    assert exc_info.value.error_class == ERROR_QUOTA_EXHAUSTED
    assert db.inserts[0]["status"] == "deferred"


def test_market_data_quota_uses_preconservative_db_cap_once():
    db = _QuotaDb(used=9, max_requests_per_minute=10)

    reservation_id = _reserve_market_data_quota(
        db,
        provider_key="twelve_data",
        endpoint_key="daily_prices",
        partition_key="scheduled_public",
        units={"request": 1},
        idempotency_key="cap-once",
    )

    assert reservation_id is not None
    assert db.inserts[0]["status"] == "reserved"
    assert json.loads(db.inserts[0]["details"])["cap"] == 10.0


def test_market_data_quota_denies_at_preconservative_db_cap():
    db = _QuotaDb(used=10, max_requests_per_minute=10)

    with pytest.raises(ProviderLimitError) as exc_info:
        _reserve_market_data_quota(
            db,
            provider_key="twelve_data",
            endpoint_key="daily_prices",
            partition_key="scheduled_public",
            units={"request": 1},
            idempotency_key="cap-once-deny",
        )

    assert exc_info.value.error_class == ERROR_QUOTA_EXHAUSTED
    assert db.inserts[0]["status"] == "deferred"
    assert json.loads(db.inserts[0]["details"])["cap"] == 10.0


def test_market_data_quota_reservation_reuses_duplicate_idempotency():
    db = _QuotaDb(max_requests_per_minute=10)

    first = _reserve_market_data_quota(
        db,
        provider_key="twelve_data",
        endpoint_key="daily_prices",
        partition_key="scheduled_public",
        units={"request": 1},
        idempotency_key="same-job",
    )
    second = _reserve_market_data_quota(
        db,
        provider_key="twelve_data",
        endpoint_key="daily_prices",
        partition_key="scheduled_public",
        units={"request": 1},
        idempotency_key="same-job",
    )

    assert second == first
    assert len([row for row in db.rows if row["status"] == "reserved"]) == 1


def test_market_data_quota_skips_memory_redis_path():
    registry = ProviderLimitRegistry(
        (
            ProviderEndpointLimit(
                provider_key="twelve_data",
                endpoint_key="daily_prices",
                rules=(
                    LimitRule(
                        unit="request",
                        window_seconds=60,
                        limit=0,
                        source_limit="test",
                        conservative_limit="test",
                    ),
                ),
                source_url="https://example.test",
                source_checked_at="2026-05-25",
                public_display_allowed=False,
            ),
        )
    )
    guard = ProviderQuotaGuard(registry)

    reservation = guard.reserve(
        provider_key="twelve_data",
        endpoint_key="daily_prices",
        db=_QuotaDb(max_requests_per_minute=10),
        idempotency_key="db-first",
    )

    assert reservation.provider_key == "twelve_data"


@pytest.mark.asyncio
async def test_provider_request_preserves_retry_after_header():
    ProviderQuotaGuard._default = _guard(10)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, headers={"Retry-After": "7"}, json={"error": "slow down"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderLimitError) as exc_info:
            await provider_request(
                client,
                "GET",
                "https://provider.test/data",
                provider_key="test_provider",
                endpoint_key="test_endpoint",
            )

    assert exc_info.value.error_class == ERROR_RATE_LIMITED
    assert exc_info.value.retry_after_seconds == 7
