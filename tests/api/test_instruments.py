from __future__ import annotations

from frw_api.services.instruments import resolve_instrument, search_instruments


def test_instrument_search_uses_local_identifier_index():
    payload = search_instruments("US67066G1040")

    assert payload["results"][0]["instrumentId"] == "NVDA"
    assert payload["dataFreshness"]["source"] == "local_scheduled_index"


def test_instrument_search_supports_korean_local_code_and_alias():
    local_code = search_instruments("005930")
    alias = search_instruments("삼성전자")

    assert local_code["results"][0]["listingId"] == "KRX:005930"
    assert local_code["results"][0]["currency"] == "KRW"
    assert alias["results"][0]["instrumentId"] == "005930.KS"


def test_instrument_search_hides_advanced_unless_requested():
    hidden = search_instruments("Apple")
    visible = search_instruments("Apple warrant", include_advanced=True)

    assert all(row["instrumentId"] != "AAPL.WS" for row in hidden["results"])
    assert visible["results"][0]["instrumentId"] == "AAPL.WS"


def test_resolve_instrument_preserves_listing_and_currency():
    payload = resolve_instrument(symbol="005930", exchange="KRX", currency="KRW")

    assert payload["status"] == "MATCHED"
    assert payload["confidence"] == "HIGH"
    assert payload["matches"][0]["listingId"] == "KRX:005930"
