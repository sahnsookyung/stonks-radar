import asyncio
import os

import httpx

from scripts import check_source_health


def _reset_env(monkeypatch):
    for key in (
        "FRED_API_KEY",
        "KRX_OPEN_API_AUTH_KEY",
        "KRX_AUTH_KEY",
        "KRX_API_KEY",
        "DATA_GO_KR_SERVICE_KEY",
        "DATA_GO_KR_API_KEY",
        "PUBLIC_DATA_API_KEY",
        "KOREA_PUBLIC_DATA_API_KEY",
        "KRX_OPEN_API_BASE_URL",
        "KRX_SAMPLE_API_BASE_URL",
        "KRX_ALLOW_SAMPLE_API_FALLBACK",
        "STONKS_SNAPSHOT_ENV_FILE",
        "STONKS_PROVIDER_ENV_FILE",
        "STONKS_SOURCE_HEALTH_ENV_FILE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_load_env_uses_production_secret_file_and_keeps_process_values(tmp_path, monkeypatch):
    _reset_env(monkeypatch)
    secrets_dir = tmp_path / ".secrets"
    secrets_dir.mkdir()
    (tmp_path / ".env").write_text("FRED_API_KEY=file-fred\n")
    (secrets_dir / "stonks-radar.production.env").write_text(
        "FRED_API_KEY=secret-fred\nKRX_AUTH_KEY=secret-krx\n"
    )
    monkeypatch.setenv("FRED_API_KEY", "process-fred")
    monkeypatch.setattr(check_source_health, "ROOT", tmp_path)

    check_source_health._load_env()

    assert os.environ["FRED_API_KEY"] == "process-fred"
    assert os.environ["KRX_AUTH_KEY"] == "secret-krx"


def test_check_reports_any_required_env_aliases_when_missing(monkeypatch):
    _reset_env(monkeypatch)
    probe = check_source_health.SourceProbe(
        "https://example.invalid",
        required_env_any=("KRX_OPEN_API_AUTH_KEY", "KRX_AUTH_KEY", "KRX_API_KEY"),
    )

    result = asyncio.run(check_source_health.check("krx", probe))

    assert result.status == "unsupported"
    assert "KRX_OPEN_API_AUTH_KEY or KRX_AUTH_KEY or KRX_API_KEY" in result.error


def test_selected_required_env_accepts_krx_alias(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("KRX_API_KEY", "krx-key")
    probe = check_source_health.SourceProbe(
        "https://example.invalid",
        required_env_any=("KRX_OPEN_API_AUTH_KEY", "KRX_AUTH_KEY", "KRX_API_KEY"),
    )

    assert check_source_health._selected_required_env(probe) == "KRX_API_KEY"


def test_krx_status_reports_service_approval_error():
    response = httpx.Response(401, json={"respMsg": "Unauthorized API Call", "respCode": "401"})

    ready, message = check_source_health._krx_status(response)

    assert ready is False
    assert message == "KRX Unauthorized API Call; confirm the key is approved for this Open API service"


def test_data_go_kr_status_accepts_items_payload():
    response = httpx.Response(
        200,
        json={
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {"items": {"item": [{"idxNm": "KOSPI"}]}},
            }
        },
    )

    ready, message = check_source_health._data_go_kr_status(response)

    assert ready is True
    assert message is None


def test_html_contains_accepts_expected_page_markers():
    response = httpx.Response(200, text="<title>iShares MSCI South Korea ETF</title> fundHeader.fundNav.navAmount")

    ready, message = check_source_health._html_contains("iShares MSCI South Korea ETF", "fundHeader.fundNav.navAmount")(response)

    assert ready is True
    assert message is None


def test_finnhub_quote_probe_requires_positive_price_and_timestamp():
    response = httpx.Response(200, json={"c": 216.5, "t": 1780073986})

    ready, message = check_source_health._finnhub_quote_status(response)

    assert ready is True
    assert message is None


def test_finnhub_quote_probe_rejects_subscription_errors():
    response = httpx.Response(200, json={"error": "Market data subscription required"})

    ready, message = check_source_health._finnhub_quote_status(response)

    assert ready is False
    assert "subscription" in message


def test_twelve_data_quote_probe_rejects_quota_errors():
    response = httpx.Response(200, json={"status": "error", "message": "You have run out of API credits"})

    ready, message = check_source_health._twelve_data_quote_status(response)

    assert ready is False
    assert "credits" in message


def test_source_health_retry_delay_honors_short_retry_after():
    response = httpx.Response(429, headers={"Retry-After": "2"})

    assert check_source_health._retry_delay_seconds(response, 0) == 2.0


def test_source_health_retry_delay_skips_long_retry_after():
    response = httpx.Response(429, headers={"Retry-After": "60"})

    assert check_source_health._retry_delay_seconds(response, 0) is None


def test_probe_url_uses_configured_krx_base(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("KRX_OPEN_API_BASE_URL", "https://data-dbg.krx.co.kr/svc/sample/apis")
    probe = check_source_health.SourceProbe(
        "https://data-dbg.krx.co.kr/svc/apis/idx/krx_dd_trd.json",
        url_env="KRX_OPEN_API_BASE_URL",
        path="idx/krx_dd_trd.json",
    )

    assert (
        check_source_health._probe_url(probe)
        == "https://data-dbg.krx.co.kr/svc/sample/apis/idx/krx_dd_trd.json"
    )


def test_probe_url_uses_sample_fallback_when_enabled(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("KRX_ALLOW_SAMPLE_API_FALLBACK", "true")
    probe = check_source_health.SourceProbe(
        "https://data-dbg.krx.co.kr/svc/apis/idx/krx_dd_trd.json",
        url_env="KRX_OPEN_API_BASE_URL",
        path="idx/krx_dd_trd.json",
    )

    assert (
        check_source_health._probe_url(probe)
        == "https://data-dbg.krx.co.kr/svc/sample/apis/idx/krx_dd_trd.json"
    )


def test_required_ready_failures_report_non_ready_sources():
    results = [
        check_source_health.SourceHealthResult(
            source_key="fred",
            status="ready",
            status_code="200",
            response_ms=10,
            error=None,
            details={},
        ),
        check_source_health.SourceHealthResult(
            source_key="krx",
            status="failed",
            status_code="401",
            response_ms=10,
            error="unexpected status 401",
            details={},
        ),
    ]

    assert check_source_health._required_ready_failures(results, ("fred", "krx", "finra")) == [
        "krx=failed:unexpected status 401",
        "finra=missing_probe",
    ]


def test_korea_market_data_requirement_accepts_public_data_fallback():
    results = [
        check_source_health.SourceHealthResult(
            source_key="krx",
            status="failed",
            status_code="401",
            response_ms=10,
            error="KRX Unauthorized API Call",
            details={},
        ),
        check_source_health.SourceHealthResult(
            source_key="fsc_market_index",
            status="ready",
            status_code="200",
            response_ms=10,
            error=None,
            details={},
        ),
    ]

    assert check_source_health._required_ready_failures(results, ("korea_market_data",)) == []


def test_korea_market_data_requirement_accepts_ewy_proxy():
    results = [
        check_source_health.SourceHealthResult(
            source_key="krx",
            status="failed",
            status_code="401",
            response_ms=10,
            error="KRX Unauthorized API Call",
            details={},
        ),
        check_source_health.SourceHealthResult(
            source_key="ishares_ewy",
            status="ready",
            status_code="200",
            response_ms=10,
            error=None,
            details={},
        ),
    ]

    assert check_source_health._required_ready_failures(results, ("korea_market_data",)) == []


def test_source_list_can_disable_required_ready():
    assert check_source_health._source_list("none") == ()
    assert check_source_health._source_list("fred, krx") == ("fred", "krx")


def test_source_health_includes_gdelt_probes():
    assert {"gdelt", "gdelt_events", "gdelt_gkg"}.issubset(check_source_health.SOURCES)
    assert check_source_health.SOURCES["gdelt_events"].api_key_param is None
