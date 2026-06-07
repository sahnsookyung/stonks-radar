from __future__ import annotations

import ast
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from frw_api.core.settings import get_settings
from frw_api.routers import public as public_router
from frw_api.services.provider_limits import (
    ERROR_RATE_LIMITED,
    ProviderLimitError,
    ProviderQuotaGuard,
)
from frw_api.services.market_data import (
    MarketDataInputError,
    _sanitize_public_source_url,
    _stored_payload,
    clear_market_data_cache,
    fetch_market_history,
    refresh_market_history,
)
from frw_api.services.market_history_store import (
    MarketHistoryCalculationNotReady,
    MarketCalendarCoverageError,
    StoredHistoryResult,
    _staging_metadata,
    expected_market_sessions,
    load_stored_market_history,
    mark_market_history_refresh_failed,
    market_history_calculation_readiness,
    require_calculation_ready_market_history,
    store_market_history_series,
    validate_market_history_batch,
)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    clear_market_data_cache()
    ProviderQuotaGuard.reset_memory()
    yield
    clear_market_data_cache()
    ProviderQuotaGuard.reset_memory()
    get_settings.cache_clear()


def test_market_history_staging_metadata_excludes_price_payloads():
    payload = _staging_metadata(
        provider_key="twelve_data",
        symbol="AAPL",
        points=[
            {
                "date": "2026-01-02",
                "open": 99.0,
                "high": 101.0,
                "low": 98.0,
                "close": 100.0,
            },
            {
                "date": "2026-01-03",
                "open": 100.0,
                "high": 103.0,
                "low": 99.0,
                "close": 102.0,
            },
        ],
        source_hash="hash",
        source_policy_digest="policy",
    )

    assert payload["point_count"] == 2
    assert payload["first_date"] == "2026-01-02"
    assert payload["latest_date"] == "2026-01-03"
    assert payload["payload_retained"] is False
    assert "points" not in payload
    assert "close" not in payload


class _Result:
    def __init__(self, value=None, rows=None, rowcount=0):
        self.value = value
        self.rows = rows or []
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def mappings(self):
        return self

    def one_or_none(self):
        return self.value

    def all(self):
        return self.rows


class _StoredHistoryDb:
    def __init__(self, rows, current_rows=None):
        self.rows = rows
        self.current_rows = current_rows

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        if "to_regclass" in sql:
            return _Result(params["table_name"])
        if "from market_data_snapshot_current" in sql:
            if self.current_rows is None:
                raise AssertionError(sql)
            return _Result(rows=self.current_rows)
        if "from market_price_bar bar" in sql:
            return _Result(rows=self.rows)
        raise AssertionError(sql)

    def rollback(self):
        return None


class _CurrentSnapshotUpdateDb:
    def __init__(self):
        self.update_params = None

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        if "to_regclass" in sql:
            return _Result(params["table_name"])
        if "update market_data_snapshot_current" in sql:
            self.update_params = dict(params)
            return _Result(rowcount=2)
        raise AssertionError(sql)


def _stored_row(
    price_date,
    *,
    snapshot_id,
    close,
    symbol="AAPL",
    currency="USD",
    exchange="NASDAQ",
    timezone_name="America/New_York",
    fetch_completed_at=None,
    source_hash="sha256:test",
):
    return {
        "symbol": symbol,
        "price_date": price_date,
        "provider_key": "twelve_data",
        "close": close,
        "adjusted_close": None,
        "volume": 1000,
        "currency_code": currency,
        "exchange": exchange,
        "timezone": timezone_name,
        "provider_price_timestamp": None,
        "ingested_at": datetime(2026, 1, 6, tzinfo=timezone.utc),
        "fetch_completed_at": fetch_completed_at,
        "source_revision": None,
        "source_hash": source_hash,
        "quality_state": "valid",
        "market_data_snapshot_id": snapshot_id,
        "source_policy_json": {"raw_public_allowed": True},
        "quality_json": {},
        "snapshot_batch_id": "batch",
        "snapshot_provider_revision": "revision",
        "snapshot_content_hash": "hash",
        "snapshot_quality_state": "valid",
        "snapshot_candidate_id": 123,
    }


def test_mark_market_history_refresh_failed_marks_current_snapshots_only():
    db = _CurrentSnapshotUpdateDb()

    updated = mark_market_history_refresh_failed(
        db,
        symbols=["aapl", "AAPL", "MSFT"],
        provider_key="twelve_data",
    )

    assert updated == 2
    assert db.update_params["symbols"] == ("AAPL", "MSFT")
    assert db.update_params["provider_key"] == "twelve_data"
    assert db.update_params["endpoint_key"] == "daily_prices"
    assert db.update_params["window_key"] == "rolling_3y"


def test_load_stored_market_history_surfaces_mixed_snapshot_coherence():
    stored = load_stored_market_history(
        _StoredHistoryDb(
            [
                _stored_row(date(2026, 1, 2), snapshot_id="snapshot-a", close=100.0),
                _stored_row(date(2026, 1, 5), snapshot_id="snapshot-b", close=101.0),
            ]
        ),
        symbols=["AAPL"],
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        provider_order=["twelve_data"],
        display_mode="private",
        public_display_allowlist=set(),
    )

    assert stored is not None
    assert stored.snapshot_id is None
    assert stored.snapshot_ids == ["snapshot-a", "snapshot-b"]
    assert stored.coherence_status == "mixed_snapshots"
    assert any(
        "multiple market data snapshots" in warning for warning in stored.warnings
    )


def test_market_history_calculation_readiness_requires_single_complete_snapshot():
    stored = load_stored_market_history(
        _StoredHistoryDb(
            [
                _stored_row(date(2026, 1, 2), snapshot_id="snapshot-a", close=100.0),
                _stored_row(date(2026, 1, 5), snapshot_id="snapshot-a", close=101.0),
            ]
        ),
        symbols=["AAPL"],
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),
        provider_order=["twelve_data"],
        display_mode="private",
        public_display_allowlist=set(),
    )

    readiness = market_history_calculation_readiness(
        stored,
        symbols=["AAPL"],
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),
    )

    assert readiness.ready is True
    assert readiness.reason is None
    assert readiness.snapshot_id == "snapshot-a"
    assert readiness.missing_sessions == {}
    assert readiness.required_fx_pairs == []


def test_market_history_calculation_readiness_rejects_mixed_snapshots():
    stored = load_stored_market_history(
        _StoredHistoryDb(
            [
                _stored_row(date(2026, 1, 2), snapshot_id="snapshot-a", close=100.0),
                _stored_row(date(2026, 1, 5), snapshot_id="snapshot-b", close=101.0),
            ]
        ),
        symbols=["AAPL"],
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),
        provider_order=["twelve_data"],
        display_mode="private",
        public_display_allowlist=set(),
    )

    readiness = market_history_calculation_readiness(
        stored,
        symbols=["AAPL"],
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),
    )

    assert readiness.ready is False
    assert readiness.reason == "market_history_mixed_snapshots"
    assert readiness.snapshot_id is None


def test_market_history_readiness_allows_current_per_symbol_snapshots():
    stored = load_stored_market_history(
        _StoredHistoryDb(
            [
                _stored_row(date(2026, 1, 2), snapshot_id="snapshot-a", close=100.0, symbol="AAPL"),
                _stored_row(date(2026, 1, 5), snapshot_id="snapshot-a", close=101.0, symbol="AAPL"),
                _stored_row(date(2026, 1, 2), snapshot_id="snapshot-b", close=200.0, symbol="MSFT"),
                _stored_row(date(2026, 1, 5), snapshot_id="snapshot-b", close=202.0, symbol="MSFT"),
            ],
            current_rows=[
                {
                    "symbol": "AAPL",
                    "provider_key": "twelve_data",
                    "snapshot_id": "snapshot-a",
                    "previous_snapshot_id": None,
                    "requested_start": date(2023, 1, 5),
                    "requested_end": date(2026, 1, 5),
                    "price_start": date(2023, 1, 5),
                    "complete_through": date(2026, 1, 5),
                    "source_observed_at": datetime(2026, 1, 6, tzinfo=timezone.utc),
                    "hard_expires_at": datetime(2026, 1, 9, tzinfo=timezone.utc),
                    "staleness_state": "active",
                    "calculation_eligible": True,
                    "source_policy_digest": "policy",
                    "content_hash": "hash-a",
                    "updated_at": datetime(2026, 1, 6, tzinfo=timezone.utc),
                },
                {
                    "symbol": "MSFT",
                    "provider_key": "twelve_data",
                    "snapshot_id": "snapshot-b",
                    "previous_snapshot_id": None,
                    "requested_start": date(2023, 1, 5),
                    "requested_end": date(2026, 1, 5),
                    "price_start": date(2023, 1, 5),
                    "complete_through": date(2026, 1, 5),
                    "source_observed_at": datetime(2026, 1, 6, tzinfo=timezone.utc),
                    "hard_expires_at": datetime(2026, 1, 9, tzinfo=timezone.utc),
                    "staleness_state": "active",
                    "calculation_eligible": True,
                    "source_policy_digest": "policy",
                    "content_hash": "hash-b",
                    "updated_at": datetime(2026, 1, 6, tzinfo=timezone.utc),
                },
            ],
        ),
        symbols=["AAPL", "MSFT"],
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),
        provider_order=["twelve_data"],
        display_mode="private",
        public_display_allowlist=set(),
    )

    assert stored is not None
    assert stored.coherence_status == "current_snapshots"
    assert stored.snapshot_ids == ["snapshot-a", "snapshot-b"]
    readiness = market_history_calculation_readiness(
        stored,
        symbols=["AAPL", "MSFT"],
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),
    )
    assert readiness.ready is True
    assert readiness.reason is None


def test_current_snapshot_table_blocks_stale_symbol_fallback():
    stored = load_stored_market_history(
        _StoredHistoryDb(
            [
                _stored_row(date(2026, 1, 2), snapshot_id="old-aapl", close=100.0, symbol="AAPL"),
                _stored_row(date(2026, 1, 5), snapshot_id="old-aapl", close=101.0, symbol="AAPL"),
            ],
            current_rows=[],
        ),
        symbols=["AAPL"],
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),
        provider_order=["twelve_data"],
        display_mode="private",
        public_display_allowlist=set(),
    )

    assert stored is None


def test_require_calculation_ready_market_history_raises_for_mixed_snapshots():
    stored = load_stored_market_history(
        _StoredHistoryDb(
            [
                _stored_row(date(2026, 1, 2), snapshot_id="snapshot-a", close=100.0),
                _stored_row(date(2026, 1, 5), snapshot_id="snapshot-b", close=101.0),
            ]
        ),
        symbols=["AAPL"],
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),
        provider_order=["twelve_data"],
        display_mode="private",
        public_display_allowlist=set(),
    )

    with pytest.raises(MarketHistoryCalculationNotReady) as exc_info:
        require_calculation_ready_market_history(
            stored,
            symbols=["AAPL"],
            start=date(2026, 1, 2),
            end=date(2026, 1, 5),
        )

    assert exc_info.value.readiness.reason == "market_history_mixed_snapshots"


def test_market_history_calculation_readiness_reports_missing_sessions():
    stored = load_stored_market_history(
        _StoredHistoryDb(
            [_stored_row(date(2026, 1, 2), snapshot_id="snapshot-a", close=100.0)]
        ),
        symbols=["AAPL"],
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),
        provider_order=["twelve_data"],
        display_mode="private",
        public_display_allowlist=set(),
    )

    readiness = market_history_calculation_readiness(
        stored,
        symbols=["AAPL"],
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),
    )

    assert readiness.ready is False
    assert readiness.reason == "missing_market_sessions"
    assert readiness.missing_sessions == {"AAPL": ["2026-01-05"]}


def test_market_history_calculation_readiness_requires_fx_for_non_base_currency():
    stored = load_stored_market_history(
        _StoredHistoryDb(
            [
                _stored_row(
                    date(2026, 1, 2),
                    snapshot_id="snapshot-kr",
                    close=80000.0,
                    symbol="005930.KS",
                    currency="KRW",
                    exchange="KRX",
                    timezone_name="Asia/Seoul",
                ),
                _stored_row(
                    date(2026, 1, 5),
                    snapshot_id="snapshot-kr",
                    close=80500.0,
                    symbol="005930.KS",
                    currency="KRW",
                    exchange="KRX",
                    timezone_name="Asia/Seoul",
                ),
            ]
        ),
        symbols=["005930.KS"],
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),
        provider_order=["twelve_data"],
        display_mode="private",
        public_display_allowlist=set(),
    )

    readiness = market_history_calculation_readiness(
        stored,
        symbols=["005930.KS"],
        start=date(2026, 1, 2),
        end=date(2026, 1, 5),
        base_currency="USD",
    )

    assert readiness.ready is False
    assert readiness.reason == "fx_coverage_unsupported"
    assert readiness.fx_coverage_status == "unsupported_no_fx_snapshot_store"
    assert readiness.required_fx_pairs == [{"from": "KRW", "to": "USD"}]


def test_backend_market_history_consumers_are_explicitly_allowlisted():
    allowed_call_sites = {
        ("apps/api/src/frw_api/routers/public.py", "fetch_market_history"),
        ("apps/api/src/frw_api/services/market_data.py", "load_stored_market_history"),
        (
            "apps/api/src/frw_api/services/market_data.py",
            "market_history_calculation_readiness",
        ),
        (
            "apps/api/src/frw_api/services/market_history_store.py",
            "market_history_calculation_readiness",
        ),
        (
            "apps/api/src/frw_api/services/market_history_store.py",
            "require_calculation_ready_market_history",
        ),
        ("apps/worker/src/frw_worker/tasks.py", "refresh_market_history"),
    }
    watched_calls = {
        "fetch_market_history",
        "refresh_market_history",
        "load_stored_market_history",
        "market_history_calculation_readiness",
        "require_calculation_ready_market_history",
    }

    unexpected = [
        (path, name)
        for path, name in _backend_market_history_call_sites(watched_calls)
        if (path, name) not in allowed_call_sites
    ]

    assert unexpected == []


def test_stored_payload_exposes_coherence_warning():
    payload = _stored_payload(
        db=_StoredHistoryDb(
            [
                _stored_row(date(2026, 1, 2), snapshot_id="snapshot-a", close=100.0),
                _stored_row(date(2026, 1, 5), snapshot_id="snapshot-b", close=101.0),
            ]
        ),
        symbols=["AAPL"],
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        provider_order=["twelve_data"],
        display_mode="private",
        public_display_allowlist=set(),
    )

    assert payload is not None
    assert payload["coherence_status"] == "mixed_snapshots"
    assert payload["market_data_snapshot_ids"] == ["snapshot-a", "snapshot-b"]
    assert payload["market_data_snapshot_id"] is None
    assert payload["calculation_readiness"]["ready"] is False
    assert (
        payload["calculation_readiness"]["reason"] == "market_history_mixed_snapshots"
    )
    assert payload["warnings"]
    assert payload["cache"] == "miss"
    assert payload["data_freshness"]["source_observed_at"] == "2026-01-05"
    assert payload["data_freshness"]["complete_through"] == "2026-01-05"
    assert payload["data_freshness"]["staleness_state"] == "stale_fallback"
    assert payload["data_freshness"]["calculation_eligible"] is False
    assert payload["data_freshness"]["delayed_by_seconds"] == 26 * 86_400
    assert payload["calculation_manifest"][0]["candidate_id"] == 123
    assert payload["calculation_manifest"][0]["content_hash"] == "sha256:test"


def test_stored_payload_uses_fetch_completed_timestamp_when_available():
    payload = _stored_payload(
        db=_StoredHistoryDb(
            [
                _stored_row(
                    date(2026, 1, 2),
                    snapshot_id="snapshot-a",
                    close=100.0,
                    fetch_completed_at=datetime(2026, 1, 7, 3, 30, tzinfo=timezone.utc),
                ),
            ]
        ),
        symbols=["AAPL"],
        start=date(2026, 1, 2),
        end=date(2026, 1, 2),
        provider_order=["twelve_data"],
        display_mode="private",
        public_display_allowlist=set(),
    )

    assert payload is not None
    assert payload["data_freshness"]["fetched_at"] == "2026-01-07T03:30:00+00:00"
    assert payload["data_freshness"]["staleness_state"] == "active"
    assert payload["data_freshness"]["calculation_eligible"] is True
    assert payload["data_freshness"]["delayed_by_seconds"] == 0


def test_public_source_url_sanitizer_removes_query_and_fragment():
    assert (
        _sanitize_public_source_url("https://api.example.test/path?apikey=secret#frag")
        == "https://api.example.test/path"
    )
    assert (
        _sanitize_public_source_url("https://user:pass@api.example.test/path?apikey=secret")
        == "https://api.example.test/path"
    )
    assert _sanitize_public_source_url("file:///tmp/key") == ""


def test_public_market_history_cache_headers_do_not_cache_private_payloads():
    headers = public_router._market_history_cache_headers(
        {
            "status": "ok",
            "display_mode": "private",
            "provider": "stored_normalized_daily_bars",
        }
    )

    assert headers["Cache-Control"] == "no-store"


@pytest.mark.asyncio
async def test_fetch_market_history_uses_twelve_data(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "market_data_provider_order", "twelve_data")
    monkeypatch.setattr(settings, "twelve_data_api_key", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.twelvedata.com"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "values": [
                    {"datetime": "2026-01-02", "close": "100.0"},
                    {"datetime": "2026-01-03", "close": "102.0"},
                ],
            },
        )

    payload = await fetch_market_history(
        symbols=["AAPL"],
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        transport=httpx.MockTransport(handler),
    )

    assert payload["provider"] == "twelve_data"
    assert payload["series"][0]["symbol"] == "AAPL"
    assert payload["series"][0]["points"][1]["close"] == 102.0


@pytest.mark.asyncio
async def test_private_yahoo_admin_fetch_uses_chart_endpoint(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "market_data_display_mode", "private")
    monkeypatch.setattr(settings, "market_data_provider_order", "yahoo_admin")
    monkeypatch.setattr(settings, "yahoo_admin_enabled", True)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "query1.finance.yahoo.com"
        assert request.url.path == "/v8/finance/chart/AAPL"
        return httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "timestamp": [1767398400, 1767657600],
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [99.0, 101.0],
                                        "high": [101.0, 103.0],
                                        "low": [98.0, 100.0],
                                        "close": [100.0, 102.0],
                                        "volume": [1000, 1100],
                                    }
                                ],
                                "adjclose": [{"adjclose": [100.0, 102.0]}],
                            },
                        }
                    ],
                    "error": None,
                }
            },
        )

    payload = await fetch_market_history(
        symbols=["AAPL"],
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        transport=httpx.MockTransport(handler),
    )

    assert payload["provider"] == "yahoo_admin"
    assert payload["display_mode"] == "private"
    assert payload["series"][0]["points"][0]["date"] == "2026-01-03"
    assert payload["series"][0]["points"][1]["close"] == 102.0


@pytest.mark.asyncio
async def test_fetch_market_history_rejects_bad_symbol():
    with pytest.raises(MarketDataInputError):
        await fetch_market_history(
            symbols=["AAPL;DROP"],
            start=date(2026, 1, 1),
            end=date(2026, 1, 31),
        )


@pytest.mark.asyncio
async def test_market_history_cache_is_bounded(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "market_data_provider_order", "twelve_data")
    monkeypatch.setattr(settings, "twelve_data_api_key", "test-key")
    monkeypatch.setattr(settings, "market_data_cache_max_entries", 1)

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        symbol = request.url.params["symbol"]
        calls.append(symbol)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "values": [
                    {"datetime": "2026-01-02", "close": "100.0"},
                    {"datetime": "2026-01-03", "close": "102.0"},
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    await fetch_market_history(
        symbols=["AAPL"],
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        transport=transport,
    )
    await fetch_market_history(
        symbols=["MSFT"],
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        transport=transport,
    )
    payload = await fetch_market_history(
        symbols=["AAPL"],
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        transport=transport,
    )

    assert payload["cache"] == "miss"
    assert calls == ["AAPL", "MSFT", "AAPL"]


@pytest.mark.asyncio
async def test_public_market_history_blocks_license_limited_providers(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "market_data_display_mode", "public")
    monkeypatch.setattr(settings, "market_data_provider_order", "twelve_data")
    monkeypatch.setattr(settings, "twelve_data_api_key", "test-key")

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500)

    payload = await fetch_market_history(
        symbols=["AAPL"],
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        transport=httpx.MockTransport(handler),
    )

    assert payload["status"] == "license_limited"
    assert payload["provider"] == "tradingview_widget_only"
    assert payload["series"] == [{"symbol": "AAPL", "points": []}]
    assert payload["data_freshness"]["is_public_display_allowed"] is False
    assert payload["data_freshness"]["license_mode"] == "public_display_not_allowed"
    assert calls == []


@pytest.mark.asyncio
async def test_market_history_cache_separates_public_display_allowlist(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "market_data_display_mode", "public")
    monkeypatch.setattr(settings, "market_data_provider_order", "twelve_data")
    monkeypatch.setattr(settings, "twelve_data_api_key", "test-key")

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "values": [
                    {"datetime": "2026-01-02", "close": "100.0"},
                    {"datetime": "2026-01-03", "close": "102.0"},
                ],
            },
        )

    limited = await fetch_market_history(
        symbols=["AAPL"],
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(settings, "market_data_public_display_allowlist", "twelve_data")
    allowed = await fetch_market_history(
        symbols=["AAPL"],
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        transport=httpx.MockTransport(handler),
    )

    assert limited["status"] == "license_limited"
    assert allowed["status"] == "license_limited"
    assert allowed["cache"] == "miss"
    assert allowed["data_freshness"]["is_public_display_allowed"] is False
    assert calls == []


@pytest.mark.asyncio
async def test_refresh_market_history_preserves_quota_wait_classification(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        settings, "market_data_provider_order", "twelve_data,alpha_vantage"
    )
    monkeypatch.setattr(settings, "twelve_data_api_key", None)
    monkeypatch.setattr(settings, "alpha_vantage_api_key", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Note": "rate limit reached"})

    with pytest.raises(ProviderLimitError) as exc_info:
        await refresh_market_history(
            symbols=["AAPL"],
            start=date(2026, 1, 1),
            end=date(2026, 1, 31),
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.error_class == ERROR_RATE_LIMITED
    assert exc_info.value.quota_related is True


def test_market_history_validation_quarantines_ohlc_invariant():
    result = validate_market_history_batch(
        [
            {
                "symbol": "AAPL",
                "price_date": date(2026, 1, 2),
                "provider_key": "twelve_data",
                "open": 100.0,
                "high": 99.0,
                "low": 98.0,
                "close": 101.0,
                "adjusted_close": None,
                "volume": 1000.0,
                "currency_code": "USD",
                "exchange": "NASDAQ",
                "timezone": "America/New_York",
                "provider_price_timestamp": None,
                "source_revision": None,
                "source_hash": "hash",
                "is_adjusted": False,
                "quality_json": {},
            }
        ],
        requested_start=date(2026, 1, 2),
        requested_end=date(2026, 1, 2),
    )

    assert result.promotable is False
    assert result.quality_state == "quarantined"
    assert any(issue["code"] == "ohlc_invariant" for issue in result.issues)


def test_market_history_validation_marks_large_daily_move_suspect():
    result = validate_market_history_batch(
        [
            {
                "symbol": "AAPL",
                "price_date": date(2026, 1, 2),
                "provider_key": "twelve_data",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "adjusted_close": None,
                "volume": 1000.0,
                "currency_code": "USD",
                "exchange": "NASDAQ",
                "timezone": "America/New_York",
                "provider_price_timestamp": None,
                "source_revision": None,
                "source_hash": "hash1",
                "is_adjusted": False,
                "quality_json": {},
            },
            {
                "symbol": "AAPL",
                "price_date": date(2026, 1, 5),
                "provider_key": "twelve_data",
                "open": 199.0,
                "high": 205.0,
                "low": 198.0,
                "close": 200.0,
                "adjusted_close": None,
                "volume": 1000.0,
                "currency_code": "USD",
                "exchange": "NASDAQ",
                "timezone": "America/New_York",
                "provider_price_timestamp": None,
                "source_revision": None,
                "source_hash": "hash2",
                "is_adjusted": False,
                "quality_json": {},
            },
        ],
        requested_start=date(2026, 1, 2),
        requested_end=date(2026, 1, 5),
    )

    assert result.promotable is False
    assert result.quality_state == "suspect"
    assert any(issue["code"] == "max_day_over_day_movement" for issue in result.issues)


class _StoreDb:
    def __init__(self):
        self.candidate_id = 0
        self.promoted = False
        self.fetch_run_updates: list[dict] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        if "to_regclass" in sql:
            return _Result(params["table_name"])
        if "from market_data_source_policy" in sql:
            return _Result(None)
        if "insert into market_price_bar_staging" in sql:
            return _Result(None)
        if "insert into market_fetch_run" in sql:
            return _Result("fetch-run-1")
        if "insert into market_price_bar_candidate" in sql:
            self.candidate_id += 1
            return _Result(self.candidate_id)
        if "update market_fetch_run" in sql:
            self.fetch_run_updates.append(params)
            return _Result(None)
        if "delete from market_price_bar_staging" in sql:
            return _Result(None)
        if "insert into market_price_bar" in sql:
            self.promoted = True
            raise AssertionError("suspect rows must not be promoted")
        raise AssertionError(sql)

    def rollback(self):
        return None


def test_store_market_history_quarantines_suspect_moves_without_promoting():
    db = _StoreDb()

    result = store_market_history_series(
        db,
        provider_key="twelve_data",
        requested_start=date(2026, 1, 2),
        requested_end=date(2026, 1, 5),
        series=[
            {
                "symbol": "AAPL",
                "points": [
                    {
                        "date": "2026-01-02",
                        "open": 99.0,
                        "high": 101.0,
                        "low": 98.0,
                        "close": 100.0,
                    },
                    {
                        "date": "2026-01-05",
                        "open": 199.0,
                        "high": 205.0,
                        "low": 198.0,
                        "close": 200.0,
                    },
                ],
            }
        ],
    )

    assert result["stored"] == 0
    assert result["promoted"] is False
    assert result["quality_state"] == "suspect"
    assert any(
        issue["code"] == "max_day_over_day_movement"
        for issue in result["validation_issues"]
    )
    assert db.promoted is False


def test_expected_market_sessions_handle_crypto_weekends_and_us_holidays():
    crypto = expected_market_sessions("BTC-USD", date(2026, 1, 3), date(2026, 1, 4))
    us = expected_market_sessions("AAPL", date(2026, 1, 1), date(2026, 1, 5))

    assert [item.isoformat() for item in crypto] == ["2026-01-03", "2026-01-04"]
    assert "2026-01-01" not in {item.isoformat() for item in us}
    assert "2026-01-03" not in {item.isoformat() for item in us}


def test_expected_market_sessions_exclude_exchange_specific_holidays():
    us = {item.isoformat() for item in expected_market_sessions("AAPL", date(2026, 4, 2), date(2026, 4, 6))}
    korea_2023 = {
        item.isoformat()
        for item in expected_market_sessions("005930.KS", date(2023, 9, 25), date(2023, 10, 4))
    }
    korea = {
        item.isoformat()
        for item in expected_market_sessions("005930.KS", date(2026, 2, 13), date(2026, 2, 20))
    }
    japan = {
        item.isoformat()
        for item in expected_market_sessions("7203.T", date(2026, 1, 9), date(2026, 1, 14))
    }

    assert "2026-04-03" not in us
    assert "2023-09-28" not in korea_2023
    assert "2023-09-29" not in korea_2023
    assert "2023-10-02" not in korea_2023
    assert "2026-02-16" not in korea
    assert "2026-02-17" not in korea
    assert "2026-02-18" not in korea
    assert "2026-01-12" not in japan
    assert "2026-01-13" in japan


def test_exchange_calendar_coverage_fails_closed_for_unsupported_year():
    with pytest.raises(MarketCalendarCoverageError):
        expected_market_sessions("005930.KS", date(2027, 1, 1), date(2027, 1, 5))

    readiness = market_history_calculation_readiness(
        StoredHistoryResult(
            provider="fixture",
            series=[
                {
                    "symbol": "005930.KS",
                    "points": [{"date": "2027-01-04", "currency": "KRW"}],
                }
            ],
            coverage=[],
            source_policy_digest="fixture",
            data_version="fixture",
            snapshot_id="snapshot",
            snapshot_ids=["snapshot"],
            coherence_status="single_snapshot",
            quality_state="valid",
            warnings=[],
        ),
        symbols=["005930.KS"],
        start=date(2027, 1, 1),
        end=date(2027, 1, 5),
    )

    assert readiness.ready is False
    assert readiness.reason == "market_calendar_coverage_incomplete"


@pytest.mark.asyncio
async def test_public_market_history_route_forces_public_no_store_mode(monkeypatch):
    calls: list[dict[str, object]] = []

    async def fake_fetch_market_history(**kwargs):
        calls.append(kwargs)
        return {
            "status": "license_limited",
            "provider": "tradingview_widget_only",
            "display_mode": "public",
            "symbols": ["AAPL"],
            "start": "2026-01-01",
            "end": "2026-01-31",
        }

    class FakeDb:
        def commit(self):
            return None

    monkeypatch.setattr(
        public_router, "fetch_market_history", fake_fetch_market_history
    )

    response = await public_router.market_history(
        symbols="AAPL",
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        db=FakeDb(),
    )

    assert calls[0]["public_only"] is True
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Market-Data-Source"] == "license-limited"


def _backend_market_history_call_sites(names: set[str]) -> list[tuple[str, str]]:
    repo_root = Path(__file__).resolve().parents[2]
    roots = [repo_root / "apps/api/src", repo_root / "apps/worker/src"]
    call_sites: list[tuple[str, str]] = []
    for root in roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            relative_path = path.relative_to(repo_root).as_posix()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _call_name(node)
                if name in names:
                    call_sites.append((relative_path, name))
    return sorted(call_sites)


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None
