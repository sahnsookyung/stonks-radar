from __future__ import annotations

from datetime import date

import httpx
import pytest

from frw_api.core.settings import get_settings
from frw_api.services.provider_limits import ProviderQuotaGuard
from frw_api.services.market_data import MarketDataInputError, clear_market_data_cache, fetch_market_history


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    clear_market_data_cache()
    ProviderQuotaGuard.reset_memory()
    yield
    clear_market_data_cache()
    ProviderQuotaGuard.reset_memory()
    get_settings.cache_clear()


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

    def handler(request: httpx.Request) -> httpx.Response:
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
    assert allowed["status"] == "ok"
    assert allowed["cache"] == "miss"
    assert allowed["data_freshness"]["is_public_display_allowed"] is True
