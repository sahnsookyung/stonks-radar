from __future__ import annotations

import os
from types import SimpleNamespace

from frw_api.services import instruments


class _Settings(SimpleNamespace):
    @property
    def instrument_universe_source_list(self) -> list[str]:
        return ["nasdaq_trader", "sec_company_tickers"]


def _settings(path: str) -> _Settings:
    return _Settings(
        instrument_universe_cache_path=path,
        instrument_universe_max_dynamic_instruments=25_000,
        instrument_universe_refresh_seconds=14400,
        instrument_universe_fetch_timeout_seconds=5,
        instrument_autocomplete_max_query_length=64,
        instrument_autocomplete_max_results=25,
        instrument_autocomplete_index_ttl_seconds=1800,
        sec_user_agent="StonksRadar tests@example.com",
    )


def _reset_index(monkeypatch) -> None:
    monkeypatch.setattr(instruments, "_INDEX", None)
    monkeypatch.setattr(instruments, "_SEARCH_CACHE", {})
    monkeypatch.setattr(instruments, "_DYNAMIC_INSTRUMENTS", ())
    monkeypatch.setattr(instruments, "_DYNAMIC_INDEX_PATH", None)
    monkeypatch.setattr(instruments, "_DYNAMIC_INDEX_MTIME", None)
    monkeypatch.setattr(instruments, "_INDEX_SOURCE_STATUSES", [])


def test_parses_nasdaq_symbol_directory_rows_and_skips_test_issues():
    text = "\n".join(
        [
            "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares",
            "QQQM|Invesco NASDAQ 100 ETF|G|N|N|100|Y|N",
            "ZZTEST|Test Issue Inc|G|Y|N|100|N|N",
            "File Creation Time: 0605202621:31|||||||",
        ]
    )

    parsed, file_creation_time = instruments._parse_nasdaq_listed(text, generated_at="2026-06-05T21:31:00Z")

    assert file_creation_time == "0605202621:31"
    assert [item.symbol for item in parsed] == ["QQQM"]
    assert parsed[0].instrument_type == "etf"
    assert parsed[0].listings[0].exchange == "NASDAQ"


def test_parses_sec_exchange_json_into_cik_identified_instruments():
    payload = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]],
    }

    parsed = instruments._parse_sec_company_tickers_exchange(payload, generated_at="2026-06-05T21:31:00Z")

    assert parsed[0].symbol == "AAPL"
    assert parsed[0].identifiers[0].type == "CIK"
    assert parsed[0].identifiers[0].value == "0000320193"


def test_refresh_writes_durable_artifact_and_search_uses_cached_universe(tmp_path, monkeypatch):
    artifact_path = tmp_path / "instrument-universe.json"
    settings = _settings(str(artifact_path))
    qqqm = instruments._source_instrument(
        symbol="QQQM",
        name="Invesco NASDAQ 100 ETF",
        exchange="NASDAQ",
        etf=True,
        generated_at="2026-06-05T21:31:00Z",
    )

    monkeypatch.setattr(instruments, "get_settings", lambda: settings)
    monkeypatch.setattr(
        instruments,
        "_fetch_dynamic_instrument_universe",
        lambda source_names, *, settings: (
            (qqqm,),
            [{"source": "nasdaq_trader:nasdaqlisted", "status": "ok", "instrument_count": 1}],
        ),
    )
    _reset_index(monkeypatch)

    result = instruments.refresh_instrument_index(source="CONFIGURED_FREE_SOURCES", mode="FULL")
    search = instruments.search_instruments("QQQM", context="BUILDER")

    assert artifact_path.exists()
    assert result["instrument_count"] >= 1
    assert search["results"][0]["displaySymbol"] == "QQQM"
    assert search["dataFreshness"]["providerStatuses"][0]["source"] == "nasdaq_trader:nasdaqlisted"


def test_search_index_notices_worker_written_artifact_without_api_restart(tmp_path, monkeypatch):
    artifact_path = tmp_path / "instrument-universe.json"
    settings = _settings(str(artifact_path))
    first = instruments._source_instrument(
        symbol="ZZZOLD",
        name="Old Dynamic Test Corp.",
        exchange="NASDAQ",
        etf=False,
        generated_at="2026-06-05T21:31:00Z",
    )
    second = instruments._source_instrument(
        symbol="ZZZNEW",
        name="New Dynamic Test Corp.",
        exchange="NASDAQ",
        etf=False,
        generated_at="2026-06-06T21:31:00Z",
    )

    monkeypatch.setattr(instruments, "get_settings", lambda: settings)
    _reset_index(monkeypatch)
    instruments._write_dynamic_instrument_artifact((first,), [{"source": "test", "status": "ok"}], settings=settings)
    assert instruments.search_instruments("ZZZOLD", context="BUILDER")["results"][0]["displaySymbol"] == "ZZZOLD"

    instruments._write_dynamic_instrument_artifact((second,), [{"source": "test", "status": "ok"}], settings=settings)
    stat = artifact_path.stat()
    os.utime(artifact_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    refreshed = instruments.search_instruments("ZZZNEW", context="BUILDER")
    assert refreshed["results"][0]["displaySymbol"] == "ZZZNEW"


def test_search_cache_stores_only_bounded_result_slice(tmp_path, monkeypatch):
    artifact_path = tmp_path / "instrument-universe.json"
    settings = _settings(str(artifact_path))
    settings.instrument_autocomplete_max_results = 3
    dynamic = tuple(
        instruments._source_instrument(
            symbol=f"AAA{i}",
            name=f"Alpha Cache Test {i}",
            exchange="NASDAQ",
            etf=False,
            generated_at="2026-06-06T21:31:00Z",
        )
        for i in range(10)
    )

    monkeypatch.setattr(instruments, "get_settings", lambda: settings)
    _reset_index(monkeypatch)
    instruments._write_dynamic_instrument_artifact(dynamic, [{"source": "test", "status": "ok"}], settings=settings)

    search = instruments.search_instruments("AAA", limit=3, context="BUILDER")

    assert len(search["results"]) == 3
    assert all(len(cached_results) <= 3 for _, cached_results in instruments._SEARCH_CACHE.values())


def test_refresh_reports_current_provider_failure_and_stale_artifact_fallback(tmp_path, monkeypatch):
    artifact_path = tmp_path / "instrument-universe.json"
    settings = _settings(str(artifact_path))
    cached = instruments._source_instrument(
        symbol="QQQM",
        name="Invesco NASDAQ 100 ETF",
        exchange="NASDAQ",
        etf=True,
        generated_at="2026-06-05T21:31:00Z",
    )

    monkeypatch.setattr(instruments, "get_settings", lambda: settings)
    _reset_index(monkeypatch)
    instruments._write_dynamic_instrument_artifact((cached,), [{"source": "test", "status": "ok"}], settings=settings)
    monkeypatch.setattr(
        instruments,
        "_fetch_dynamic_instrument_universe",
        lambda source_names, *, settings: (
            (),
            [{"source": "nasdaq_trader:nasdaqlisted", "status": "error", "error": "timeout"}],
        ),
    )

    result = instruments.refresh_instrument_index(source="CONFIGURED_FREE_SOURCES", mode="FULL")

    assert result["provider_statuses"][0]["status"] == "error"
    assert result["provider_statuses"][1]["status"] == "stale_fallback"
    assert result["provider_statuses"][1]["instrument_count"] == 1


def test_dynamic_universe_merges_nasdaq_listing_with_sec_cik(tmp_path, monkeypatch):
    settings = _settings(str(tmp_path / "instrument-universe.json"))
    nasdaq = instruments._source_instrument(
        symbol="ZZZMERGE",
        name="Merge Test Corp.",
        exchange="NASDAQ",
        etf=False,
        generated_at="2026-06-05T21:31:00Z",
        source_provider="nasdaq_trader",
    )
    sec = instruments._source_instrument(
        symbol="ZZZMERGE",
        name="Merge Test Corporation",
        exchange="Nasdaq",
        etf=False,
        generated_at="2026-06-05T21:31:00Z",
        identifiers=(instruments.InstrumentIdentifier("CIK", "0000123456"),),
        source_provider="sec_company_tickers",
    )

    monkeypatch.setattr(instruments, "_fetch_nasdaq_trader_symbols", lambda client, *, generated_at: ([nasdaq], [{"source": "nasdaq_trader:nasdaqlisted", "status": "ok"}]))
    monkeypatch.setattr(instruments, "_fetch_sec_company_tickers", lambda client, *, generated_at: ([sec], {"source": "sec_company_tickers", "status": "ok"}))

    merged, _statuses = instruments._fetch_dynamic_instrument_universe(["nasdaq_trader", "sec_company_tickers"], settings=settings)

    assert len(merged) == 1
    assert merged[0].exchange == "NASDAQ"
    assert ("nasdaq_trader", "sec_company_tickers") == merged[0].source_providers
    assert any(identifier.type == "CIK" and identifier.value == "0000123456" for identifier in merged[0].identifiers)


def test_instrument_universe_static_record_keeps_display_but_merges_dynamic_cik(tmp_path, monkeypatch):
    settings = _settings(str(tmp_path / "instrument-universe.json"))
    dynamic_aapl = instruments._source_instrument(
        symbol="AAPL",
        name="Apple Inc. SEC mapping",
        exchange="Nasdaq",
        etf=False,
        generated_at="2026-06-05T21:31:00Z",
        identifiers=(instruments.InstrumentIdentifier("CIK", "0000320193"),),
        source_provider="sec_company_tickers",
    )

    monkeypatch.setattr(instruments, "get_settings", lambda: settings)
    monkeypatch.setattr(instruments, "_load_dynamic_instruments", lambda *args, **kwargs: (dynamic_aapl,))

    aapl = next(item for item in instruments.instrument_universe() if item.instrument_id == "AAPL")

    assert aapl.exchange == "NASDAQ"
    assert "local_static_seed" in aapl.source_providers
    assert "sec_company_tickers" in aapl.source_providers
    assert any(identifier.type == "CIK" and identifier.value == "0000320193" for identifier in aapl.identifiers)


def test_instrument_index_freshness_uses_refresh_cadence(tmp_path, monkeypatch):
    settings = _settings(str(tmp_path / "instrument-universe.json"))
    monkeypatch.setattr(instruments, "get_settings", lambda: settings)
    monkeypatch.setattr(instruments, "INDEX_LAST_UPDATED_AT", "2026-06-06T00:00:00Z")

    freshness = instruments._index_freshness()

    assert freshness["staleAfter"] == "2026-06-06T08:00:00Z"
    assert freshness["hardExpiresAt"] == "2026-06-13T00:00:00Z"
