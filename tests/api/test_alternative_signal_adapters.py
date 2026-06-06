from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from frw_api.adapters.alternative_signals import (
    FINRAShortInterestAdapter,
    FINRAShortVolumeAdapter,
    PentagonPizzaAdapter,
    PublicShortResearchAdapter,
    TrumpFilingsAdapter,
    _selected_short_research_sources,
)
from frw_api.core.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _allow_url(url: str):
    return SimpleNamespace(allowed=True, reason="allowed", resolved_ips=["93.184.216.34"])


@pytest.mark.asyncio
async def test_finra_short_interest_adapter_parses_rows(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "finra_api_base_url", "https://api.finra.test")
    monkeypatch.setattr(settings, "finra_api_token", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/data/group/otcMarket/name/consolidatedShortInterest"
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.read() == (
            b'{"limit":5000,"compareFilters":[{"compareType":"equal","fieldName":"symbolCode","fieldValue":"TSLA"}]}'
        )
        return httpx.Response(
            200,
            json=[
                {
                    "symbolCode": "TSLA",
                    "settlementDate": "2026-05-15",
                    "currentShortPositionQuantity": 123456,
                }
            ],
        )

    result = await FINRAShortInterestAdapter().fetch(
        symbols=["TSLA"],
        transport=httpx.MockTransport(handler),
    )

    assert result.source_key == "finra_short_interest"
    assert result.observations[0]["series_key"] == "FINRA_SHORT_INTEREST_TSLA"
    assert result.observations[0]["value"] == 123456
    assert result.documents[0]["row_count"] == 1


@pytest.mark.asyncio
async def test_finra_adapter_preserves_multi_symbol_latest_rows(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "finra_api_base_url", "https://api.finra.test")
    monkeypatch.setattr(settings, "finra_api_token", "test-token")
    seen_symbols: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json_from_request(request)
        symbol = payload["compareFilters"][0]["fieldValue"]
        seen_symbols.append(symbol)
        older = {
            "symbolCode": symbol,
            "settlementDate": "2026-04-30",
            "currentShortPositionQuantity": 100,
        }
        newer = {
            "symbolCode": symbol,
            "settlementDate": "2026-05-15",
            "currentShortPositionQuantity": 200,
        }
        return httpx.Response(200, json=[older, newer])

    result = await FINRAShortInterestAdapter().fetch(
        symbols=["DJT", "TSLA", "NVDA"],
        limit=3,
        transport=httpx.MockTransport(handler),
    )

    assert seen_symbols == ["DJT", "TSLA", "NVDA"]
    assert {row["symbol"] for row in result.observations} == {"DJT", "TSLA", "NVDA"}
    assert {row["date"] for row in result.observations} == {"2026-05-15"}


@pytest.mark.asyncio
async def test_finra_short_volume_adapter_parses_rows(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "finra_api_base_url", "https://api.finra.test")
    monkeypatch.setattr(settings, "finra_api_token", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/data/group/otcMarket/name/regShoDaily"
        assert request.method == "POST"
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "securitiesInformationProcessorSymbolIdentifier": "NVDA",
                        "tradeReportDate": "2026-05-22",
                        "shortParQuantity": 9876,
                    }
                ]
            },
        )

    result = await FINRAShortVolumeAdapter().fetch(
        symbols=["NVDA"],
        transport=httpx.MockTransport(handler),
    )

    assert result.source_key == "finra_reg_sho_short_volume"
    assert result.observations[0]["series_key"] == "FINRA_SHORT_VOLUME_NVDA"
    assert result.observations[0]["value"] == 9876


@pytest.mark.asyncio
async def test_finra_adapter_uses_oauth_client_credentials(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "finra_api_base_url", "https://api.finra.test")
    monkeypatch.setattr(settings, "finra_oauth_token_url", "https://oauth.finra.test/token")
    monkeypatch.setattr(settings, "finra_api_token", None)
    monkeypatch.setattr(settings, "finra_api_client_id", "client-id")
    monkeypatch.setattr(settings, "finra_api_client_secret", "client-secret")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth.finra.test":
            assert request.method == "POST"
            assert request.headers["authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "oauth-token", "token_type": "Bearer", "expires_in": 1800})
        assert request.url.path == "/data/group/otcMarket/name/regShoDaily"
        assert request.headers["authorization"] == "Bearer oauth-token"
        return httpx.Response(
            200,
            json=[
                {
                    "securitiesInformationProcessorSymbolIdentifier": "TSLA",
                    "tradeReportDate": "2026-05-22",
                    "shortParQuantity": 1234,
                }
            ],
        )

    result = await FINRAShortVolumeAdapter().fetch(symbols=["TSLA"], transport=httpx.MockTransport(handler))

    assert result.observations[0]["series_key"] == "FINRA_SHORT_VOLUME_TSLA"
    assert result.observations[0]["value"] == 1234


@pytest.mark.asyncio
async def test_finra_adapters_degrade_without_credentials():
    short_interest = await FINRAShortInterestAdapter().fetch()
    short_volume = await FINRAShortVolumeAdapter().fetch()

    assert short_interest.unsupported == ["FINRA_API_TOKEN or FINRA_API_CLIENT_ID/FINRA_API_CLIENT_SECRET is required"]
    assert short_volume.unsupported == ["FINRA_API_TOKEN or FINRA_API_CLIENT_ID/FINRA_API_CLIENT_SECRET is required"]


@pytest.mark.asyncio
async def test_public_short_research_adapter_keeps_metadata_only(monkeypatch):
    monkeypatch.setattr("frw_api.services.safe_fetch.evaluate_url", _allow_url)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><head><title>Muddy Waters Research</title></head><body>Report index</body></html>",
        )

    result = await PublicShortResearchAdapter().fetch(
        source_keys=["muddy_waters"],
        transport=httpx.MockTransport(handler),
    )

    assert result.source_key == "public_short_research"
    assert result.documents[0]["title"] == "Muddy Waters Research"
    assert result.documents[0]["raw_retained"] is False
    assert result.observations == []


def test_public_short_research_excludes_hindenburg():
    selected = _selected_short_research_sources(["hindenburg", "muddy_waters"])

    assert "hindenburg" not in selected
    assert selected == {"muddy_waters": "https://www.muddywatersresearch.com/"}


@pytest.mark.asyncio
async def test_pentagon_pizza_adapter_marks_weak_osint(monkeypatch):
    monkeypatch.setattr(get_settings(), "pentagon_pizza_base_url", "https://pizza.test")
    monkeypatch.setattr(get_settings(), "pentagon_pizza_function_url", None)
    monkeypatch.setattr(get_settings(), "pentagon_pizza_supabase_anon_key", None)
    monkeypatch.setattr("frw_api.services.safe_fetch.evaluate_url", _allow_url)
    monkeypatch.setattr("frw_api.adapters.alternative_signals.evaluate_url", _allow_url)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "pizza.test" and request.url.path == "/":
            return httpx.Response(
                200,
                text='<html><head><title>Pizza status</title><script src="/assets/index.js"></script></head></html>',
            )
        if request.url.host == "pizza.test" and request.url.path == "/assets/index.js":
            return httpx.Response(
                200,
                text=(
                    'const d_="https://pizza.supabase.co";'
                    'const f_="eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJ0ZXN0In0.signature";'
                ),
            )
        if request.url.host == "pizza.supabase.co":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "timestamp": "2026-05-25T17:50:37.711Z",
                    "locationCount": 2,
                    "anomalyCount": 1,
                    "dataSource": "pattern_model",
                    "readings": [
                        {"busyness_level": 60, "is_anomaly": False},
                        {"busyness_level": 66, "is_anomaly": True},
                    ],
                },
            )
        raise AssertionError(f"unexpected request {request.url}")

    result = await PentagonPizzaAdapter().fetch(transport=httpx.MockTransport(handler))

    assert result.source_key == "pentagon_pizza"
    assert result.observations[0]["signal_class"] == "weak_osint"
    assert result.observations[0]["risk_level"] == "high"
    assert result.observations[0]["value"] == 63.0
    assert result.observations[0]["unit"] == "0_100_index"
    assert result.observations[0]["status"] == "measured"
    assert result.observations[0]["location_count"] == 2
    assert result.observations[0]["anomaly_count"] == 1
    assert result.documents[0]["raw_retained"] is False


@pytest.mark.asyncio
async def test_trump_filings_adapter_parses_recent_sec_filings(monkeypatch):
    monkeypatch.setattr(get_settings(), "trump_filing_monitored_entities", "DJT")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "data.sec.gov"
        return httpx.Response(
            200,
            json={
                "name": "Trump Media & Technology Group Corp.",
                "filings": {
                    "recent": {
                        "accessionNumber": ["0001849635-26-000001"],
                        "form": ["8-K"],
                        "filingDate": ["2026-05-22"],
                    }
                },
            },
        )

    result = await TrumpFilingsAdapter().fetch(
        ciks={"DJT": "1849635"},
        transport=httpx.MockTransport(handler),
    )

    assert result.source_key == "trump_filings"
    assert result.documents[0]["form"] == "8-K"
    assert result.documents[0]["entity_label"] == "DJT"


def json_from_request(request: httpx.Request):
    import json

    return json.loads(request.read().decode())
