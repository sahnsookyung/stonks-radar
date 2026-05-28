from __future__ import annotations

import hashlib
import csv
import io
import json
import os
import re
import time
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = Path(
    os.getenv("STONKS_SNAPSHOT_PUBLIC_ROOT", str(ROOT / "apps" / "web" / "public" / "public"))
).expanduser()
VERSION = 1
LOCALES = ["en", "ko"]
FRED_API_BASE_URL = "https://api.stlouisfed.org/fred"
FRED_SERIES_BASE_URL = "https://fred.stlouisfed.org/series"
GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
YAHOO_FINANCE_RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"
MOF_JGB_CSV_URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
MOF_JGB_PAGE_URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm"
ISHARES_EWY_URL = "https://www.ishares.com/us/products/239681/ishares-msci-south-korea-etf"
KRX_OPEN_API_BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"
KRX_SAMPLE_API_BASE_URL = "https://data-dbg.krx.co.kr/svc/sample/apis"
KRX_INDEX_DAILY_PATH = "idx/krx_dd_trd"
KRX_ETF_DAILY_PATH = "etp/etf_bydd_trd"
KRX_FUTURES_DAILY_PATH = "drv/fut_bydd_trd"
FRED_REQUEST_MIN_INTERVAL_SECONDS = 0.55
KRX_REQUEST_MIN_INTERVAL_SECONDS = 0.35
FINRA_API_BASE_URL = "https://api.finra.org"
FINRA_OAUTH_TOKEN_URL = "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token?grant_type=client_credentials"
FINRA_REQUEST_MIN_INTERVAL_SECONDS = 0.25
DEFAULT_SHORT_TICKERS = "DJT,TSLA,NVDA"
DEFAULT_NEWS_TICKERS = "RKLB,TSLA,NVDA,DJT"
DEFAULT_TRUMP_CIKS = {"DJT": "0001849635"}
PENTAGON_PIZZA_URL = "https://pentagon.pizza/"
OFFICIAL_POLICY_CALENDAR_URLS = {
    "federal_reserve": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "ecb": "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
    "bank_of_england": "https://www.bankofengland.co.uk/news/2025/september/monetary-policy-committee-dates-for-2026",
    "bank_of_japan": "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm",
    "bank_of_korea": "https://www.bok.or.kr/eng/main/contents.do?menuNo=400020",
    "bcb": "https://www.bcb.gov.br/detalhenoticia/20739/nota",
}
KRX_DOC_URLS = {
    "index_daily": "https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES001_S2.cmd?BO_ID=SsgXTEspyJESKvyXZtCU",
    "etf_daily": "https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES003_S2.cmd?BO_ID=nrEpCLaZpoLCTzPUMxuF",
    "futures_daily": "https://openapi.krx.co.kr/contents/OPP/USES/service/OPPUSES005_S2.cmd?BO_ID=ilaVYOabbaicHbKTsqga",
}
_RUNTIME_ENV: dict[str, str] | None = None
_FRED_CACHE: dict[str, dict[str, Any] | None] = {}
_MOF_JGB_CACHE: list[dict[str, Any]] | None = None
_KRX_ROWS_CACHE: dict[tuple[str, str], list[dict[str, Any]]] = {}
_KRX_ERROR_CACHE: dict[tuple[str, str], str] = {}
_FINRA_TOKEN_CACHE: dict[str, Any] = {"token": None, "expires_at": 0.0}
_FINRA_ROWS_CACHE: dict[str, list[dict[str, Any]]] = {}
_SEC_SUBMISSIONS_CACHE: dict[str, dict[str, Any] | None] = {}
_WEB_METADATA_CACHE: dict[str, dict[str, str] | None] = {}
_ISHARES_FUND_CACHE: dict[str, dict[str, Any] | None] = {}
_PENTAGON_PIZZA_CACHE: dict[str, dict[str, Any] | None] = {}
_GDELT_ARTICLE_CACHE: dict[str, list[dict[str, str]]] = {}
_RSS_ARTICLE_CACHE: dict[str, list[dict[str, str]]] = {}
_LAST_FRED_REQUEST_AT = 0.0
_LAST_KRX_REQUEST_AT = 0.0
_LAST_FINRA_REQUEST_AT = 0.0

SECTORS = {
    "space": {
        "en": "Space",
        "ko": "우주",
        "entities": ["Rocket Lab", "Intuitive Machines", "AST SpaceMobile", "Redwire", "SpaceX (private/reference)"],
        "exposure": ["USA", "KOR", "JPN", "EU"],
        "drivers_en": ["Launch cadence", "defense demand", "cash runway", "government contracts"],
        "drivers_ko": ["발사 일정", "국방 수요", "현금 런웨이", "정부 계약"],
    },
    "quantum": {
        "en": "Quantum",
        "ko": "양자",
        "entities": ["IONQ", "Rigetti", "D-Wave", "Quantum Computing Inc.", "Big Tech quantum divisions"],
        "exposure": ["USA", "EU", "JPN"],
        "drivers_en": ["Government funding", "technical milestone verification", "export controls"],
        "drivers_ko": ["정부 지원", "기술 마일스톤 검증", "수출통제"],
    },
    "semiconductors": {
        "en": "Semiconductors",
        "ko": "반도체",
        "entities": ["NVIDIA", "AMD", "Intel", "TSMC", "Samsung Electronics", "SK Hynix", "ASML", "Micron", "Broadcom"],
        "exposure": ["USA", "KOR", "TWN", "JPN", "EUROZONE"],
        "drivers_en": ["AI accelerator demand", "memory pricing", "foundry capacity", "export controls", "FX exposure"],
        "drivers_ko": ["AI 가속기 수요", "메모리 가격", "파운드리 용량", "수출통제", "환율 노출"],
    },
    "oil-energy": {
        "en": "Oil/Energy",
        "ko": "석유/에너지",
        "entities": ["Brent reference series", "WTI reference series", "Chevron", "ExxonMobil", "OPEC+", "EIA"],
        "exposure": ["USA", "BRA", "MIDDLE_EAST_OPEC_GCC", "EU"],
        "drivers_en": ["Inventories", "OPEC+ meetings", "sanctions", "supply disruptions", "chokepoints"],
        "drivers_ko": ["재고", "OPEC+ 회의", "제재", "공급 차질", "해상 요충지"],
    },
    "big-tech": {
        "en": "Big Tech",
        "ko": "빅테크",
        "entities": ["Alphabet", "Microsoft", "Apple", "Amazon", "Meta", "NVIDIA", "Tesla"],
        "exposure": ["USA", "EU", "CHN", "KOR", "JPN"],
        "drivers_en": ["Cloud growth", "AI capex", "antitrust", "buybacks", "major outages"],
        "drivers_ko": ["클라우드 성장", "AI 투자", "반독점", "자사주 매입", "대형 장애"],
    },
}

COUNTRIES = {
    "USA": ("United States", "미국", "country"),
    "BRA": ("Brazil", "브라질", "country"),
    "KOR": ("South Korea", "대한민국", "country"),
    "GBR": ("United Kingdom", "영국", "country"),
    "DEU": ("Germany", "독일", "country"),
    "CHN": ("China", "중국", "country"),
    "TWN": ("Taiwan", "대만", "country"),
    "JPN": ("Japan", "일본", "country"),
}

REGIONS = {
    "EUROZONE": ("Eurozone", "유로존", "region"),
    "EU": ("European Union", "유럽연합", "region"),
    "MIDDLE_EAST_OPEC_GCC": ("Middle East / OPEC+ / GCC", "중동 / OPEC+ / GCC", "region"),
    "TOP10_GDP_2026_WORLD_BANK": ("Dynamic Top-10 Economies", "동적 GDP 상위 10개 경제권", "region"),
}

SCENARIOS = {
    "ai-infra-capex": {
        "en": "AI Infrastructure Capex",
        "ko": "AI 인프라 투자",
        "thesis_en": "Tracks data-center, accelerator, memory, power, and cloud capex channels using approved public facts.",
        "thesis_ko": "승인된 공개 사실을 기반으로 데이터센터, 가속기, 메모리, 전력, 클라우드 투자 경로를 추적합니다.",
        "objects": ["NVIDIA", "Microsoft", "TSMC", "Samsung Electronics", "SK Hynix", "ASML"],
    },
    "energy-supply-shock": {
        "en": "Energy Supply Shock Watchlist",
        "ko": "에너지 공급 충격 워치리스트",
        "thesis_en": "Monitors inventories, OPEC+ meetings, sanctions, chokepoints, and integrated energy companies.",
        "thesis_ko": "재고, OPEC+ 회의, 제재, 해상 요충지, 통합 에너지 기업을 모니터링합니다.",
        "objects": ["OPEC+", "Chevron", "ExxonMobil", "WTI reference", "Brent reference"],
    },
    "asia-semiconductor-risk": {
        "en": "Asia Semiconductor Risk",
        "ko": "아시아 반도체 리스크",
        "thesis_en": "Maps Taiwan, Korea, Japan, export-control, memory, and foundry risk channels.",
        "thesis_ko": "대만, 한국, 일본, 수출통제, 메모리, 파운드리 리스크 경로를 매핑합니다.",
        "objects": ["TSMC", "Samsung Electronics", "SK Hynix", "ASML", "NVIDIA"],
    },
}


def build_snapshots() -> None:
    _reset_runtime_caches()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0)
    stale_after = generated_at + timedelta(hours=12)
    hard_expires_at = generated_at + timedelta(days=7)
    manifest: dict[str, Any] = {
        "current_version": VERSION,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "locales": LOCALES,
        "objects": {},
    }

    for locale in LOCALES:
        events = _events(locale, generated_at)
        calendar = _calendar(locale)
        macro_tiles = _preserve_previous_active_macro_tiles(locale, _macro_tiles(locale, generated_at))
        sector_tiles = [_sector_tile(key, locale, events) for key in SECTORS]
        scenario_summaries = [_scenario_summary(key, locale) for key in SCENARIOS]

        _write(
            manifest,
            "home",
            locale,
            ["home.json"],
            _envelope(
                locale,
                generated_at,
                stale_after,
                hard_expires_at,
                "home",
                "home",
                {
                    "headline": _t(locale, "Global market intelligence dashboard", "글로벌 시장 인텔리전스 대시보드"),
                    "summary": _t(
                        locale,
                        "Snapshot-first research dashboard for public, source-gated intelligence. It highlights monitored sectors, central-bank calendars, scenario baskets, and approved events without personalized advice.",
                        "공개 출처 정책을 통과한 정보를 스냅샷 우선 방식으로 보여주는 리서치 대시보드입니다. 개인화 조언 없이 섹터, 중앙은행 일정, 시나리오 바스켓, 승인 이벤트를 표시합니다.",
                    ),
                    "generated_label": generated_at.isoformat().replace("+00:00", "Z"),
                    "snapshot_health": {
                        "status": "fresh",
                        "age_minutes": 0,
                        "stale_after": stale_after.isoformat().replace("+00:00", "Z"),
                        "backend_dependency": "none_for_public_pages",
                    },
                    "top_events": events,
                    "macro_tiles": macro_tiles,
                    "alternative_signals": _alternative_signals(locale, generated_at),
                    "sector_tiles": sector_tiles,
                    "calendar_preview": calendar[:6],
                    "scenario_baskets": scenario_summaries,
                },
            ),
        )

        _write(
            manifest,
            "map_events",
            locale,
            ["map", "events.json"],
            _envelope(
                locale,
                generated_at,
                stale_after,
                hard_expires_at,
                "map_events",
                "events",
                {
                    "events": events,
                    "filters": {
                        "countries_regions": sorted({key for event in events for key in event["country_region_keys"]}),
                        "sectors": sorted({key for event in events for key in event["sector_keys"]}),
                        "severities": ["low", "medium", "high", "critical"],
                        "event_types": sorted({event["event_type"] for event in events}),
                    },
                },
            ),
        )

        _write(
            manifest,
            "calendar_upcoming",
            locale,
            ["calendar", "upcoming.json"],
            _envelope(
                locale,
                generated_at,
                stale_after,
                hard_expires_at,
                "calendar_upcoming",
                "upcoming",
                {
                    "items": calendar,
                    "central_banks": [item for item in calendar if item["release_type"] == "central_bank"],
                    "methodology": _t(
                        locale,
                        "Expectation labels preserve source taxonomy: official projection, licensed consensus, open survey, manual estimate, internal forecast, or unknown. Surprise is only shown when units are comparable and expectation type is valid.",
                        "예상치 라벨은 공식 전망, 라이선스 합의, 공개 설문, 수동 추정, 내부 전망, 미상으로 구분합니다. 단위 비교가 가능하고 예상치 유형이 유효할 때만 서프라이즈를 표시합니다.",
                    ),
                },
            ),
        )

        for key, names in {**COUNTRIES, **REGIONS}.items():
            object_id = f"country_{key}" if names[2] == "country" else f"region_{key}"
            path_group = "countries"
            _write(
                manifest,
                object_id,
                locale,
                [path_group, f"{key}.json"],
                _envelope(
                    locale,
                    generated_at,
                    stale_after,
                    hard_expires_at,
                    "country_region",
                    key,
                    _country_region_data(key, names, locale, events, calendar, generated_at),
                ),
            )

        for key in SECTORS:
            _write(
                manifest,
                f"sector_{key}",
                locale,
                ["sectors", f"{key}.json"],
                _envelope(
                    locale,
                    generated_at,
                    stale_after,
                    hard_expires_at,
                    "sector_page",
                    key,
                    _sector_page(key, locale, events, calendar, generated_at),
                ),
            )

        for key in SCENARIOS:
            _write(
                manifest,
                f"scenario_basket_{key}",
                locale,
                ["scenario-baskets", f"{key}.json"],
                _envelope(
                    locale,
                    generated_at,
                    stale_after,
                    hard_expires_at,
                    "scenario_basket",
                    key,
                    _scenario_page(key, locale, generated_at),
                ),
            )

        _write(
            manifest,
            "source_status",
            locale,
            ["status.json"],
            _envelope(
                locale,
                generated_at,
                stale_after,
                hard_expires_at,
                "source_status",
                "status",
                _source_status(),
            ),
        )

        _write(
            manifest,
            "correction_log",
            locale,
            ["corrections.json"],
            _envelope(
                locale,
                generated_at,
                stale_after,
                hard_expires_at,
                "correction_log",
                "corrections",
                {"entries": []},
            ),
        )

    latest = PUBLIC_ROOT / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    (latest / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


def _reset_runtime_caches() -> None:
    global _RUNTIME_ENV, _MOF_JGB_CACHE, _LAST_FRED_REQUEST_AT, _LAST_KRX_REQUEST_AT, _LAST_FINRA_REQUEST_AT
    _RUNTIME_ENV = None
    _FRED_CACHE.clear()
    _MOF_JGB_CACHE = None
    _KRX_ROWS_CACHE.clear()
    _KRX_ERROR_CACHE.clear()
    _FINRA_TOKEN_CACHE.clear()
    _FINRA_TOKEN_CACHE.update({"token": None, "expires_at": 0.0})
    _FINRA_ROWS_CACHE.clear()
    _SEC_SUBMISSIONS_CACHE.clear()
    _WEB_METADATA_CACHE.clear()
    _ISHARES_FUND_CACHE.clear()
    _PENTAGON_PIZZA_CACHE.clear()
    _GDELT_ARTICLE_CACHE.clear()
    _RSS_ARTICLE_CACHE.clear()
    _LAST_FRED_REQUEST_AT = 0.0
    _LAST_KRX_REQUEST_AT = 0.0
    _LAST_FINRA_REQUEST_AT = 0.0


def _runtime_env() -> dict[str, str]:
    global _RUNTIME_ENV
    if _RUNTIME_ENV is not None:
        return _RUNTIME_ENV
    loaded: dict[str, str] = {}
    default_env = ROOT / ".env"
    if default_env.exists():
        loaded.update(_read_env_file(default_env))
    explicit_env = os.getenv("STONKS_SNAPSHOT_ENV_FILE")
    if explicit_env:
        loaded.update(_read_env_file(Path(explicit_env).expanduser()))
    loaded.update({key: value for key, value in os.environ.items() if value})
    _RUNTIME_ENV = loaded
    return loaded


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env_has(env: dict[str, str], key: str) -> bool:
    return bool(str(env.get(key) or "").strip())


def _fred_series(series_id: str) -> dict[str, Any] | None:
    if series_id in _FRED_CACHE:
        return _FRED_CACHE[series_id]
    env = _runtime_env()
    api_key = env.get("FRED_API_KEY")
    if not api_key:
        _FRED_CACHE[series_id] = None
        return None

    global _LAST_FRED_REQUEST_AT
    elapsed = time.monotonic() - _LAST_FRED_REQUEST_AT
    if elapsed < FRED_REQUEST_MIN_INTERVAL_SECONDS:
        time.sleep(FRED_REQUEST_MIN_INTERVAL_SECONDS - elapsed)

    params = parse.urlencode(
        {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": "30",
        }
    )
    try:
        with request.urlopen(f"{FRED_API_BASE_URL}/series/observations?{params}", timeout=20) as response:
            payload = json.loads(response.read().decode())
    except Exception:
        _FRED_CACHE[series_id] = None
        return None
    finally:
        _LAST_FRED_REQUEST_AT = time.monotonic()

    observations = [
        item
        for item in payload.get("observations", [])
        if item.get("value") not in (None, "", ".") and item.get("date")
    ]
    points = []
    for item in reversed(observations[:4]):
        try:
            value = float(item["value"])
        except (TypeError, ValueError):
            continue
        points.append({"date": item["date"], "value": value})
    if not points:
        _FRED_CACHE[series_id] = None
        return None
    latest_point = points[-1]
    result = {"date": latest_point["date"], "value": latest_point["value"], "points": points}
    _FRED_CACHE[series_id] = result
    return result


def _mof_jgb_series(term: str) -> dict[str, Any] | None:
    rows = _mof_jgb_rows()
    points: list[dict[str, Any]] = []
    for row in reversed(rows):
        date = _iso_date(str(row.get("Date") or ""))
        value = _numeric_value(row.get(term))
        if not date or value is None:
            continue
        points.append({"date": date, "value": value})
        if len(points) >= 4:
            break
    points.reverse()
    if not points:
        return None
    latest_point = points[-1]
    return {"date": latest_point["date"], "value": latest_point["value"], "points": points}


def _mof_jgb_rows() -> list[dict[str, Any]]:
    global _MOF_JGB_CACHE
    if _MOF_JGB_CACHE is not None:
        return _MOF_JGB_CACHE
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    try:
        req = request.Request(MOF_JGB_CSV_URL, headers={"User-Agent": user_agent, "Accept": "text/csv,*/*"})
        with request.urlopen(req, timeout=20) as response:
            text = response.read(2_000_000).decode("utf-8-sig", errors="ignore")
    except Exception:
        _MOF_JGB_CACHE = []
        return _MOF_JGB_CACHE
    lines = text.splitlines()
    header_index = next((index for index, line in enumerate(lines) if line.startswith("Date,")), -1)
    if header_index < 0:
        _MOF_JGB_CACHE = []
        return _MOF_JGB_CACHE
    reader = csv.DictReader(io.StringIO("\n".join(lines[header_index:])))
    _MOF_JGB_CACHE = [row for row in reader if row.get("Date")]
    return _MOF_JGB_CACHE


def _krx_series(
    path: str,
    generated_at: datetime,
    *,
    predicate: Any,
    value_keys: tuple[str, ...],
) -> dict[str, Any] | None:
    if not _krx_auth_key():
        return None
    points: list[dict[str, Any]] = []
    for bas_dd in _recent_krx_dates(generated_at):
        rows = _krx_rows(path, bas_dd)
        matches = [row for row in rows if predicate(row)]
        for row in matches:
            value = _numeric_value(_row_value(row, value_keys))
            if value is None:
                continue
            date = _iso_date(str(row.get("BAS_DD") or bas_dd))
            if not date:
                continue
            points.append({"date": date, "value": value})
            break
        if len(points) >= 4:
            break
    points.reverse()
    if not points:
        return None
    latest_point = points[-1]
    return {"date": latest_point["date"], "value": latest_point["value"], "points": points}


def _krx_rows(path: str, bas_dd: str) -> list[dict[str, Any]]:
    cache_key = (path, bas_dd)
    if cache_key in _KRX_ROWS_CACHE:
        return _KRX_ROWS_CACHE[cache_key]
    auth_key = _krx_auth_key()
    if not auth_key:
        _KRX_ROWS_CACHE[cache_key] = []
        return []

    global _LAST_KRX_REQUEST_AT
    elapsed = time.monotonic() - _LAST_KRX_REQUEST_AT
    if elapsed < KRX_REQUEST_MIN_INTERVAL_SECONDS:
        time.sleep(KRX_REQUEST_MIN_INTERVAL_SECONDS - elapsed)

    params = parse.urlencode({"basDd": bas_dd})
    for base_url in _krx_base_urls():
        try:
            payload = _http_json(
                f"{base_url.rstrip('/')}/{path}.json?{params}",
                headers={"Accept": "application/json", "AUTH_KEY": auth_key},
                timeout=20,
            )
        except error.HTTPError as exc:
            _KRX_ROWS_CACHE[cache_key] = []
            _KRX_ERROR_CACHE[cache_key] = _krx_error_from_http_error(exc)
        except Exception as exc:
            _KRX_ROWS_CACHE[cache_key] = []
            _KRX_ERROR_CACHE[cache_key] = f"KRX request failed: {exc.__class__.__name__}"
        else:
            rows = payload.get("OutBlock_1") if isinstance(payload, dict) else []
            _KRX_ROWS_CACHE[cache_key] = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
            _KRX_ERROR_CACHE.pop(cache_key, None)
            if _KRX_ROWS_CACHE[cache_key]:
                break
        finally:
            _LAST_KRX_REQUEST_AT = time.monotonic()
    return _KRX_ROWS_CACHE[cache_key]


def _krx_base_urls() -> list[str]:
    env = _runtime_env()
    configured_base = str(env.get("KRX_OPEN_API_BASE_URL") or "").strip()
    if configured_base:
        return [configured_base]
    urls = [KRX_OPEN_API_BASE_URL]
    if _truthy(env.get("KRX_ALLOW_SAMPLE_API_FALLBACK")):
        urls.append(str(env.get("KRX_SAMPLE_API_BASE_URL") or KRX_SAMPLE_API_BASE_URL))
    return urls


def _krx_error_from_http_error(exc: error.HTTPError) -> str:
    body = ""
    try:
        body = exc.read(2_000).decode("utf-8", errors="ignore")
    except Exception:
        body = ""
    message = ""
    try:
        payload = json.loads(body) if body else {}
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        message = str(payload.get("respMsg") or payload.get("message") or "").strip()
    if exc.code == 401 and message:
        return f"KRX returned 401 {message}; confirm the API key is approved for this Open API service"
    if message:
        return f"KRX returned HTTP {exc.code}: {message}"
    return f"KRX returned HTTP {exc.code}"


def _krx_recent_error(path: str, generated_at: datetime) -> str | None:
    for bas_dd in _recent_krx_dates(generated_at):
        message = _KRX_ERROR_CACHE.get((path, bas_dd))
        if message:
            return message
    return None


def _krx_auth_key() -> str:
    env = _runtime_env()
    return str(env.get("KRX_OPEN_API_AUTH_KEY") or env.get("KRX_AUTH_KEY") or env.get("KRX_API_KEY") or "").strip()


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _recent_krx_dates(generated_at: datetime, lookback_days: int = 12) -> list[str]:
    korea_today = (generated_at + timedelta(hours=9)).date()
    dates = []
    for offset in range(lookback_days):
        day = korea_today - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        dates.append(day.strftime("%Y%m%d"))
    return dates


def _iso_date(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _finra_short_interest_rows(symbols: list[str]) -> list[dict[str, Any]]:
    return _finra_dataset_rows(
        "consolidatedShortInterest",
        symbol_field="symbolCode",
        date_field="settlementDate",
        symbols=symbols,
    )


def _finra_short_volume_rows(symbols: list[str]) -> list[dict[str, Any]]:
    return _finra_dataset_rows(
        "regShoDaily",
        symbol_field="securitiesInformationProcessorSymbolIdentifier",
        date_field="tradeReportDate",
        symbols=symbols,
    )


def _finra_dataset_rows(
    dataset: str,
    *,
    symbol_field: str,
    date_field: str,
    symbols: list[str],
) -> list[dict[str, Any]]:
    normalized = _symbol_list(",".join(symbols))
    cache_key = f"{dataset}:{','.join(normalized)}"
    if cache_key in _FINRA_ROWS_CACHE:
        return _FINRA_ROWS_CACHE[cache_key]
    token = _finra_bearer_token()
    if not token:
        _FINRA_ROWS_CACHE[cache_key] = []
        return []

    start_date = (datetime.now(timezone.utc) - timedelta(days=420)).date().isoformat()
    end_date = datetime.now(timezone.utc).date().isoformat()
    rows: list[dict[str, Any]] = []
    base_url = _runtime_env().get("FINRA_API_BASE_URL", FINRA_API_BASE_URL).rstrip("/")
    for symbol in normalized:
        payload = {
            "limit": 5000,
            "compareFilters": [
                {
                    "compareType": "equal",
                    "fieldName": symbol_field,
                    "fieldValue": symbol,
                }
            ],
            "dateRangeFilters": [
                {
                    "fieldName": date_field,
                    "startDate": start_date,
                    "endDate": end_date,
                }
            ],
        }
        try:
            response = _http_json(
                f"{base_url}/data/group/otcMarket/name/{dataset}",
                method="POST",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                payload=payload,
                timeout=25,
                throttle_key="finra",
            )
        except Exception:
            continue
        rows.extend(_json_rows(response))
    sorted_rows = sorted(rows, key=lambda row: (_row_date(row), _row_symbol(row)), reverse=True)
    _FINRA_ROWS_CACHE[cache_key] = sorted_rows
    return sorted_rows


def _finra_bearer_token() -> str | None:
    env = _runtime_env()
    api_token = str(env.get("FINRA_API_TOKEN") or "").strip()
    if api_token:
        return api_token
    client_id = str(env.get("FINRA_API_CLIENT_ID") or "").strip()
    client_secret = str(env.get("FINRA_API_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        return None
    now = time.time()
    cached = _FINRA_TOKEN_CACHE.get("token")
    if cached and float(_FINRA_TOKEN_CACHE.get("expires_at") or 0) > now:
        return str(cached)
    encoded = b64encode(f"{client_id}:{client_secret}".encode()).decode()
    token_url = str(env.get("FINRA_OAUTH_TOKEN_URL") or FINRA_OAUTH_TOKEN_URL)
    try:
        payload = _http_json(
            token_url,
            method="POST",
            headers={"Accept": "application/json", "Authorization": f"Basic {encoded}"},
            timeout=20,
            throttle_key="finra",
        )
    except Exception:
        return None
    token = str(payload.get("access_token") or "").strip()
    if not token:
        return None
    expires_in = int(payload.get("expires_in") or 1800)
    _FINRA_TOKEN_CACHE.update({"token": token, "expires_at": now + max(60, min(expires_in - 60, 1800))})
    return token


def _sec_submissions(cik: str) -> dict[str, Any] | None:
    padded = str(cik).zfill(10)
    if padded in _SEC_SUBMISSIONS_CACHE:
        return _SEC_SUBMISSIONS_CACHE[padded]
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    try:
        payload = _http_json(
            f"https://data.sec.gov/submissions/CIK{padded}.json",
            headers={"Accept": "application/json", "User-Agent": user_agent},
            timeout=20,
        )
    except Exception:
        payload = None
    _SEC_SUBMISSIONS_CACHE[padded] = payload if isinstance(payload, dict) else None
    return _SEC_SUBMISSIONS_CACHE[padded]


def _web_metadata(url: str) -> dict[str, str] | None:
    if url in _WEB_METADATA_CACHE:
        return _WEB_METADATA_CACHE[url]
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    try:
        req = request.Request(url, headers={"User-Agent": user_agent, "Accept": "text/html"})
        with request.urlopen(req, timeout=20) as response:
            html = response.read(600_000).decode("utf-8", errors="ignore")
    except Exception:
        _WEB_METADATA_CACHE[url] = None
        return None
    title = _html_field(html, r"<title[^>]*>(.*?)</title>") or parse.urlparse(url).netloc
    description = (
        _html_field(html, r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']+)[\"']")
        or _html_field(html, r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+name=[\"']description[\"']")
        or ""
    )
    _WEB_METADATA_CACHE[url] = {"title": title[:160], "description": description[:240]}
    return _WEB_METADATA_CACHE[url]


def _http_text(url: str, *, headers: dict[str, str] | None = None, timeout: int = 20, max_bytes: int = 600_000) -> str | None:
    try:
        req = request.Request(url, headers=headers or {})
        with request.urlopen(req, timeout=timeout) as response:
            return response.read(max_bytes).decode("utf-8", errors="ignore")
    except Exception:
        return None


def _ishares_ewy_nav_series() -> dict[str, Any] | None:
    if ISHARES_EWY_URL in _ISHARES_FUND_CACHE:
        return _ISHARES_FUND_CACHE[ISHARES_EWY_URL]
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    html = _http_text(
        ISHARES_EWY_URL,
        headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"},
        timeout=20,
        max_bytes=1_200_000,
    )
    if not html:
        _ISHARES_FUND_CACHE[ISHARES_EWY_URL] = None
        return None
    text = unescape(html)
    nav = _ishares_metric(text, "fundHeader.fundNav.navAmount")
    change = _ishares_metric(text, "fundHeader.fundNav.navAmountChange")
    percent = _ishares_metric(text, "fundHeader.fundNav.percentChange")
    if not nav or nav.get("value") is None:
        _ISHARES_FUND_CACHE[ISHARES_EWY_URL] = None
        return None
    date_text = _iso_date(str(nav.get("asOfDate") or "")) or _parse_ishares_formatted_date(str(nav.get("formattedAsOfDate") or ""))
    if not date_text:
        _ISHARES_FUND_CACHE[ISHARES_EWY_URL] = None
        return None
    value = float(nav["value"])
    points = [{"date": date_text, "value": value}]
    delta = _numeric_value(change.get("value")) if change else None
    if delta is not None:
        try:
            prior_date = (datetime.strptime(date_text, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()
        except ValueError:
            prior_date = date_text
        points.insert(0, {"date": prior_date, "value": value - delta})
    result = {
        "date": date_text,
        "value": value,
        "points": points,
        "change": delta,
        "percent_change": _numeric_value(percent.get("value")) if percent else None,
    }
    _ISHARES_FUND_CACHE[ISHARES_EWY_URL] = result
    return result


def _ishares_metric(text: str, full_name: str) -> dict[str, Any] | None:
    escaped = re.escape(full_name)
    match = re.search(r'\{[^{}]*"fullName"\s*:\s*"' + escaped + r'"[^{}]*\}', text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_ishares_formatted_date(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _pentagon_pizza_payload(base_url: str) -> dict[str, Any] | None:
    if base_url in _PENTAGON_PIZZA_CACHE:
        return _PENTAGON_PIZZA_CACHE[base_url]
    env = _runtime_env()
    user_agent = env.get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    function_url = str(env.get("PENTAGON_PIZZA_FUNCTION_URL") or "").strip()
    anon_key = str(env.get("PENTAGON_PIZZA_SUPABASE_ANON_KEY") or "").strip()
    html = _http_text(base_url, headers={"User-Agent": user_agent, "Accept": "text/html"})
    if (not function_url or not anon_key) and html:
        discovered = _discover_pentagon_pizza_api(base_url, html, user_agent)
        if discovered:
            function_url, anon_key = discovered
    if not function_url or not anon_key:
        _PENTAGON_PIZZA_CACHE[base_url] = None
        return None
    try:
        payload = _http_json(
            function_url,
            method="POST",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {anon_key}",
                "Content-Type": "application/json",
                "User-Agent": user_agent,
            },
            timeout=20,
        )
    except Exception:
        payload = None
    _PENTAGON_PIZZA_CACHE[base_url] = payload if isinstance(payload, dict) else None
    return _PENTAGON_PIZZA_CACHE[base_url]


def _discover_pentagon_pizza_api(base_url: str, html: str, user_agent: str) -> tuple[str, str] | None:
    script_text = ""
    script_match = re.search(r"<script[^>]+src=[\"']([^\"']+\.js)[\"']", html, flags=re.IGNORECASE)
    if script_match:
        script_url = parse.urljoin(base_url.rstrip("/") + "/", script_match.group(1))
        script_text = _http_text(script_url, headers={"User-Agent": user_agent, "Accept": "application/javascript"}) or ""
    source = f"{html}\n{script_text}"
    url_match = re.search(r"[\"'](https://[a-z0-9-]+\.supabase\.co)[\"']", source, flags=re.IGNORECASE)
    key_match = re.search(r"[\"'](eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)[\"']", source)
    if not url_match or not key_match:
        return None
    return f"{url_match.group(1).rstrip('/')}/functions/v1/fetch-busyness", key_match.group(1)


def _pentagon_pizza_summary(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    readings = payload.get("readings") if isinstance(payload, dict) else None
    values = [
        float(reading["busyness_level"])
        for reading in readings or []
        if isinstance(reading, dict) and isinstance(reading.get("busyness_level"), (int, float))
    ]
    if not values:
        return None
    typical_values = [
        float(reading["typical_level"])
        for reading in readings or []
        if isinstance(reading, dict) and isinstance(reading.get("typical_level"), (int, float))
    ]
    anomaly_count = payload.get("anomalyCount")
    if not isinstance(anomaly_count, int):
        anomaly_count = sum(1 for reading in readings or [] if isinstance(reading, dict) and reading.get("is_anomaly"))
    location_count = payload.get("locationCount")
    if not isinstance(location_count, int):
        location_count = len(values)
    return {
        "activity_score": round(sum(values) / len(values), 1),
        "typical_score": round(sum(typical_values) / len(typical_values), 1) if typical_values else None,
        "min_activity": min(values),
        "max_activity": max(values),
        "values": values,
        "timestamp": str(payload.get("timestamp") or datetime.now(timezone.utc).isoformat()),
        "location_count": location_count,
        "anomaly_count": anomaly_count,
        "data_source": str(payload.get("dataSource") or "unknown"),
    }


def _pentagon_pizza_points(summary: dict[str, Any], generated_at: datetime) -> list[dict[str, Any]]:
    values = sorted(float(value) for value in summary.get("values", []) if isinstance(value, (int, float)))
    if len(values) >= 4:
        chart_values = [values[0], values[len(values) // 3], values[(len(values) * 2) // 3], values[-1]]
    else:
        typical = summary.get("typical_score")
        chart_values = [
            float(summary["min_activity"]),
            float(typical if isinstance(typical, (int, float)) else summary["activity_score"]),
            float(summary["activity_score"]),
            float(summary["max_activity"]),
        ]
    return [
        {
            "date": (generated_at - timedelta(minutes=offset)).isoformat().replace("+00:00", "Z"),
            "value": round(value, 1),
        }
        for offset, value in zip((45, 30, 15, 0), chart_values, strict=True)
    ]


def _gdelt_articles(query: str, *, maxrecords: int = 5) -> list[dict[str, str]]:
    cache_key = f"{query}:{maxrecords}"
    if cache_key in _GDELT_ARTICLE_CACHE:
        return _GDELT_ARTICLE_CACHE[cache_key]
    params = parse.urlencode(
        {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "sort": "hybridrel",
            "maxrecords": str(maxrecords),
        }
    )
    try:
        payload = _http_json(f"{GDELT_DOC_API_URL}?{params}", headers={"Accept": "application/json"}, timeout=8)
    except Exception:
        _GDELT_ARTICLE_CACHE[cache_key] = []
        return []
    articles = payload.get("articles") if isinstance(payload, dict) else []
    rows: list[dict[str, str]] = []
    for index, article in enumerate(articles if isinstance(articles, list) else []):
        if not isinstance(article, dict):
            continue
        title = str(article.get("title") or "").strip()
        url = str(article.get("url") or "").strip()
        if not title or not url:
            continue
        rows.append(
            {
                "key": hashlib.sha1(f"{query}:{index}:{url}".encode()).hexdigest()[:12],
                "title": title[:140],
                "url": url,
                "domain": str(article.get("domain") or parse.urlparse(url).netloc or "news").strip()[:80],
                "seen_date": str(article.get("seendate") or "")[:14],
                "language": str(article.get("language") or "").strip()[:24],
            }
        )
    _GDELT_ARTICLE_CACHE[cache_key] = rows
    return rows


def _rss_articles(url: str, *, cache_key: str, maxrecords: int = 5) -> list[dict[str, str]]:
    if cache_key in _RSS_ARTICLE_CACHE:
        return _RSS_ARTICLE_CACHE[cache_key]
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    try:
        req = request.Request(url, headers={"User-Agent": user_agent, "Accept": "application/rss+xml, application/xml"})
        with request.urlopen(req, timeout=8) as response:
            xml_text = response.read(800_000).decode("utf-8", errors="ignore")
    except Exception:
        _RSS_ARTICLE_CACHE[cache_key] = []
        return []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        _RSS_ARTICLE_CACHE[cache_key] = []
        return []
    rows: list[dict[str, str]] = []
    for index, item in enumerate(root.findall(".//item")):
        title = _xml_text(item, "title")
        link = _xml_text(item, "link")
        if not title or not link:
            continue
        domain = parse.urlparse(link).netloc or _xml_text(item, "source") or "rss"
        rows.append(
            {
                "key": hashlib.sha1(f"{cache_key}:{index}:{link}".encode()).hexdigest()[:12],
                "title": title[:140],
                "url": link,
                "domain": domain[:80],
                "seen_date": _xml_text(item, "pubDate")[:32],
            }
        )
        if len(rows) >= maxrecords:
            break
    _RSS_ARTICLE_CACHE[cache_key] = rows
    return rows


def _xml_text(item: ElementTree.Element, tag: str) -> str:
    element = item.find(tag)
    if element is None or element.text is None:
        return ""
    return unescape(element.text.strip())


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: int = 20,
    throttle_key: str | None = None,
) -> Any:
    global _LAST_FINRA_REQUEST_AT
    if throttle_key == "finra":
        elapsed = time.monotonic() - _LAST_FINRA_REQUEST_AT
        if elapsed < FINRA_REQUEST_MIN_INTERVAL_SECONDS:
            time.sleep(FINRA_REQUEST_MIN_INTERVAL_SECONDS - elapsed)
    data = json.dumps(payload).encode() if payload is not None else None
    req = request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode())
    finally:
        if throttle_key == "finra":
            _LAST_FINRA_REQUEST_AT = time.monotonic()


def _json_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("results") or payload.get("rows") or []
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _symbol_list(raw: str | None) -> list[str]:
    values: list[str] = []
    for part in (raw or DEFAULT_SHORT_TICKERS).split(","):
        symbol = part.strip().upper()
        if symbol and re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,14}", symbol):
            values.append(symbol)
    return list(dict.fromkeys(values)) or _symbol_list(DEFAULT_SHORT_TICKERS)


def _latest_short_interest(rows: list[dict[str, Any]], symbols: list[str]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = _row_symbol(row)
        value = _numeric_value(_row_value(row, ("currentShortPositionQuantity", "currentShortShareNumber", "shortInterest", "short_interest", "currentShortPositionQty")))
        date = _row_date(row)
        if symbol not in symbols or value is None or not date:
            continue
        existing = latest.get(symbol)
        if not existing or date > existing["date"]:
            latest[symbol] = {"symbol": symbol, "date": date, "value": value}
    return [latest[symbol] for symbol in symbols if symbol in latest]


def _latest_short_volume(rows: list[dict[str, Any]], symbols: list[str]) -> list[dict[str, Any]]:
    totals: dict[tuple[str, str], float] = {}
    for row in rows:
        symbol = _row_symbol(row)
        date = _row_date(row)
        value = _numeric_value(_row_value(row, ("shortParQuantity", "shortVolume", "short_volume", "shortSaleVolume")))
        if symbol not in symbols or value is None or not date:
            continue
        totals[(symbol, date)] = totals.get((symbol, date), 0.0) + value
    latest: dict[str, dict[str, Any]] = {}
    for (symbol, date), value in totals.items():
        existing = latest.get(symbol)
        if not existing or date > existing["date"]:
            latest[symbol] = {"symbol": symbol, "date": date, "value": value}
    return [latest[symbol] for symbol in symbols if symbol in latest]


def _recent_sec_documents(cik: str, limit: int = 4) -> list[dict[str, str]]:
    padded = str(cik).zfill(10)
    payload = _sec_submissions(padded)
    if not payload:
        return []
    filings = payload.get("filings", {}).get("recent", {})
    accessions = filings.get("accessionNumber", [])
    forms = filings.get("form", [])
    dates = filings.get("filingDate", [])
    primary_docs = filings.get("primaryDocument", [])
    name = str(payload.get("name") or "SEC issuer")
    documents: list[dict[str, str]] = []
    for idx, accession in enumerate(accessions[:limit]):
        accession_text = str(accession)
        accession_no_dash = accession_text.replace("-", "")
        form = str(_list_item(forms, idx) or "filing")
        filing_date = str(_list_item(dates, idx) or "")
        primary_doc = str(_list_item(primary_docs, idx) or "")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(padded)}/{accession_no_dash}/"
        if primary_doc:
            url = f"{url}{primary_doc}"
        documents.append(
            {
                "title": f"{name} {form}",
                "form": form,
                "filing_date": filing_date,
                "accession_number": accession_text,
                "url": url,
            }
        )
    return documents


def _row_symbol(row: dict[str, Any]) -> str:
    value = (
        row.get("symbol")
        or row.get("symbolCode")
        or row.get("issueSymbolIdentifier")
        or row.get("ticker")
        or row.get("securitiesInformationProcessorSymbolIdentifier")
    )
    return str(value or "").strip().upper()


def _row_date(row: dict[str, Any]) -> str:
    value = row.get("settlementDate") or row.get("tradeReportDate") or row.get("date") or row.get("businessDate")
    return str(value or "")[:10]


def _row_value(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _numeric_value(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


def _format_count(value: float | int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B".rstrip("0").rstrip(".")
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M".rstrip("0").rstrip(".")
    if value >= 1_000:
        return f"{value / 1_000:.1f}K".rstrip("0").rstrip(".")
    return f"{value:,.0f}"


def _html_field(html: str, pattern: str) -> str | None:
    match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", match.group(1))).strip()
    return unescape(text) if text else None


def _list_item(values: Any, idx: int) -> Any:
    return values[idx] if isinstance(values, list) and idx < len(values) else None


def _format_metric_value(value: float, decimals: int) -> str:
    text = f"{value:,.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _actual_delay_label(locale: str, source: str, date: str) -> str:
    return _t(locale, f"{source} actual through {date}", f"{source} 실제값, {date}까지")


def _not_connected_label(locale: str) -> str:
    return _t(locale, "Not connected", "미연결")


def _unsupported_delay_label(locale: str, reason_en: str, reason_ko: str) -> str:
    return _t(locale, reason_en, reason_ko)


def _write(manifest: dict[str, Any], object_id: str, locale: str, relative_parts: list[str], payload: dict[str, Any]) -> None:
    path = PUBLIC_ROOT / f"v{VERSION}" / locale / Path(*relative_parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    manifest["objects"].setdefault(object_id, {})[locale] = f"public/v{VERSION}/{locale}/{'/'.join(relative_parts)}"


def _envelope(
    locale: str,
    generated_at: datetime,
    stale_after: datetime,
    hard_expires_at: datetime,
    object_type: str,
    object_key: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    content_hash = "sha256:" + hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {
        "schema_version": "1.0",
        "snapshot_version": VERSION,
        "locale": locale,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "stale_after": stale_after.isoformat().replace("+00:00", "Z"),
        "hard_expires_at": hard_expires_at.isoformat().replace("+00:00", "Z"),
        "object_type": object_type,
        "object_key": object_key,
        "content_hash": content_hash,
        "source_policy_versions": [
            {"source_key": "federal_reserve", "policy_version": 1},
            {"source_key": "sec_edgar", "policy_version": 1},
            {"source_key": "eia", "policy_version": 1},
            {"source_key": "world_bank", "policy_version": 1},
            {"source_key": "gdelt", "policy_version": 1},
            {"source_key": "google_news_rss", "policy_version": 1},
            {"source_key": "yahoo_finance_rss", "policy_version": 1},
        ],
        "data": data,
        "warnings": [
            {
                "code": "reference_delayed_market_data",
                "message": _t(locale, "Market indicators are delayed/reference unless licensed.", "시장 지표는 라이선스가 없는 한 지연/참조 데이터입니다."),
                "severity": "info",
            }
        ],
        "corrections": [],
    }


def _events(locale: str, generated_at: datetime) -> list[dict[str, Any]]:
    ts = generated_at.isoformat().replace("+00:00", "Z")
    return [
        {
            "id": "event_semis_export_controls_seed",
            "title": _t(locale, "Semiconductor export-control monitoring remains elevated", "반도체 수출통제 모니터링 강도 유지"),
            "summary": _t(locale, "Approved seed event links export-control risk to advanced chips, foundry exposure, and Asia supply chains.", "승인된 시드 이벤트가 첨단 칩, 파운드리 노출, 아시아 공급망을 수출통제 리스크와 연결합니다."),
            "why_it_matters": _t(locale, "The effect can propagate through AI accelerator availability, capex timing, and country exposure.", "AI 가속기 가용성, 투자 시점, 국가 노출을 통해 영향이 전파될 수 있습니다."),
            "occurred_at": ts,
            "published_at": ts,
            "country_region_keys": ["USA", "TWN", "KOR", "CHN", "JPN"],
            "sector_keys": ["semiconductors", "big-tech"],
            "event_type": "policy_risk",
            "severity": "medium",
            "confidence": 0.74,
            "source_strength": "reviewed_structured_seed",
            "freshness": "fresh",
            "evidence_count": 2,
            "latitude": 23.7,
            "longitude": 121.0,
            "affected_objects": ["NVIDIA", "TSMC", "Samsung Electronics", "SK Hynix", "ASML"],
            "source_links": [{"label": "Source policy seed", "url": "/en/source-policy", "source_key": "sec_edgar", "policy_version": 1}],
            "correction_status": "none",
        },
        {
            "id": "event_energy_inventory_seed",
            "title": _t(locale, "Energy inventory calendar is active for oil supply monitoring", "석유 공급 모니터링을 위한 에너지 재고 일정 활성"),
            "summary": _t(locale, "EIA-linked inventory releases are tracked as official structured data before publication.", "EIA 연계 재고 발표는 공개 전 공식 구조화 데이터로 추적됩니다."),
            "why_it_matters": _t(locale, "Inventory surprises can affect energy equities, inflation inputs, and geopolitical risk interpretation.", "재고 서프라이즈는 에너지 주식, 인플레이션 입력값, 지정학 리스크 해석에 영향을 줄 수 있습니다."),
            "occurred_at": ts,
            "published_at": ts,
            "country_region_keys": ["USA", "MIDDLE_EAST_OPEC_GCC"],
            "sector_keys": ["oil-energy"],
            "event_type": "official_calendar",
            "severity": "low",
            "confidence": 0.82,
            "source_strength": "official_structured",
            "freshness": "fresh",
            "evidence_count": 1,
            "latitude": 38.9,
            "longitude": -77.0,
            "affected_objects": ["WTI reference", "Brent reference", "Chevron", "ExxonMobil"],
            "source_links": [{"label": "EIA", "url": "https://www.eia.gov", "source_key": "eia", "policy_version": 1}],
            "correction_status": "none",
        },
        {
            "id": "event_central_bank_seed",
            "title": _t(locale, "Central-bank calendar coverage seeded across six policy committees", "6개 중앙은행 정책회의 일정 시드 적용"),
            "summary": _t(locale, "FOMC, ECB, BoE, BoJ, BoK, and Brazil COPOM are represented with explicit expectation labels.", "FOMC, ECB, BoE, BoJ, BoK, 브라질 COPOM이 명시적 예상치 라벨과 함께 표시됩니다."),
            "why_it_matters": _t(locale, "Calendar visibility reduces silent coverage gaps and makes stale policy data visible.", "캘린더 가시성은 커버리지 공백을 숨기지 않고 오래된 정책 데이터를 드러냅니다."),
            "occurred_at": ts,
            "published_at": ts,
            "country_region_keys": ["USA", "EUROZONE", "GBR", "JPN", "KOR", "BRA"],
            "sector_keys": ["big-tech", "semiconductors", "oil-energy"],
            "event_type": "central_bank_calendar",
            "severity": "low",
            "confidence": 0.78,
            "source_strength": "official_calendar_seed",
            "freshness": "fresh",
            "evidence_count": 6,
            "latitude": 51.5,
            "longitude": 0.0,
            "affected_objects": ["FOMC", "ECB", "BoE", "BoJ", "BoK", "COPOM"],
            "source_links": [
                {
                    "label": "Federal Reserve",
                    "url": OFFICIAL_POLICY_CALENDAR_URLS["federal_reserve"],
                    "source_key": "federal_reserve",
                    "policy_version": 1,
                },
                {"label": "ECB", "url": OFFICIAL_POLICY_CALENDAR_URLS["ecb"], "source_key": "ecb", "policy_version": 1},
                {
                    "label": "Bank of England",
                    "url": OFFICIAL_POLICY_CALENDAR_URLS["bank_of_england"],
                    "source_key": "bank_of_england",
                    "policy_version": 1,
                },
                {
                    "label": "Bank of Japan",
                    "url": OFFICIAL_POLICY_CALENDAR_URLS["bank_of_japan"],
                    "source_key": "bank_of_japan",
                    "policy_version": 1,
                },
                {
                    "label": "Bank of Korea",
                    "url": OFFICIAL_POLICY_CALENDAR_URLS["bank_of_korea"],
                    "source_key": "bank_of_korea",
                    "policy_version": 1,
                },
                {"label": "Banco Central do Brasil", "url": OFFICIAL_POLICY_CALENDAR_URLS["bcb"], "source_key": "bcb", "policy_version": 1},
            ],
            "correction_status": "none",
        },
    ]


def _preserve_previous_active_macro_tiles(locale: str, tiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous = _previous_macro_tiles(locale)
    if not previous:
        return tiles
    preserved: list[dict[str, Any]] = []
    for tile in tiles:
        previous_tile = previous.get(str(tile.get("key")))
        if not _is_metric_tile_unavailable(tile) or not previous_tile or _is_metric_tile_unavailable(previous_tile):
            preserved.append(tile)
            continue
        fallback = dict(previous_tile)
        fallback["freshness"] = "watch"
        fallback["delay_label"] = _t(
            locale,
            f"Using last published value; current refresh unavailable: {tile.get('delay_label', 'source unavailable')}",
            f"마지막 게시 값을 사용 중입니다. 현재 갱신 불가: {tile.get('delay_label', '출처 사용 불가')}",
        )
        preserved.append(fallback)
    return preserved


def _previous_macro_tiles(locale: str) -> dict[str, dict[str, Any]]:
    path = PUBLIC_ROOT / f"v{VERSION}" / locale / "home.json"
    if not path.exists():
        return {}
    try:
        snapshot = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    tiles = snapshot.get("data", {}).get("macro_tiles", [])
    if not isinstance(tiles, list):
        return {}
    return {
        str(tile["key"]): tile
        for tile in tiles
        if isinstance(tile, dict) and isinstance(tile.get("key"), str)
    }


def _is_metric_tile_unavailable(tile: dict[str, Any]) -> bool:
    value = str(tile.get("value", "")).strip().lower()
    return (
        tile.get("coverage_status") == "coverage_gap"
        or tile.get("freshness") == "unsupported"
        or value in {"source gap", "출처 공백", "not connected"}
    )


def _calendar(locale: str) -> list[dict[str, Any]]:
    items = [
        ("cal_fomc", "FOMC policy decision", "FOMC 정책 결정", "USA", "central_bank", "2026-06-17", "America/New_York", "official_projection", "Summary of Economic Projections meeting", "Federal Reserve"),
        ("cal_ecb", "ECB monetary-policy decision", "ECB 통화정책 결정", "EUROZONE", "central_bank", "2026-06-11", "Europe/Frankfurt", "official_calendar", "day 2 with press conference", "ECB"),
        ("cal_boe", "BoE MPC decision", "영란은행 MPC 결정", "GBR", "central_bank", "2026-06-18", "Europe/London", "official_calendar", "MPC announcement and minutes", "BoE"),
        ("cal_boj", "BoJ monetary-policy meeting", "일본은행 통화정책회의", "JPN", "central_bank", "2026-06-16", "Asia/Tokyo", "official_calendar", "meeting day 2", "BoJ"),
        ("cal_bok", "Bank of Korea decision", "한국은행 기준금리 결정", "KOR", "central_bank", "2026-05-28", "Asia/Seoul", "official_calendar", "policy-setting meeting", "BoK"),
        ("cal_copom", "Brazil COPOM decision", "브라질 COPOM 결정", "BRA", "central_bank", "2026-06-17", "America/Sao_Paulo", "official_calendar", "decision day", "BCB"),
        ("cal_us_cpi", "US CPI release", "미국 CPI 발표", "USA", "macro_release", "2026-06-10", "America/New_York", "manual_estimate", "manual estimate visible", "BLS"),
        ("cal_us_jobs", "US employment situation", "미국 고용보고서", "USA", "macro_release", "2026-06-05", "America/New_York", "unknown", None, "BLS"),
        ("cal_earnings_ai", "Monitored AI infrastructure earnings window", "AI 인프라 모니터링 기업 실적 구간", "USA", "earnings_window", "2026-06-30", "UTC", "unknown", None, "SEC/company IR"),
    ]
    return [
        {
            "id": item_id,
            "title": _t(locale, title_en, title_ko),
            "country_region_key": country,
            "release_type": release_type,
            "scheduled_at": f"{date}T12:00:00Z" if release_type != "earnings_window" else None,
            "scheduled_local_date": date,
            "timezone": timezone,
            "time_precision": "time_estimated" if release_type == "central_bank" else "date_only",
            "status": "scheduled",
            "expectation_type": expectation_type,
            "expectation_value": expectation_value,
            "actual_value": None,
            "previous_value": None,
            "surprise": None,
            "source": source,
            "freshness": "watch" if expectation_type == "unknown" else "fresh",
        }
        for item_id, title_en, title_ko, country, release_type, date, timezone, expectation_type, expectation_value, source in items
    ]


def _macro_tiles(locale: str, generated_at: datetime) -> list[dict[str, Any]]:
    updated = generated_at.isoformat().replace("+00:00", "Z")
    env = _runtime_env()
    pizza_url = str(env.get("PENTAGON_PIZZA_BASE_URL") or PENTAGON_PIZZA_URL)
    pizza_metadata = _web_metadata(pizza_url)
    pizza_summary = _pentagon_pizza_summary(_pentagon_pizza_payload(pizza_url))

    def rate_event(region: str) -> dict[str, str]:
        events = {
            "us": {
                "title": _t(locale, "FOMC policy decision", "FOMC 정책 결정"),
                "date": "2026-06-17",
                "timezone": "America/New_York",
                "source": "Federal Reserve FOMC calendar",
            },
            "japan": {
                "title": _t(locale, "BoJ monetary-policy meeting", "일본은행 통화정책회의"),
                "date": "2026-06-16",
                "timezone": "Asia/Tokyo",
                "source": "Bank of Japan MPM calendar",
            },
        }
        return events[region]

    def tile(
        key: str,
        label_en: str,
        label_ko: str,
        value: str,
        source: str,
        delay_label: str,
        freshness: str = "watch",
        unit: str | None = None,
        source_url: str | None = None,
        points: list[dict[str, Any]] | None = None,
        coverage_status: str = "active",
        next_event: dict[str, str] | None = None,
        refresh_seconds: int = 900,
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": key,
            "label": _t(locale, label_en, label_ko),
            "value": value,
            "source": source,
            "freshness": freshness,
            "delay_label": delay_label,
            "updated_at": updated_at or updated,
            "coverage_status": coverage_status,
            "refresh_seconds": refresh_seconds,
        }
        if unit:
            payload["unit"] = unit
        if source_url:
            payload["source_url"] = source_url
        if points:
            payload["points"] = points
        if next_event:
            payload["next_event"] = next_event
        return payload

    def fred_tile(
        key: str,
        label_en: str,
        label_ko: str,
        series_id: str,
        source: str,
        source_label: str,
        unit: str | None = None,
        decimals: int = 2,
        next_event: dict[str, str] | None = None,
        refresh_seconds: int = 900,
    ) -> dict[str, Any]:
        series = _fred_series(series_id)
        if not series:
            return tile(
                key,
                label_en,
                label_ko,
                _t(locale, "Source gap", "출처 공백"),
                source,
                _unsupported_delay_label(
                    locale,
                    "FRED_API_KEY missing or FRED series unavailable",
                    "FRED_API_KEY가 없거나 FRED 시리즈를 사용할 수 없습니다.",
                ),
                "watch",
                None,
                f"{FRED_SERIES_BASE_URL}/{series_id}",
                None,
                "coverage_gap",
                next_event,
                refresh_seconds,
            )
        return tile(
            key,
            label_en,
            label_ko,
            _format_metric_value(series["value"], decimals),
            source,
            _actual_delay_label(locale, source_label, series["date"]),
            "fresh",
            unit,
            f"{FRED_SERIES_BASE_URL}/{series_id}",
            series["points"],
            "active",
            next_event,
            refresh_seconds,
        )

    def mof_jgb_tile(
        key: str,
        label_en: str,
        label_ko: str,
        term: str,
        next_event: dict[str, str] | None = None,
        refresh_seconds: int = 900,
    ) -> dict[str, Any]:
        series = _mof_jgb_series(term)
        if not series:
            return tile(
                key,
                label_en,
                label_ko,
                _t(locale, "Source gap", "출처 공백"),
                "Japan MOF JGB yield curve",
                _unsupported_delay_label(
                    locale,
                    "Japan MOF historical JGB CSV unavailable during snapshot build",
                    "스냅샷 생성 중 일본 재무성 국채 금리 CSV를 사용할 수 없습니다.",
                ),
                "watch",
                "%",
                MOF_JGB_PAGE_URL,
                None,
                "coverage_gap",
                next_event,
                refresh_seconds,
            )
        return tile(
            key,
            label_en,
            label_ko,
            _format_metric_value(series["value"], 2),
            "Japan MOF JGB yield curve",
            _actual_delay_label(locale, f"MOF {term} JGB", series["date"]),
            "fresh",
            "%",
            MOF_JGB_PAGE_URL,
            series["points"],
            "active",
            next_event,
            refresh_seconds,
        )

    def krx_tile(
        key: str,
        label_en: str,
        label_ko: str,
        path: str,
        predicate: Any,
        value_keys: tuple[str, ...],
        source: str,
        source_url: str,
        unit: str | None = None,
        decimals: int = 2,
        refresh_seconds: int = 900,
    ) -> dict[str, Any]:
        if not _krx_auth_key():
            return coverage_gap_tile(
                key,
                label_en,
                label_ko,
                source,
                "KRX_OPEN_API_AUTH_KEY, KRX_AUTH_KEY, or KRX_API_KEY is required for official Korea Exchange data",
                "한국거래소 공식 데이터를 가져오려면 KRX_OPEN_API_AUTH_KEY, KRX_AUTH_KEY 또는 KRX_API_KEY가 필요합니다.",
                unit,
                source_url,
                refresh_seconds,
            )
        series = _krx_series(path, generated_at, predicate=predicate, value_keys=value_keys)
        if not series:
            error_message = _krx_recent_error(path, generated_at)
            reason_en = error_message or "KRX credentials are configured, but recent official rows were unavailable for this instrument"
            reason_ko = (
                "KRX 키가 구성되었지만 한국거래소 Open API 서비스에서 이 요청을 승인하지 않았습니다."
                if error_message and "401" in error_message
                else "KRX 자격 증명은 구성되었지만 이 상품의 최근 공식 행을 가져오지 못했습니다."
            )
            return coverage_gap_tile(
                key,
                label_en,
                label_ko,
                source,
                reason_en,
                reason_ko,
                unit,
                source_url,
                refresh_seconds,
            )
        return tile(
            key,
            label_en,
            label_ko,
            _format_metric_value(series["value"], decimals),
            source,
            _actual_delay_label(locale, source, series["date"]),
            "fresh",
            unit,
            source_url,
            series["points"],
            "active",
            None,
            refresh_seconds,
        )

    def ewy_korea_proxy_tile() -> dict[str, Any]:
        series = _ishares_ewy_nav_series()
        source = "iShares / BlackRock EWY"
        if not series:
            return coverage_gap_tile(
                "ewy_korea_proxy",
                "EWY Korea ETF NAV proxy",
                "EWY 한국 ETF NAV 프록시",
                source,
                "iShares EWY public NAV page unavailable during snapshot build",
                "스냅샷 생성 중 iShares EWY 공개 NAV 페이지를 사용할 수 없습니다.",
                "$",
                ISHARES_EWY_URL,
            )
        detail = _t(
            locale,
            f"iShares EWY NAV actual through {series['date']}; proxy for Korean equity exposure, not local exchange tape",
            f"iShares EWY NAV 실제값, {series['date']}까지; 한국 주식 노출 프록시이며 현지 거래소 시세가 아닙니다.",
        )
        payload = tile(
            "ewy_korea_proxy",
            "EWY Korea ETF NAV proxy",
            "EWY 한국 ETF NAV 프록시",
            _format_metric_value(float(series["value"]), 2),
            source,
            detail,
            "fresh",
            "$",
            ISHARES_EWY_URL,
            series.get("points"),
            "active",
            None,
            900,
        )
        if series.get("change") is not None:
            payload["refresh_delta"] = series["change"]
        if series.get("percent_change") is not None:
            payload["refresh_delta_percent"] = series["percent_change"]
        return payload

    def korea_equity_tiles() -> list[dict[str, Any]]:
        krx_tiles = [
            krx_tile(
                "krx_300",
                "KRX 300",
                "KRX 300",
                KRX_INDEX_DAILY_PATH,
                lambda row: str(row.get("IDX_NM") or "").replace(" ", "") == "KRX300",
                ("CLSPRC_IDX",),
                "KRX index daily trading",
                KRX_DOC_URLS["index_daily"],
            ),
            krx_tile(
                "krx_300_it",
                "KRX 300 IT",
                "KRX 300 정보기술",
                KRX_INDEX_DAILY_PATH,
                lambda row: str(row.get("IDX_NM") or "").replace(" ", "") in {"KRX300정보기술", "KRX300IT"},
                ("CLSPRC_IDX",),
                "KRX index daily trading",
                KRX_DOC_URLS["index_daily"],
            ),
        ]
        if all(tile.get("coverage_status") == "active" for tile in krx_tiles):
            return krx_tiles
        return [ewy_korea_proxy_tile()]

    def coverage_gap_tile(
        key: str,
        label_en: str,
        label_ko: str,
        source: str,
        reason_en: str,
        reason_ko: str,
        unit: str | None = None,
        source_url: str | None = None,
        refresh_seconds: int = 900,
    ) -> dict[str, Any]:
        return tile(
            key,
            label_en,
            label_ko,
            _t(locale, "Source gap", "출처 공백"),
            source,
            _unsupported_delay_label(locale, reason_en, reason_ko),
            "watch",
            None,
            source_url,
            None,
            "coverage_gap",
            None,
            refresh_seconds,
        )

    def pentagon_pizza_tile() -> dict[str, Any]:
        if pizza_summary:
            source_date = pizza_summary["timestamp"][:10]
            locations = int(pizza_summary["location_count"])
            anomalies = int(pizza_summary["anomaly_count"])
            anomaly_word = "anomaly" if anomalies == 1 else "anomalies"
            detail_en = f"Pentagon.Pizza average busyness across {locations} monitored sites; {anomalies} {anomaly_word}"
            detail_ko = f"Pentagon.Pizza 모니터링 지점 {locations}곳 평균 혼잡도; 이상치 {anomalies}건"
            detail_en += f" through {source_date}"
            detail_ko += f", {source_date}까지"
            return tile(
                "pentagon_pizza_index",
                "Pentagon pizza index",
                "펜타곤 피자 지수",
                _format_metric_value(float(pizza_summary["activity_score"]), 1),
                "Pentagon.Pizza",
                _t(locale, detail_en, detail_ko),
                "fresh",
                "/100",
                pizza_url,
                _pentagon_pizza_points(pizza_summary, generated_at),
                "active",
                None,
                300,
                str(pizza_summary["timestamp"]),
            )
        return tile(
            "pentagon_pizza_index",
            "Pentagon pizza index",
            "펜타곤 피자 지수",
            _t(locale, "Source gap", "출처 공백"),
            "Pentagon.Pizza",
            _unsupported_delay_label(
                locale,
                "Pentagon.Pizza activity API unavailable during snapshot build",
                "스냅샷 생성 중 Pentagon.Pizza 활동 API를 사용할 수 없었습니다.",
            ),
            "watch",
            "/100",
            pizza_url,
            None,
            "coverage_gap" if pizza_metadata else "coverage_gap",
            None,
            300,
        )

    return [
        fred_tile(
            "nasdaq_composite",
            "Nasdaq Composite",
            "나스닥 종합",
            "NASDAQCOM",
            "FRED / Nasdaq",
            "FRED NASDAQCOM",
        ),
        fred_tile(
            "nasdaq_100",
            "Nasdaq 100",
            "나스닥 100",
            "NASDAQ100",
            "FRED / Nasdaq",
            "FRED NASDAQ100",
        ),
        fred_tile(
            "kospi",
            "Korea share price index",
            "한국 주가지수",
            "SPASTT01KRM661N",
            "FRED / OECD Korea share prices",
            "FRED SPASTT01KRM661N",
        ),
        *korea_equity_tiles(),
        fred_tile("wti_crude", "WTI crude oil", "WTI 원유", "DCOILWTICO", "FRED / EIA", "FRED DCOILWTICO", "$", 2),
        fred_tile("vix", "VIX", "VIX", "VIXCLS", "FRED / Cboe", "FRED VIXCLS"),
        fred_tile("usd_krw", "USD/KRW", "달러/원", "DEXKOUS", "FRED / Federal Reserve H.10", "FRED DEXKOUS", "KRW", 2),
        fred_tile("usd_jpy", "USD/JPY", "달러/엔", "DEXJPUS", "FRED / Federal Reserve H.10", "FRED DEXJPUS", "JPY", 2),
        fred_tile("us_2y", "US Treasury 2Y", "미국 국채 2년", "DGS2", "FRED / US Treasury", "FRED DGS2", "%", 2, rate_event("us")),
        fred_tile("us_3y", "US Treasury 3Y", "미국 국채 3년", "DGS3", "FRED / US Treasury", "FRED DGS3", "%", 2, rate_event("us")),
        fred_tile("us_5y", "US Treasury 5Y", "미국 국채 5년", "DGS5", "FRED / US Treasury", "FRED DGS5", "%", 2, rate_event("us")),
        fred_tile("us_10y", "US Treasury 10Y", "미국 국채 10년", "DGS10", "FRED / US Treasury", "FRED DGS10", "%", 2, rate_event("us")),
        fred_tile(
            "japan_policy_rate",
            "BoJ policy rate",
            "일본은행 정책금리",
            "IRSTCB01JPM156N",
            "FRED / OECD Japan central bank rate",
            "FRED IRSTCB01JPM156N",
            "%",
            2,
            rate_event("japan"),
        ),
        mof_jgb_tile("japan_2y", "Japan govt 2Y", "일본 국채 2년", "2Y", rate_event("japan")),
        mof_jgb_tile("japan_5y", "Japan govt 5Y", "일본 국채 5년", "5Y", rate_event("japan")),
        mof_jgb_tile(
            "japan_10y",
            "Japan govt 10Y",
            "일본 국채 10년",
            "10Y",
            rate_event("japan"),
        ),
        pentagon_pizza_tile(),
    ]


def _alternative_signals(locale: str, generated_at: datetime) -> list[dict[str, Any]]:
    updated = generated_at.isoformat().replace("+00:00", "Z")
    env = _runtime_env()

    def item(
        lane_key: str,
        key: str,
        label_en: str,
        label_ko: str,
        value: str,
        detail_en: str,
        detail_ko: str,
        source: str,
        severity: str = "medium",
        freshness: str = "watch",
        source_url: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": f"{lane_key}_{key}",
            "label": _t(locale, label_en, label_ko),
            "value": value,
            "detail": _t(locale, detail_en, detail_ko),
            "source": source,
            "freshness": freshness,
            "severity": severity,
            "updated_at": updated,
        }
        if source_url:
            payload["source_url"] = source_url
        return payload

    symbols = _symbol_list(env.get("SHORT_VOLUME_MONITORED_TICKERS") or DEFAULT_SHORT_TICKERS)
    short_interest = _latest_short_interest(_finra_short_interest_rows(symbols), symbols)
    short_volume = _latest_short_volume(_finra_short_volume_rows(symbols), symbols)
    trump_documents = _recent_sec_documents(DEFAULT_TRUMP_CIKS["DJT"])
    ai_summary_ready = any(
        _env_has(env, key)
        for key in (
            "LOCAL_LLM_BASE_URL",
            "GEMINI_API_KEY",
            "GROQ_API_KEY",
            "CEREBRAS_API_KEY",
            "MISTRAL_API_KEY",
            "OPENROUTER_API_KEY",
            "HF_TOKEN",
        )
    )
    summary_status = _t(locale, "ready", "준비됨") if ai_summary_ready else _t(locale, "local LLM needed", "로컬 LLM 필요")
    news_queries = [
        (
            "geopolitical",
            "Geopolitical market risk",
            "지정학 시장 리스크",
            '(Iran OR Hormuz OR "Strait of Hormuz" OR "Red Sea" OR Taiwan OR "export controls") '
            '(oil OR shipping OR sanctions OR markets OR stocks)',
        ),
        (
            "tracked_tickers",
            "Tracked ticker headlines",
            "추적 티커 헤드라인",
            '("Rocket Lab" OR RKLB OR NVDA OR NVIDIA OR TSLA OR Tesla OR DJT OR "stock offering" OR "share issuance")',
        ),
    ]
    market_news_items: list[dict[str, Any]] = []
    for query_key, label_en, label_ko, query in news_queries:
        for article in _gdelt_articles(query, maxrecords=4):
            seen = article["seen_date"][:8]
            market_news_items.append(
                item(
                    "breaking_market_news",
                    f"{query_key}_{article['key']}",
                    article["title"],
                    article["title"],
                    _t(locale, "headline", "헤드라인"),
                    f"{label_en}; {article['domain']}" + (f"; seen {seen}" if seen else ""),
                    f"{label_ko}; {article['domain']}" + (f"; 관측 {seen}" if seen else ""),
                    "GDELT Doc API",
                    "high" if query_key == "geopolitical" else "medium",
                    "fresh",
                    article["url"],
                )
            )
    ticker_watchlist = ",".join(_symbol_list(env.get("NEWS_TICKER_WATCHLIST") or DEFAULT_NEWS_TICKERS))
    yahoo_url = f"{YAHOO_FINANCE_RSS_URL}?{parse.urlencode({'s': ticker_watchlist, 'region': 'US', 'lang': 'en-US'})}"
    rss_sources = [
        (
            "google_geopolitical",
            "Geopolitical market risk",
            "지정학 시장 리스크",
            "Google News RSS",
            f"{GOOGLE_NEWS_RSS_URL}?{parse.urlencode({'q': 'Iran OR Hormuz OR Taiwan export controls oil markets', 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})}",
            "high",
        ),
        (
            "yahoo_tickers",
            "Tracked ticker headlines",
            "추적 티커 헤드라인",
            "Yahoo Finance RSS",
            yahoo_url,
            "medium",
        ),
    ]
    seen_news_urls = {str(item.get("source_url") or "") for item in market_news_items}
    for source_key, label_en, label_ko, source_name, url, severity in rss_sources:
        for article in _rss_articles(url, cache_key=source_key, maxrecords=4):
            if article["url"] in seen_news_urls:
                continue
            seen_news_urls.add(article["url"])
            market_news_items.append(
                item(
                    "breaking_market_news",
                    f"{source_key}_{article['key']}",
                    article["title"],
                    article["title"],
                    _t(locale, "headline", "헤드라인"),
                    f"{label_en}; {article['domain']}" + (f"; seen {article['seen_date']}" if article["seen_date"] else ""),
                    f"{label_ko}; {article['domain']}" + (f"; 관측 {article['seen_date']}" if article["seen_date"] else ""),
                    source_name,
                    severity,
                    "fresh",
                    article["url"],
                )
            )
    if not market_news_items:
        market_news_article_count = 0
        market_news_items = [
            item(
                "breaking_market_news",
                "watchlist",
                "Breaking-news watchlist",
                "속보 워치리스트",
                _t(locale, "watch", "감시"),
                "GDELT and public RSS metadata are queried for geopolitical shocks and tracked ticker headlines when snapshots build.",
                "스냅샷 빌드 시 GDELT와 공개 RSS 메타데이터로 지정학 충격 및 추적 티커 헤드라인을 조회합니다.",
                "GDELT/RSS",
                "high",
                "watch",
                "https://www.gdeltproject.org/",
            )
        ]
    else:
        market_news_article_count = len(market_news_items)

    short_interest_items = [
        item(
            "highest_short_interest",
            row["symbol"].lower().replace(".", "_"),
            f"{row['symbol']} short interest",
            f"{row['symbol']} 공매도 잔고",
            f"{_format_count(row['value'])} shares",
            f"As of {row['date']}; open short positions, not daily short-sale volume.",
            f"{row['date']} 기준 미청산 공매도 포지션이며 일별 공매도 거래량이 아닙니다.",
            "FINRA consolidated short interest",
            "medium",
            "fresh",
            "https://www.finra.org/finra-data/browse-catalog/equity-short-interest",
        )
        for row in short_interest
    ]
    if not short_interest_items:
        short_interest_items = [
            item(
                "highest_short_interest",
                "credentials",
                "FINRA short interest",
                "FINRA 공매도 잔고",
                _t(locale, "waiting for rows", "행 대기"),
                "Credentials are configured, but the latest symbol-filtered rows were not available during this snapshot build.",
                "자격 증명은 구성되었지만 이번 스냅샷 빌드에서 최신 심볼 필터 행을 가져오지 못했습니다.",
                "FINRA",
                "medium",
                "watch",
            )
        ]
    short_interest_items.append(
        item(
            "highest_short_interest",
            "method",
            "Short interest is not short volume",
            "공매도 잔고와 공매도 거래량은 다름",
            "guardrail",
            "Short interest is open short positions. Daily short sale volume is transaction flow and can be much larger.",
            "공매도 잔고는 미청산 포지션입니다. 일별 공매도 거래량은 거래 흐름이며 훨씬 클 수 있습니다.",
            "FINRA",
            "medium",
            "fresh",
            "https://www.finra.org/investors/insights/short-interest",
        )
    )

    short_volume_items = [
        item(
            "short_volume_monitor",
            row["symbol"].lower().replace(".", "_"),
            f"{row['symbol']} short volume",
            f"{row['symbol']} 공매도 거래량",
            f"{_format_count(row['value'])} shares",
            f"Aggregated FINRA Reg SHO rows for trade date {row['date']}. This is flow, not outstanding short interest.",
            f"{row['date']} 거래일의 FINRA Reg SHO 행을 합산했습니다. 이는 거래 흐름이며 잔고가 아닙니다.",
            "FINRA Reg SHO daily short sale volume",
            "medium",
            "fresh",
            "https://developer.finra.org/docs/api-explorer/query_api-equity-reg_sho_daily_short_sale_volume",
        )
        for row in short_volume
    ]
    if not short_volume_items:
        short_volume_items = [
            item(
                "short_volume_monitor",
                "monitored",
                "Monitored tickers",
                "모니터링 티커",
                ", ".join(symbols),
                "FINRA Reg SHO rows were not available during this snapshot build.",
                "이번 스냅샷 빌드에서 FINRA Reg SHO 행을 가져오지 못했습니다.",
                "configuration",
                "medium",
                "watch",
            )
        ]

    trump_items = [
        item(
            "trump_filings",
            f"{document['form'].lower()}_{index}",
            f"DJT {document['form']}",
            f"DJT {document['form']}",
            f"filed {document['filing_date']}" if document["filing_date"] else "filed",
            f"{document['title']} · accession {document['accession_number']}",
            f"{document['title']} · 접수번호 {document['accession_number']}",
            "SEC EDGAR submissions API",
            "medium",
            "fresh",
            document["url"],
        )
        for index, document in enumerate(trump_documents[:3])
    ]
    if not trump_items:
        trump_items = [
            item(
                "trump_filings",
                "djt",
                "Trump Media & Technology Group",
                "트럼프 미디어",
                "SEC monitor",
                "DJT issuer filings and insider Forms 3/4/5 are tracked via SEC submissions.",
                "DJT 발행사 공시와 내부자 Form 3/4/5를 SEC submissions로 추적합니다.",
                "SEC EDGAR",
                "medium",
                "watch",
                "https://www.sec.gov/edgar/browse/?CIK=1849635",
            )
        ]
    trump_items.extend(
        [
            item(
                "trump_filings",
                "trust",
                "Donald J. Trump Revocable Trust",
                "도널드 J. 트럼프 취소가능 신탁",
                "entity caveat",
                "Keep beneficial-ownership filings separate from any unconfirmed 13F manager assumption.",
                "수익소유 공시와 확인되지 않은 13F 운용사 가정은 분리합니다.",
                "SEC EDGAR",
                "medium",
                "watch",
            ),
            item(
                "trump_filings",
                "ai_summary",
                "Long filing summaries",
                "장문 공시 요약",
                summary_status,
                "AI summaries are source-bound and generated from approved public facts or extract-only local text, not from secrets.",
                "AI 요약은 출처에 묶이며 비밀이 아니라 승인된 공개 사실 또는 추출 전용 로컬 텍스트에서 생성합니다.",
                "LLM router",
                "medium",
                "fresh" if ai_summary_ready else "watch",
            ),
        ]
    )

    top_interest = max(short_interest, key=lambda row: row["value"], default=None)
    top_volume = max(short_volume, key=lambda row: row["value"], default=None)
    latest_filing = trump_documents[0] if trump_documents else None

    return [
        {
            "key": "highest_short_interest",
            "title": _t(locale, "Short interest watch", "공매도 잔고 워치"),
            "summary": _t(
                locale,
                "Latest FINRA short-interest rows for tracked tickers. Float-adjusted ranking remains separate until float data is approved.",
                "추적 티커의 최신 FINRA 공매도 잔고 행입니다. 유통주식 조정 랭킹은 유통주식 데이터 승인 후 분리해 표시합니다.",
            ),
            "value": f"{top_interest['symbol']} {_format_count(top_interest['value'])}" if top_interest else _t(locale, "rows pending", "행 대기"),
            "cadence": _t(locale, "FINRA short interest is published twice monthly after settlement-date reporting.", "FINRA 공매도 잔고는 결제일 보고 후 월 2회 공개됩니다."),
            "source": "FINRA consolidated short interest",
            "source_url": "https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest",
            "freshness": "fresh" if short_interest else "watch",
            "severity": "medium",
            "refresh_seconds": 43200,
            "items": short_interest_items,
        },
        {
            "key": "short_volume_monitor",
            "title": _t(locale, "Daily short volume", "일별 공매도 거래량"),
            "summary": _t(
                locale,
                "Aggregated FINRA Reg SHO daily short-sale volume for the tracked ticker watchlist.",
                "추적 티커 워치리스트의 FINRA Reg SHO 일별 공매도 거래량 합산값입니다.",
            ),
            "value": f"{top_volume['symbol']} {_format_count(top_volume['value'])}" if top_volume else " / ".join(symbols),
            "cadence": _t(locale, "Daily after FINRA posts files, no later than 6:00 p.m. ET.", "FINRA 파일 공개 후 매일 갱신, 동부시간 오후 6시 이전 공개."),
            "source": "FINRA Reg SHO Daily Short Sale Volume",
            "source_url": "https://developer.finra.org/docs/api-explorer/query_api-equity-reg_sho_daily_short_sale_volume",
            "freshness": "fresh" if short_volume else "watch",
            "severity": "medium",
            "refresh_seconds": 900,
            "items": short_volume_items,
        },
        {
            "key": "breaking_market_news",
            "title": _t(locale, "Breaking market news", "시장 속보"),
            "summary": _t(
                locale,
                "GDELT and public RSS headline metadata for geopolitical chokepoints, sanctions, export controls, and tracked ticker catalysts.",
                "지정학 요충지, 제재, 수출통제, 추적 티커 촉매에 대한 GDELT 및 공개 RSS 헤드라인 메타데이터입니다.",
            ),
            "value": _t(locale, f"{market_news_article_count} headlines", f"헤드라인 {market_news_article_count}개")
            if market_news_article_count
            else _t(locale, "watchlist ready", "워치리스트 준비"),
            "cadence": _t(locale, "5-minute target for breaking-news metadata; source pages remain one click away.", "속보 메타데이터 5분 목표; 원문은 한 번의 클릭으로 이동합니다."),
            "source": "GDELT Doc API",
            "source_url": "https://www.gdeltproject.org/",
            "freshness": "fresh" if market_news_article_count else "watch",
            "severity": "high",
            "refresh_seconds": 300,
            "items": market_news_items[:6],
        },
        {
            "key": "short_research_reports",
            "title": _t(locale, "Public short research", "공개 숏 리서치"),
            "summary": _t(
                locale,
                "Tracks public reports from activist short sellers and forensic research publishers.",
                "액티비스트 숏셀러와 포렌식 리서치 발행사의 공개 보고서를 추적합니다.",
            ),
            "value": _t(locale, "8 sources", "8개 출처"),
            "cadence": _t(locale, "15-minute source checks once live ingestion is enabled.", "라이브 수집 활성화 후 15분 간격으로 출처를 점검합니다."),
            "source": "public research websites/RSS/news",
            "freshness": "watch",
            "severity": "high",
            "refresh_seconds": 900,
            "items": [
                item("short_research_reports", "hindenburg", "Hindenburg Research", "힌덴버그 리서치", "archived", "Founder announced shutdown; keep archive/news monitoring for follow-through.", "창업자가 폐쇄를 발표했으므로 아카이브/뉴스 후속 추적을 유지합니다.", "Hindenburg/news", "high", "watch", "https://hindenburgresearch.com/"),
                item("short_research_reports", "muddy_waters", "Muddy Waters", "머디 워터스", "active watch", "Known for public short theses and forensic reports.", "공개 숏 논지와 포렌식 보고서로 알려진 출처입니다.", "Muddy Waters", "high", "watch", "https://www.muddywatersresearch.com/"),
                item("short_research_reports", "viceroy", "Viceroy Research", "바이스로이 리서치", "active watch", "Known public activist short research publisher.", "공개 액티비스트 숏 리서치 발행사로 알려져 있습니다.", "Viceroy", "medium", "watch", "https://viceroyresearch.org/"),
                item("short_research_reports", "ai_summary", "AI report summaries", "AI 보고서 요약", summary_status, "Long public reports can be summarized after source-policy review; raw restricted text is not sent to external providers.", "긴 공개 보고서는 출처 정책 검토 후 요약할 수 있으며 제한 원문은 외부 제공자에게 보내지 않습니다.", "LLM router", "medium", "fresh" if ai_summary_ready else "watch"),
                item("short_research_reports", "spruce_point", "Spruce Point", "스프루스 포인트", "active watch", "Public forensic short research source.", "공개 포렌식 숏 리서치 출처입니다.", "Spruce Point", "medium", "watch", "https://www.sprucepointcap.com/"),
                item("short_research_reports", "kerrisdale", "Kerrisdale Capital", "케리스데일 캐피털", "active watch", "Publishes short and long research letters.", "롱/숏 리서치 레터를 공개합니다.", "Kerrisdale", "medium", "watch", "https://www.kerrisdalecap.com/"),
                item("short_research_reports", "culper", "Culper Research", "컬퍼 리서치", "active watch", "Public short research publisher.", "공개 숏 리서치 발행사입니다.", "Culper", "medium", "watch", "https://culperresearch.com/"),
                item("short_research_reports", "blue_orca", "Blue Orca Capital", "블루 오르카 캐피털", "active watch", "Known for public short reports.", "공개 숏 보고서로 알려져 있습니다.", "Blue Orca", "medium", "watch", "https://www.blueorcacapital.com/"),
                item("short_research_reports", "grizzly", "Grizzly Research", "그리즐리 리서치", "active watch", "Public short research source.", "공개 숏 리서치 출처입니다.", "Grizzly", "medium", "watch", "https://grizzlyreports.com/"),
            ],
        },
        {
            "key": "trump_filings",
            "title": _t(locale, "Trump-family filings", "트럼프 일가 공시"),
            "summary": _t(
                locale,
                "Direct SEC filing digest for tracked Trump-related public entities, with unresolved entity caveats kept visible.",
                "추적 중인 트럼프 관련 공개 엔티티의 SEC 공시 요약이며 미확정 엔티티 주의사항을 함께 표시합니다.",
            ),
            "value": f"{latest_filing['form']} {latest_filing['filing_date']}" if latest_filing else _t(locale, "SEC watch", "SEC 감시"),
            "cadence": _t(locale, "SEC submissions snapshot; poll no faster than the configured fair-access schedule.", "SEC submissions 스냅샷이며 설정된 공정 접근 주기보다 빠르게 폴링하지 않습니다."),
            "source": "SEC EDGAR / OGE disclosures",
            "source_url": "https://www.sec.gov/search-filings",
            "freshness": "fresh" if trump_documents else "watch",
            "severity": "medium",
            "refresh_seconds": 900,
            "items": trump_items,
        },
    ]


def _sector_tile(key: str, locale: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    sector = SECTORS[key]
    count = sum(1 for event in events if key in event["sector_keys"])
    return {
        "key": key,
        "name": sector[locale],
        "summary": _t(locale, f"Monitoring {len(sector['entities'])} entities with approved event and calendar links.", f"{len(sector['entities'])}개 객체를 승인 이벤트 및 일정과 함께 모니터링합니다."),
        "source_strength": "seeded_review_policy",
        "freshness": "fresh",
        "monitored_count": len(sector["entities"]),
        "event_count": count,
    }


def _sector_page(key: str, locale: str, events: list[dict[str, Any]], calendar: list[dict[str, Any]], generated_at: datetime) -> dict[str, Any]:
    sector = SECTORS[key]
    sector_events = [event for event in events if key in event["sector_keys"]]
    indicators = _macro_tiles(locale, generated_at)[:2]
    return {
        "key": key,
        "name": sector[locale],
        "overview": _t(locale, f"{sector['en']} module links monitored entities, country exposure, approved events, source strength, and delayed/reference indicators.", f"{sector['ko']} 모듈은 모니터링 객체, 국가 노출, 승인 이벤트, 출처 강도, 지연/참조 지표를 연결합니다."),
        "monitored_entities": sector["entities"],
        "monitored_instruments": [f"{name} reference/security metadata" for name in sector["entities"][:4]],
        "country_region_exposure": sector["exposure"],
        "recent_events": sector_events or events[:1],
        "upcoming_calendar_items": calendar[:4],
        "macro_geopolitical_drivers": sector[f"drivers_{locale}"],
        "reference_indicators": indicators,
        "scenario_baskets": [_scenario_summary(key2, locale) for key2 in SCENARIOS if key == "semiconductors" or key2 != "asia-semiconductor-risk"],
        "risks_and_caveats": [
            _t(locale, "Coverage is explicit; unsupported data remains labeled rather than inferred.", "지원 범위는 명시되며 미지원 데이터는 추론하지 않고 라벨링합니다."),
            _t(locale, "Market data is delayed/reference unless terms permit realtime public redistribution.", "시장 데이터는 조건상 실시간 공개 재배포가 허용되지 않는 한 지연/참조입니다."),
            _t(locale, "Scenario baskets are research watchlists, not personalized allocation advice.", "시나리오 바스켓은 리서치 워치리스트이며 개인화 배분 조언이 아닙니다."),
        ],
        "freshness": "fresh",
        "source_strength": "reviewed_seed",
    }


def _country_region_data(
    key: str,
    names: tuple[str, str, str],
    locale: str,
    events: list[dict[str, Any]],
    calendar: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any]:
    relevant_events = [event for event in events if key in event["country_region_keys"]]
    return {
        "key": key,
        "name": names[1 if locale == "ko" else 0],
        "type": names[2],
        "overview": _t(locale, f"{names[0]} coverage combines official macro calendars, sector exposure, source-strength labels, and approved events.", f"{names[1]} 커버리지는 공식 거시 일정, 섹터 노출, 출처 강도 라벨, 승인 이벤트를 결합합니다."),
        "source_strength": "official_or_reviewed_seed",
        "freshness": "fresh",
        "monitored_sectors": [_sector_tile(sector_key, locale, events) for sector_key in SECTORS],
        "recent_events": relevant_events or events[:1],
        "calendar_items": [item for item in calendar if item["country_region_key"] == key] or calendar[:2],
        "indicators": _macro_tiles(locale, generated_at),
    }


def _scenario_summary(key: str, locale: str) -> dict[str, Any]:
    item = SCENARIOS[key]
    return {
        "key": key,
        "name": item[locale],
        "thesis": item[f"thesis_{locale}"],
        "risk_summary": _t(locale, "Illustrative only; risk factors and data delays must remain visible.", "예시 목적이며 리스크 요인과 데이터 지연을 항상 표시해야 합니다."),
        "freshness": "fresh",
    }


def _scenario_page(key: str, locale: str, generated_at: datetime) -> dict[str, Any]:
    item = SCENARIOS[key]
    return {
        "key": key,
        "name": item[locale],
        "thesis": item[f"thesis_{locale}"],
        "methodology": _t(locale, "Illustrative weights are equal-weight seed placeholders until editor-approved methodology data is ingested. Inclusion is based on thematic exposure and reviewed public facts.", "예시 비중은 편집 승인 방법론 데이터 수집 전까지 동일가중 시드 placeholder입니다. 포함 기준은 테마 노출과 검토된 공개 사실입니다."),
        "included_objects": [
            {
                "name": name,
                "object_key": name.upper().replace(" ", "_"),
                "reason": _t(locale, "Thematic exposure under monitored scenario.", "모니터링 시나리오에 대한 테마 노출."),
                "illustrative_weight": "equal-weight seed",
            }
            for name in item["objects"]
        ],
        "risk_summary": _t(locale, "Scenario can fail if source data is stale, policy risk reverses, or sector exposure is weaker than expected.", "출처 데이터가 오래되거나 정책 리스크가 반전되거나 섹터 노출이 예상보다 약하면 시나리오가 실패할 수 있습니다."),
        "freshness_timestamp": generated_at.isoformat().replace("+00:00", "Z"),
        "data_delay_warning": _t(locale, "Uses delayed/reference indicators only; no brokerage connection or trade execution.", "지연/참조 지표만 사용하며 증권사 연결이나 주문 실행은 없습니다."),
        "disclaimer": _t(locale, "Research only. Not personalized financial advice. Do not treat this as a buy, sell, or allocation recommendation.", "리서치 목적입니다. 개인화 금융 조언이 아니며 매수, 매도, 배분 추천으로 해석하지 마십시오."),
        "approval_status": "approved",
    }


def _source_status() -> dict[str, Any]:
    env = _runtime_env()

    def status_for(keys: str | tuple[str, ...], warning: str | None) -> tuple[str, str | None]:
        if isinstance(keys, str):
            ready = _env_has(env, keys)
        else:
            ready = all(_env_has(env, key) for key in keys)
        return ("ready", None) if ready else ("missing_credentials", warning)

    fred_status, fred_warning = status_for("FRED_API_KEY", "FRED_API_KEY required for live ingest")
    bls_status, bls_warning = status_for("BLS_API_KEY", "BLS_API_KEY enables higher-limit BLS ingest")
    eia_status, eia_warning = status_for("EIA_API_KEY", "EIA_API_KEY required for live ingest")
    sec_user_agent = env.get("SEC_USER_AGENT", "")
    sec_status = "ready" if "@" in sec_user_agent and "contact@example.com" not in sec_user_agent else "degraded"
    sec_warning = None if sec_status == "ready" else "SEC_USER_AGENT must contain a real contact in production"
    twelve_status, twelve_warning = status_for("TWELVE_DATA_API_KEY", "TWELVE_DATA_API_KEY enables portfolio history primary")
    alpha_status, alpha_warning = status_for("ALPHA_VANTAGE_API_KEY", "ALPHA_VANTAGE_API_KEY enables portfolio history fallback")
    fmp_status, fmp_warning = status_for("FMP_API_KEY", "FMP_API_KEY enables EOD/fundamental fallback")
    finnhub_status, finnhub_warning = status_for("FINNHUB_API_KEY", "FINNHUB_API_KEY enables future market/fundamental fallback")
    nasdaq_status, nasdaq_warning = status_for("NASDAQ_DATA_LINK_API_KEY", "NASDAQ_DATA_LINK_API_KEY enables future Nasdaq Data Link datasets")
    if any(_env_has(env, key) for key in ("KRX_OPEN_API_AUTH_KEY", "KRX_AUTH_KEY", "KRX_API_KEY")):
        krx_warning = _krx_recent_error(KRX_INDEX_DAILY_PATH, datetime.now(timezone.utc))
        krx_status = "degraded" if krx_warning else "ready"
    else:
        krx_status, krx_warning = (
            "missing_credentials",
            "KRX_OPEN_API_AUTH_KEY, KRX_AUTH_KEY, or KRX_API_KEY required for KRX index daily-trading ingest",
        )
    if _env_has(env, "FINRA_API_TOKEN") or (_env_has(env, "FINRA_API_CLIENT_ID") and _env_has(env, "FINRA_API_CLIENT_SECRET")):
        finra_status, finra_warning = "ready", None
    else:
        finra_status, finra_warning = (
            "missing_credentials",
            "FINRA_API_CLIENT_ID and FINRA_API_CLIENT_SECRET required for short interest and Reg SHO short volume ingest",
        )
    gemini_status, gemini_warning = status_for("GEMINI_API_KEY", "GEMINI_API_KEY optional; public facts only")
    groq_status, groq_warning = status_for("GROQ_API_KEY", "GROQ_API_KEY optional; public facts only")
    cerebras_status, cerebras_warning = status_for("CEREBRAS_API_KEY", "CEREBRAS_API_KEY optional; public facts only")
    mistral_status, mistral_warning = status_for("MISTRAL_API_KEY", "MISTRAL_API_KEY optional; public facts only")
    openrouter_status, openrouter_warning = status_for("OPENROUTER_API_KEY", "OPENROUTER_API_KEY optional; public facts only")
    hf_status, hf_warning = status_for("HF_TOKEN", "HF_TOKEN optional; public facts only")
    local_status = "ready" if _env_has(env, "LOCAL_LLM_BASE_URL") else "missing_credentials"
    local_warning = None if local_status == "ready" else "LOCAL_LLM_BASE_URL enables private local research"

    providers = [
        ("fred", "official_api", fred_status, "FREE_ONLY", fred_warning),
        ("bls", "official_api", bls_status, "FREE_ONLY", bls_warning),
        ("eia", "official_api", eia_status, "FREE_ONLY", eia_warning),
        ("sec_edgar", "filing", sec_status, "FREE_ONLY", sec_warning),
        ("oge_disclosures", "filing", sec_status, "FREE_ONLY", sec_warning),
        ("twelve_data", "market_data", twelve_status, "FREE_ONLY", twelve_warning),
        ("alpha_vantage", "market_data", alpha_status, "FREE_ONLY", alpha_warning),
        ("fmp", "market_data", fmp_status, "FREE_ONLY", fmp_warning),
        ("finnhub", "market_data", finnhub_status, "FREE_ONLY", finnhub_warning),
        ("nasdaq_data_link", "market_data", nasdaq_status, "FREE_ONLY", nasdaq_warning),
        ("krx_open_api", "official_api", krx_status, "FREE_ONLY", krx_warning),
        ("japan_mof_jgb_csv", "official_csv", "ready", "FREE_ONLY", None),
        ("finra", "official_api", finra_status, "FREE_ONLY", finra_warning),
        ("gdelt", "news_metadata", "ready", "FREE_ONLY", None),
        ("google_news_rss", "news_metadata", "ready", "FREE_ONLY", None),
        ("yahoo_finance_rss", "news_metadata", "ready", "FREE_ONLY", None),
        ("pentagon_pizza", "weak_osint", "degraded", "FREE_ONLY", "Weak OSINT only; cannot publish standalone high-confidence events"),
        ("public_short_research", "public_web", "degraded", "FREE_ONLY", "Public short-report monitors need source-specific parser review"),
        ("gemini", "llm_provider", gemini_status, "FREE_ONLY", gemini_warning),
        ("groq", "llm_provider", groq_status, "FREE_ONLY", groq_warning),
        ("cerebras", "llm_provider", cerebras_status, "FREE_ONLY", cerebras_warning),
        ("mistral", "llm_provider", mistral_status, "FREE_ONLY", mistral_warning),
        ("openrouter", "llm_provider", openrouter_status, "FREE_ONLY", openrouter_warning),
        ("huggingface", "llm_provider", hf_status, "FREE_ONLY", hf_warning),
        ("local", "llm_provider", local_status, "LOCAL_ONLY", local_warning),
    ]
    return {
        "snapshot_age_minutes": 0,
        "degraded_mode": False,
        "backend_required_for_public_pages": False,
        "providers": [
            {
                "provider_key": key,
                "provider_type": typ,
                "status": status,
                "mode": mode,
                "last_verified_at": None,
                "warning": warning,
            }
            for key, typ, status, mode, warning in providers
        ],
        "operations": {
            "disk_watermark": "unknown_until_monitor_runs",
            "snapshot_storage_status": "local_seed",
            "backup_status": "local_encrypted_backups_not_configured",
            "restore_drill_at": None,
        },
    }


def _t(locale: str, en: str, ko: str) -> str:
    return ko if locale == "ko" else en


if __name__ == "__main__":
    build_snapshots()
