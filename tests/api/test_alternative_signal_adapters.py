from __future__ import annotations

import httpx
import pytest

from frw_api.adapters.alternative_signals import (
    FINRAShortInterestAdapter,
    FINRAShortVolumeAdapter,
    PentagonPizzaAdapter,
    PublicShortResearchAdapter,
    TrumpFilingsAdapter,
)
from frw_api.core.settings import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_finra_short_interest_adapter_parses_rows(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "finra_api_base_url", "https://api.finra.test")
    monkeypatch.setattr(settings, "finra_api_token", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/data/group/otcMarket/name/consolidatedShortInterest"
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            json=[
                {
                    "symbol": "TSLA",
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
async def test_finra_short_volume_adapter_parses_rows(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "finra_api_base_url", "https://api.finra.test")
    monkeypatch.setattr(settings, "finra_api_token", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/data/group/otcMarket/name/regShoDaily"
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
async def test_finra_adapters_degrade_without_token():
    short_interest = await FINRAShortInterestAdapter().fetch()
    short_volume = await FINRAShortVolumeAdapter().fetch()

    assert short_interest.unsupported == ["FINRA_API_TOKEN is required"]
    assert short_volume.unsupported == ["FINRA_API_TOKEN is required"]


@pytest.mark.asyncio
async def test_public_short_research_adapter_keeps_metadata_only():
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


@pytest.mark.asyncio
async def test_pentagon_pizza_adapter_marks_weak_osint(monkeypatch):
    monkeypatch.setattr(get_settings(), "pentagon_pizza_base_url", "https://pizza.test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><head><title>Pizza status</title></head></html>")

    result = await PentagonPizzaAdapter().fetch(transport=httpx.MockTransport(handler))

    assert result.source_key == "pentagon_pizza"
    assert result.observations[0]["signal_class"] == "weak_osint"
    assert result.observations[0]["risk_level"] == "high"
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
