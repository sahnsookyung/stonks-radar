import json
from datetime import datetime, timezone
from io import BytesIO
from urllib import error

from scripts import build_seed_snapshots


def test_preserve_previous_active_macro_tile_when_refresh_source_is_unavailable(tmp_path, monkeypatch):
    home_path = tmp_path / "v1" / "en" / "home.json"
    home_path.parent.mkdir(parents=True)
    home_path.write_text(
        json.dumps(
            {
                "data": {
                    "macro_tiles": [
                        {
                            "key": "us_2y",
                            "label": "US Treasury 2Y",
                            "value": "4.03",
                            "source": "U.S. Treasury XML feed",
                            "freshness": "fresh",
                            "delay_label": "Treasury 2Y actual through 2026-05-22",
                            "updated_at": "2026-05-26T01:00:50Z",
                            "coverage_status": "active",
                            "refresh_seconds": 900,
                        }
                    ]
                }
            }
        )
    )
    monkeypatch.setattr(build_seed_snapshots, "PUBLIC_ROOT", tmp_path)

    [tile] = build_seed_snapshots._preserve_previous_active_macro_tiles(
        "en",
        [
            {
                "key": "us_2y",
                "label": "US Treasury 2Y",
                "value": "Source gap",
                "source": "U.S. Treasury XML feed",
                "freshness": "watch",
                "delay_label": "Treasury XML feed unavailable",
                "updated_at": "2026-05-27T00:00:00Z",
                "coverage_status": "coverage_gap",
                "refresh_seconds": 900,
            }
        ],
    )

    assert tile["value"] == "4.03"
    assert tile["freshness"] == "watch"
    assert tile["coverage_status"] == "active"
    assert tile["updated_at"] == "2026-05-26T01:00:50Z"
    assert "Using last published value" in tile["delay_label"]


def test_preserve_previous_active_macro_tile_blocks_time_sensitive_fallback(tmp_path, monkeypatch):
    home_path = tmp_path / "v1" / "en" / "home.json"
    home_path.parent.mkdir(parents=True)
    home_path.write_text(
        json.dumps(
            {
                "data": {
                    "macro_tiles": [
                        {
                            "key": "wti_crude",
                            "label": "WTI crude oil futures",
                            "value": "97.63",
                            "source": "FRED / EIA",
                            "freshness": "fresh",
                            "delay_label": "stale old source",
                            "updated_at": "2026-05-26T21:00:00Z",
                            "coverage_status": "active",
                            "refresh_seconds": 900,
                        }
                    ]
                }
            }
        )
    )
    monkeypatch.setattr(build_seed_snapshots, "PUBLIC_ROOT", tmp_path)

    [tile] = build_seed_snapshots._preserve_previous_active_macro_tiles(
        "en",
        [
            {
                "key": "wti_crude",
                "value": "Source gap",
                "freshness": "watch",
                "coverage_status": "coverage_gap",
                "delay_label": "current quote unavailable",
            }
        ],
    )

    assert tile["value"] == "Source gap"
    assert tile["coverage_status"] == "coverage_gap"


def test_preserve_previous_active_macro_tile_does_not_keep_previous_gap(tmp_path, monkeypatch):
    home_path = tmp_path / "v1" / "en" / "home.json"
    home_path.parent.mkdir(parents=True)
    home_path.write_text(
        json.dumps(
            {
                "data": {
                    "macro_tiles": [
                        {
                            "key": "kodex_200",
                            "value": "Source gap",
                            "freshness": "watch",
                            "coverage_status": "coverage_gap",
                        }
                    ]
                }
            }
        )
    )
    monkeypatch.setattr(build_seed_snapshots, "PUBLIC_ROOT", tmp_path)

    [tile] = build_seed_snapshots._preserve_previous_active_macro_tiles(
        "en",
        [
            {
                "key": "kodex_200",
                "value": "Source gap",
                "freshness": "watch",
                "coverage_status": "coverage_gap",
            }
        ],
    )

    assert tile["value"] == "Source gap"
    assert tile["coverage_status"] == "coverage_gap"


def test_krx_rows_records_unauthorized_diagnostic(monkeypatch):
    build_seed_snapshots._reset_runtime_caches()
    monkeypatch.setenv("KRX_OPEN_API_AUTH_KEY", "test-key")

    def fail_request(*_args, **_kwargs):
        raise error.HTTPError(
            url="https://data-dbg.krx.co.kr/svc/apis/idx/krx_dd_trd.json",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=BytesIO(b'{"respMsg":"Unauthorized API Call","respCode":"401"}'),
        )

    monkeypatch.setattr(build_seed_snapshots, "_http_json", fail_request)

    rows = build_seed_snapshots._krx_rows(build_seed_snapshots.KRX_INDEX_DAILY_PATH, "20260522")
    message = build_seed_snapshots._krx_recent_error(
        build_seed_snapshots.KRX_INDEX_DAILY_PATH,
        datetime(2026, 5, 22, tzinfo=timezone.utc),
    )

    assert rows == []
    assert message == "KRX returned 401 Unauthorized API Call; confirm the API key is approved for this Open API service"


def test_krx_rows_can_fallback_to_sample_api_when_enabled(monkeypatch):
    build_seed_snapshots._reset_runtime_caches()
    monkeypatch.setenv("KRX_OPEN_API_AUTH_KEY", "test-key")
    monkeypatch.setenv("KRX_ALLOW_SAMPLE_API_FALLBACK", "true")
    requested_urls = []

    def fake_request(url, *_args, **_kwargs):
        requested_urls.append(url)
        if "/svc/apis/" in url:
            raise error.HTTPError(
                url=url,
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=BytesIO(b'{"respMsg":"Unauthorized API Call","respCode":"401"}'),
            )
        return {"OutBlock_1": [{"BAS_DD": "20260522", "IDX_NM": "KRX300", "CLSPRC_IDX": "5523.14"}]}

    monkeypatch.setattr(build_seed_snapshots, "_http_json", fake_request)

    rows = build_seed_snapshots._krx_rows(build_seed_snapshots.KRX_INDEX_DAILY_PATH, "20260522")

    assert rows == [{"BAS_DD": "20260522", "IDX_NM": "KRX300", "CLSPRC_IDX": "5523.14"}]
    assert requested_urls == [
        "https://data-dbg.krx.co.kr/svc/apis/idx/krx_dd_trd.json?basDd=20260522",
        "https://data-dbg.krx.co.kr/svc/sample/apis/idx/krx_dd_trd.json?basDd=20260522",
    ]


def test_macro_tiles_derive_korea_indices_from_krx_index_service(monkeypatch):
    build_seed_snapshots._reset_runtime_caches()
    monkeypatch.setenv("KRX_OPEN_API_AUTH_KEY", "test-key")
    monkeypatch.setattr(build_seed_snapshots, "_web_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_pentagon_pizza_payload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_pentagon_pizza_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_yahoo_chart_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_stooq_quote_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_treasury_yield_curve_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        build_seed_snapshots,
        "_fred_series",
        lambda *_args, **_kwargs: {
            "date": "2026-05-26",
            "value": 1.23,
            "points": [{"date": "2026-05-25", "value": 1.2}, {"date": "2026-05-26", "value": 1.23}],
        },
    )
    monkeypatch.setattr(
        build_seed_snapshots,
        "_mof_jgb_series",
        lambda *_args, **_kwargs: {
            "date": "2026-05-26",
            "value": 0.85,
            "points": [{"date": "2026-05-25", "value": 0.8}, {"date": "2026-05-26", "value": 0.85}],
        },
    )

    def fake_krx_series(path, _generated_at, *, predicate, value_keys):
        assert path == build_seed_snapshots.KRX_INDEX_DAILY_PATH
        rows = [
            {"BAS_DD": "20260526", "IDX_NM": "KRX300", "CLSPRC_IDX": "5523.14"},
            {"BAS_DD": "20260526", "IDX_NM": "KRX300 정보기술", "CLSPRC_IDX": "11549.84"},
        ]
        for row in rows:
            if predicate(row):
                return {
                    "date": "2026-05-26",
                    "value": float(row[value_keys[0]]),
                    "points": [
                        {"date": "2026-05-25", "value": float(row[value_keys[0]]) - 10},
                        {"date": "2026-05-26", "value": float(row[value_keys[0]])},
                    ],
                }
        return None

    monkeypatch.setattr(build_seed_snapshots, "_krx_series", fake_krx_series)

    tiles = build_seed_snapshots._macro_tiles("en", datetime(2026, 5, 26, tzinfo=timezone.utc))
    by_key = {tile["key"]: tile for tile in tiles}

    assert by_key["krx_300"]["value"] == "5,523.14"
    assert by_key["krx_300_it"]["value"] == "11,549.84"
    assert by_key["krx_300"]["source"] == "KRX index daily trading"
    assert "kodex_200" not in by_key
    assert "kospi_200_futures" not in by_key


def test_macro_tiles_use_ewy_proxy_when_krx_is_unavailable(monkeypatch):
    build_seed_snapshots._reset_runtime_caches()
    monkeypatch.setenv("KRX_OPEN_API_AUTH_KEY", "test-key")
    monkeypatch.setattr(build_seed_snapshots, "_web_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_pentagon_pizza_payload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_pentagon_pizza_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_yahoo_chart_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_stooq_quote_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_treasury_yield_curve_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        build_seed_snapshots,
        "_fred_series",
        lambda *_args, **_kwargs: {
            "date": "2026-05-26",
            "value": 1.23,
            "points": [{"date": "2026-05-25", "value": 1.2}, {"date": "2026-05-26", "value": 1.23}],
        },
    )
    monkeypatch.setattr(
        build_seed_snapshots,
        "_mof_jgb_series",
        lambda *_args, **_kwargs: {
            "date": "2026-05-26",
            "value": 0.85,
            "points": [{"date": "2026-05-25", "value": 0.8}, {"date": "2026-05-26", "value": 0.85}],
        },
    )
    monkeypatch.setattr(build_seed_snapshots, "_krx_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        build_seed_snapshots,
        "_ishares_ewy_nav_series",
        lambda: {
            "date": "2026-05-26",
            "value": 197.71,
            "change": 12.44,
            "percent_change": 6.72,
            "points": [{"date": "2026-05-25", "value": 185.27}, {"date": "2026-05-26", "value": 197.71}],
        },
    )

    tiles = build_seed_snapshots._macro_tiles("en", datetime(2026, 5, 26, tzinfo=timezone.utc))
    by_key = {tile["key"]: tile for tile in tiles}

    assert by_key["ewy_korea_proxy"]["value"] == "197.71"
    assert by_key["ewy_korea_proxy"]["source"] == "iShares / BlackRock EWY"
    assert by_key["ewy_korea_proxy"]["refresh_delta"] == 12.44
    assert "proxy for Korean equity exposure" in by_key["ewy_korea_proxy"]["delay_label"]
    assert "krx_300" not in by_key
    assert "krx_300_it" not in by_key


def test_macro_tiles_prefer_current_kospi_and_kodex_quotes(monkeypatch):
    build_seed_snapshots._reset_runtime_caches()
    monkeypatch.setattr(build_seed_snapshots, "_web_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_pentagon_pizza_payload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_pentagon_pizza_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_fred_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_treasury_yield_curve_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_mof_jgb_series", lambda *_args, **_kwargs: None)
    values = {
        "^KS11": {"date": "2026-05-29", "value": 8476.15, "updated_at": "2026-05-29T09:05:40Z", "points": [{"date": "2026-05-29T09:04:00Z", "value": 8460.0}, {"date": "2026-05-29T09:05:40Z", "value": 8476.15}], "change": 290.86, "source_url": "https://finance.yahoo.com/quote/%5EKS11"},
        "069500.KS": {"date": "2026-05-29", "value": 134815.0, "updated_at": "2026-05-29T06:30:07Z", "points": [{"date": "2026-05-29T06:29:00Z", "value": 134000.0}, {"date": "2026-05-29T06:30:07Z", "value": 134815.0}], "change": 4825.0, "source_url": "https://finance.yahoo.com/quote/069500.KS"},
    }
    monkeypatch.setattr(build_seed_snapshots, "_yahoo_chart_series", lambda symbol: values.get(symbol))
    monkeypatch.setattr(build_seed_snapshots, "_stooq_quote_series", lambda *_args, **_kwargs: None)

    tiles = build_seed_snapshots._macro_tiles("en", datetime(2026, 5, 29, 12, tzinfo=timezone.utc))
    by_key = {tile["key"]: tile for tile in tiles}

    assert by_key["kospi"]["value"] == "8,476.15"
    assert by_key["kospi"]["updated_at"] == "2026-05-29T09:05:40Z"
    assert by_key["kodex_200"]["value"] == "134,815"
    assert by_key["kodex_200"]["refresh_delta"] == 4825.0
    assert "FRED" not in by_key["kospi"]["source"]


def test_macro_tiles_choose_freshest_allowed_public_quote_candidate(monkeypatch):
    build_seed_snapshots._reset_runtime_caches()
    monkeypatch.setattr(build_seed_snapshots, "_web_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_pentagon_pizza_payload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_pentagon_pizza_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_fred_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_treasury_yield_curve_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_mof_jgb_series", lambda *_args, **_kwargs: None)

    def yahoo(symbol):
        if symbol == "CL=F":
            return {
                "date": "2026-05-29",
                "value": 87.75,
                "updated_at": "2026-05-29T15:50:35Z",
                "points": [{"date": "2026-05-29T15:49:00Z", "value": 88.0}, {"date": "2026-05-29T15:50:35Z", "value": 87.75}],
                "change": -0.25,
                "source_url": "https://finance.yahoo.com/quote/CL%3DF",
            }
        return None

    def stooq(symbol):
        if symbol == "cl.f":
            return {
                "date": "2026-05-29",
                "value": 86.87,
                "updated_at": "2026-05-29T17:05:36Z",
                "points": [{"date": "2026-05-29T17:04:00Z", "value": 87.0}, {"date": "2026-05-29T17:05:36Z", "value": 86.87}],
                "change": -0.13,
                "source_url": "https://stooq.com/q/?s=cl.f",
            }
        return None

    monkeypatch.setattr(build_seed_snapshots, "_yahoo_chart_series", yahoo)
    monkeypatch.setattr(build_seed_snapshots, "_stooq_quote_series", stooq)

    tiles = build_seed_snapshots._macro_tiles("en", datetime(2026, 5, 29, 19, 10, tzinfo=timezone.utc))
    by_key = {tile["key"]: tile for tile in tiles}

    assert by_key["wti_crude"]["value"] == "86.87"
    assert by_key["wti_crude"]["source"] == "Stooq delayed quote"
    assert by_key["wti_crude"]["updated_at"] == "2026-05-29T17:05:36Z"
    assert "not guaranteed realtime exchange tape" in by_key["wti_crude"]["delay_label"]


def test_http_json_retries_retryable_status(monkeypatch):
    calls = []
    sleeps = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size=-1):
            return b'{"ok": true}'

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, timeout))
        if len(calls) == 1:
            raise error.HTTPError(
                req.full_url,
                429,
                "Too Many Requests",
                {"Retry-After": "0"},
                BytesIO(),
            )
        return FakeResponse()

    monkeypatch.setattr(build_seed_snapshots.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(build_seed_snapshots.time, "sleep", lambda seconds: sleeps.append(seconds))

    payload = build_seed_snapshots._http_json("https://example.test/data.json")

    assert payload == {"ok": True}
    assert len(calls) == 2
    assert sleeps == [0.0]


def test_twelve_data_quote_series_treats_date_only_payload_as_daily(monkeypatch):
    build_seed_snapshots._reset_runtime_caches()
    monkeypatch.setattr(build_seed_snapshots, "_runtime_env", lambda: {"TWELVE_DATA_API_KEY": "test-key"})
    monkeypatch.setattr(
        build_seed_snapshots,
        "_http_json",
        lambda *_args, **_kwargs: {
            "datetime": "2026-05-29",
            "close": "1504.21",
            "previous_close": "1499.00",
        },
    )

    series = build_seed_snapshots._twelve_data_quote_series("USD/KRW")

    assert series is not None
    assert series["updated_at"] == "2026-05-29T00:00:00Z"
    assert series["points"][0]["date"] == "2026-05-28T00:00:00Z"
    assert series["points"][1]["date"] == "2026-05-29T00:00:00Z"


def test_macro_tiles_use_treasury_xml_for_us_rates(monkeypatch):
    build_seed_snapshots._reset_runtime_caches()
    monkeypatch.setattr(build_seed_snapshots, "_web_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_pentagon_pizza_payload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_pentagon_pizza_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_yahoo_chart_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_stooq_quote_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_mof_jgb_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        build_seed_snapshots,
        "_treasury_yield_curve_rows",
        lambda _generated_at: [
            {"NEW_DATE": "2026-05-28T00:00:00", "BC_2YEAR": "4.01", "BC_3YEAR": "4.09", "BC_5YEAR": "4.17", "BC_10YEAR": "4.48"},
        ],
    )

    tiles = build_seed_snapshots._macro_tiles("en", datetime(2026, 5, 29, 12, tzinfo=timezone.utc))
    by_key = {tile["key"]: tile for tile in tiles}

    assert by_key["us_10y"]["value"] == "4.48"
    assert by_key["us_10y"]["source"] == "U.S. Treasury XML feed"
    assert "FRED" not in by_key["us_10y"]["source"]


def test_ishares_metric_parses_embedded_fund_metric():
    html = (
        '{"navAmount":{"active":true,"asOfDate":20260526,'
        '"formattedAsOfDate":"May 26, 2026","formattedValue":"197.71",'
        '"fullName":"fundHeader.fundNav.navAmount","value":197.709462}}'
    )

    metric = build_seed_snapshots._ishares_metric(html, "fundHeader.fundNav.navAmount")

    assert metric is not None
    assert metric["asOfDate"] == 20260526
    assert metric["value"] == 197.709462


def test_source_status_marks_krx_degraded_when_index_probe_failed(monkeypatch):
    build_seed_snapshots._reset_runtime_caches()
    monkeypatch.setenv("KRX_OPEN_API_AUTH_KEY", "test-key")
    bas_dd = build_seed_snapshots._recent_krx_dates(datetime.now(timezone.utc))[0]
    build_seed_snapshots._KRX_ERROR_CACHE[(build_seed_snapshots.KRX_INDEX_DAILY_PATH, bas_dd)] = "KRX returned HTTP 401"

    status = build_seed_snapshots._source_status()
    krx = next(provider for provider in status["providers"] if provider["provider_key"] == "krx_open_api")

    assert krx["status"] == "degraded"
    assert krx["warning"] == "KRX returned HTTP 401"


def test_build_snapshots_writes_news_seed_snapshots(tmp_path, monkeypatch):
    monkeypatch.setattr(build_seed_snapshots, "PUBLIC_ROOT", tmp_path)
    monkeypatch.setattr(build_seed_snapshots, "_web_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_pentagon_pizza_payload", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_pentagon_pizza_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_fred_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_treasury_yield_curve_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_mof_jgb_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_ishares_ewy_nav_series", lambda: None)
    monkeypatch.setattr(build_seed_snapshots, "_yahoo_chart_series", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(build_seed_snapshots, "_stooq_quote_series", lambda *_args, **_kwargs: None)

    build_seed_snapshots.build_snapshots()

    manifest = json.loads((tmp_path / "latest" / "manifest.json").read_text())
    required = {
        "news_index",
        "news_ticker_NVDA",
        "news_ticker_005930_KS",
        "news_ticker_RKLB",
        "news_ticker_IONQ",
        "news_region_USA",
        "news_region_KOR",
        "news_region_JPN",
        "news_region_BRA",
        "news_region_EU",
        "news_region_CHN",
        "news_topic_semiconductors",
        "news_topic_geopolitics",
        "news_topic_public_health",
        "news_topic_central_banks",
        "news_topic_energy",
    }

    assert required.issubset(manifest["objects"])
    for object_key in required:
        assert set(manifest["objects"][object_key]) == {"en", "ko"}

    index = json.loads((tmp_path / "v1" / "en" / "news" / "index.json").read_text())
    event_ids = {event["id"] for event in index["data"]["events"]}

    assert {
        "semiconductor_export_controls_seed",
        "central_bank_policy_watch_seed",
        "public_health_alert_seed",
        "rklb_launch_window_seed",
        "ionq_contract_watch_seed",
        "energy_geopolitical_supply_risk_seed",
    }.issubset(event_ids)
    assert index["data"]["filters"]["regions"]
    assert index["data"]["filters"]["topics"]
