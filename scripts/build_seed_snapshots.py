from __future__ import annotations

import hashlib
import csv
import io
import json
import os
import re
import time
import zipfile
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = Path(
    os.getenv("STONKS_SNAPSHOT_PUBLIC_ROOT", str(ROOT / "apps" / "web" / "public" / "public"))
).expanduser()
VERSION = 1
LOCALES = ["en", "ko"]
FRED_API_BASE_URL = "https://api.stlouisfed.org/fred"
FRED_SERIES_BASE_URL = "https://fred.stlouisfed.org/series"
GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
GDELT_EXPORT_SUFFIX = ".export.CSV.zip"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
YAHOO_FINANCE_RSS_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline"
YAHOO_FINANCE_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
YAHOO_FINANCE_QUOTE_URL = "https://finance.yahoo.com/quote"
STOOQ_QUOTE_URL = "https://stooq.com/q/l/"
STOOQ_QUOTE_TIMEZONE = ZoneInfo("Europe/Warsaw")
FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote"
TWELVE_DATA_QUOTE_URL = "https://api.twelvedata.com/quote"
TREASURY_YIELD_XML_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
TREASURY_YIELD_FEED_DOC_URL = "https://home.treasury.gov/treasury-daily-interest-rate-xml-feed"
MOF_JGB_CSV_URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"
MOF_JGB_PAGE_URL = "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm"
ISHARES_EWY_URL = "https://www.ishares.com/us/products/239681/ishares-msci-south-korea-etf"
BOJ_TIMESERIES_API_URL = "https://www.stat-search.boj.or.jp/api/v1/getDataCode"
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
DEFAULT_NEWS_TICKERS = "DJT,TSLA,NVDA,RKLB,IONQ,RGTI,QBTS,QUANTINUUM,LUNR,ASTS,RDW,AMD,AAPL,MSFT,TLT,005930.KS"
DEFAULT_TRUMP_CIKS = {"DJT": "0001849635"}
TRACKED_ENTITY_REGISTRY_PATH = ROOT / "config" / "tracked_entities.json"
GEOPOLITICAL_WATCH_REGISTRY_PATH = ROOT / "config" / "geopolitical_watch_registry.json"
CUSIP_TICKER_OVERRIDES_PATH = ROOT / "config" / "cusip_ticker_overrides.json"
TRACKED_ENTITY_WATCHLIST_PATH = ROOT / "apps" / "api" / "src" / "frw_api" / "services" / "news" / "ticker_watchlist.generated.json"
FUND_PORTFOLIOS = {
    "situational-awareness": {
        "display_name": "Leopold Aschenbrenner 13F Portfolio",
        "display_name_ko": "레오폴드 아셴브레너 13F 포트폴리오",
        "manager_name": "Leopold Aschenbrenner",
        "fund_name": "Situational Awareness LP",
        "cik": "0002045724",
        "source_url": "https://www.sec.gov/edgar/browse/?CIK=0002045724",
    }
}
TIME_SENSITIVE_MARKET_TILE_KEYS = {
    "nasdaq_composite",
    "nasdaq_100",
    "kospi",
    "kodex_200",
    "krx_300",
    "krx_300_it",
    "ewy_korea_proxy",
    "wti_crude",
    "gold_futures",
    "silver_futures",
    "copper_futures",
    "vix",
    "usd_krw",
    "usd_jpy",
    "japan_policy_rate",
}
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
_SEC_FUND_PORTFOLIO_CACHE: dict[str, dict[str, Any] | None] = {}
_CUSIP_TICKER_OVERRIDES_CACHE: dict[str, str | None] | None = None
_WEB_METADATA_CACHE: dict[str, dict[str, str] | None] = {}
_ISHARES_FUND_CACHE: dict[str, dict[str, Any] | None] = {}
_BOJ_SERIES_CACHE: dict[tuple[str, str, str], dict[str, Any] | None] = {}
_PENTAGON_PIZZA_CACHE: dict[str, dict[str, Any] | None] = {}
_YAHOO_QUOTE_CACHE: dict[str, dict[str, Any] | None] = {}
_STOOQ_QUOTE_CACHE: dict[str, dict[str, Any] | None] = {}
_FINNHUB_QUOTE_CACHE: dict[str, dict[str, Any] | None] = {}
_TWELVE_DATA_QUOTE_CACHE: dict[str, dict[str, Any] | None] = {}
_TREASURY_YIELD_CACHE: dict[str, Any] | None = None
_GDELT_ARTICLE_CACHE: dict[str, list[dict[str, str]]] = {}
_RSS_ARTICLE_CACHE: dict[str, list[dict[str, str]]] = {}
_TRACKED_ENTITY_CACHE: list[dict[str, Any]] | None = None
_GEOPOLITICAL_REGISTRY_CACHE: dict[str, Any] | None = None
_SECTOR_SHORT_FACT_CACHE: dict[tuple[str, str], list[dict[str, Any]]] = {}
_LAST_FRED_REQUEST_AT = 0.0
_LAST_KRX_REQUEST_AT = 0.0
_LAST_FINRA_REQUEST_AT = 0.0
_LAST_HTTP_PROVIDER_REQUEST_AT: dict[str, float] = {}

HTTP_RETRY_STATUS_CODES = {408, 429, 500, 502, 503, 504}
HTTP_DEFAULT_MAX_ATTEMPTS = 2
HTTP_DEFAULT_MAX_RETRY_DELAY_SECONDS = 3.0
HTTP_PROVIDER_MIN_INTERVAL_SECONDS = {
    "fred": FRED_REQUEST_MIN_INTERVAL_SECONDS,
    "krx": KRX_REQUEST_MIN_INTERVAL_SECONDS,
    "finra": FINRA_REQUEST_MIN_INTERVAL_SECONDS,
    "yahoo_finance_delayed_quote": 0.25,
    "stooq_delayed_quote": 0.45,
    "finnhub_quote": 2.1,
    "twelve_data_quote": 10.2,
    "ishares_ewy": 1.0,
    "boj_timeseries": 0.5,
    "gdelt_doc": 6.0,
}

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
        "entities": ["IONQ", "Rigetti", "D-Wave", "Quantinuum (private/reference)", "Quantum Computing Inc.", "Big Tech quantum divisions"],
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

NEWS_TICKER_KO_NAMES = {
    "DJT": "트럼프 미디어",
    "TSLA": "테슬라",
    "NVDA": "엔비디아",
    "005930.KS": "삼성전자",
    "RKLB": "로켓랩 USA",
    "IONQ": "아이온큐",
    "RGTI": "리게티 컴퓨팅",
    "QBTS": "디웨이브 퀀텀",
    "QUANTINUUM": "퀀티넘",
    "LUNR": "인튜이티브 머신스",
    "ASTS": "AST 스페이스모바일",
    "RDW": "레드와이어",
    "AMD": "AMD",
    "AAPL": "애플",
    "MSFT": "마이크로소프트",
    "TLT": "아이셰어즈 장기 미국채 ETF",
}

NEWS_TICKER_EXCHANGES = {
    "DJT": "NASDAQ",
    "TSLA": "NASDAQ",
    "NVDA": "NASDAQ",
    "005930.KS": "KRX",
    "RKLB": "NASDAQ",
    "IONQ": "NYSE",
    "RGTI": "NASDAQ",
    "QBTS": "NYSE",
    "QUANTINUUM": "PRIVATE",
    "LUNR": "NASDAQ",
    "ASTS": "NASDAQ",
    "RDW": "NYSE",
    "AMD": "NASDAQ",
    "AAPL": "NASDAQ",
    "MSFT": "NASDAQ",
    "TLT": "NASDAQ",
}


def _tracked_entity_records() -> list[dict[str, Any]]:
    global _TRACKED_ENTITY_CACHE
    if _TRACKED_ENTITY_CACHE is not None:
        return _TRACKED_ENTITY_CACHE
    if TRACKED_ENTITY_REGISTRY_PATH.exists():
        payload = json.loads(TRACKED_ENTITY_REGISTRY_PATH.read_text())
    elif TRACKED_ENTITY_WATCHLIST_PATH.exists():
        payload = json.loads(TRACKED_ENTITY_WATCHLIST_PATH.read_text())
    else:
        payload = {"entities": []}
    records = [entity for entity in payload.get("entities", []) if isinstance(entity, dict)]
    _TRACKED_ENTITY_CACHE = records
    return records


def _symbol_route_key(symbol: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", symbol.upper()).strip("_")


def _load_news_ticker_profiles() -> dict[str, dict[str, str]]:
    profiles: dict[str, dict[str, str]] = {}
    for entity in _tracked_entity_records():
        symbol = str(entity.get("symbol") or "").upper()
        if not symbol:
            continue
        name = entity.get("name") if isinstance(entity.get("name"), dict) else {}
        display_symbol = str(entity.get("display_symbol") or symbol)
        name_en = str(name.get("en") or entity.get("legal_name") or display_symbol)
        name_ko = str(name.get("ko") or NEWS_TICKER_KO_NAMES.get(symbol, name_en))
        profiles[symbol] = {
            "entity_id": str(entity.get("entity_id") or symbol.lower()),
            "name_en": name_en,
            "name_ko": name_ko,
            "exchange": str(entity.get("exchange") or NEWS_TICKER_EXCHANGES.get(symbol, "REFERENCE")),
            "route_kind": str(entity.get("route_kind") or "ticker"),
            "route_key": str(entity.get("route_key") or _symbol_route_key(symbol)),
            "source_strength": str(entity.get("source_strength") or "registry"),
        }
    return profiles


NEWS_TICKER_PROFILES = _load_news_ticker_profiles()


def _tracked_entity_by_symbol() -> dict[str, dict[str, Any]]:
    return {str(entity.get("symbol") or "").upper(): entity for entity in _tracked_entity_records()}


def _tracked_entity_by_route_key() -> dict[str, dict[str, Any]]:
    return {str(entity.get("route_key") or _symbol_route_key(str(entity.get("symbol") or ""))).upper(): entity for entity in _tracked_entity_records()}

NEWS_REGION_KEYS = ["USA", "KOR", "JPN", "BRA", "EU", "CHN"]
NEWS_TOPIC_KEYS = ["semiconductors", "space", "quantum", "geopolitics", "public_health", "central_banks", "energy"]

NEWS_TOPIC_LABELS = {
    "semiconductors": ("Semiconductors", "반도체"),
    "geopolitics": ("Geopolitics", "지정학"),
    "public_health": ("Public health", "공중보건"),
    "central_banks": ("Central banks", "중앙은행"),
    "energy": ("Energy", "에너지"),
    "space": ("Space", "우주"),
    "quantum": ("Quantum", "양자"),
    "trade_policy": ("Trade policy", "무역 정책"),
    "supply_chain": ("Supply chain", "공급망"),
    "macro": ("Macro", "거시"),
}

NEWS_TRUST_LABELS = {
    "T0_OFFICIAL": ("Official source", "공식 출처"),
    "T1_REGULATED_FILING": ("Regulated filing", "규제 공시"),
    "T2_REPUTABLE_MEDIA": ("Reputable media", "신뢰 매체"),
    "T3_REVIEWED_PUBLIC_SOURCE": ("Reviewed public source", "검토된 공개 출처"),
    "T4_WEAK_SIGNAL": ("Weak signal", "약한 신호"),
    "T5_UNREVIEWED": ("Unreviewed", "미검토"),
    "T6_BLOCKED": ("Blocked", "차단"),
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
        news_events = _news_event_details(locale, generated_at)
        news_list_items = [_news_list_item(event) for event in news_events]
        news_list_items.sort(key=lambda event: (event["breaking_score"], event["last_seen_at"]), reverse=True)
        macro_tiles = _preserve_previous_active_macro_tiles(locale, _macro_tiles(locale, generated_at))
        alternative_signals = _alternative_signals(locale, generated_at)
        breaking_market_map = _breaking_market_projection_from_signals(alternative_signals, generated_at=generated_at)
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
                    "breaking_market_events": breaking_market_map["events"],
                    "breaking_market_map": breaking_market_map,
                    "macro_tiles": macro_tiles,
                    "alternative_signals": alternative_signals,
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
                    "breaking_market_events": breaking_market_map["events"],
                    "breaking_market_map": breaking_market_map,
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
                    _sector_page(key, locale, events, calendar, news_list_items, generated_at),
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

        _write_news_snapshots(manifest, locale, generated_at, stale_after, hard_expires_at, news_events, news_list_items)
        _write_reference_entity_snapshots(manifest, locale, generated_at, stale_after, hard_expires_at, news_list_items)
        _write_fund_portfolio_snapshots(manifest, locale, generated_at, stale_after, hard_expires_at)

    latest = PUBLIC_ROOT / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    (latest / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


def _reset_runtime_caches() -> None:
    global _RUNTIME_ENV, _MOF_JGB_CACHE, _TREASURY_YIELD_CACHE, _LAST_FRED_REQUEST_AT, _LAST_KRX_REQUEST_AT, _LAST_FINRA_REQUEST_AT, _CUSIP_TICKER_OVERRIDES_CACHE, _GEOPOLITICAL_REGISTRY_CACHE
    _RUNTIME_ENV = None
    _FRED_CACHE.clear()
    _MOF_JGB_CACHE = None
    _KRX_ROWS_CACHE.clear()
    _KRX_ERROR_CACHE.clear()
    _FINRA_TOKEN_CACHE.clear()
    _FINRA_TOKEN_CACHE.update({"token": None, "expires_at": 0.0})
    _FINRA_ROWS_CACHE.clear()
    _SEC_SUBMISSIONS_CACHE.clear()
    _SEC_FUND_PORTFOLIO_CACHE.clear()
    _CUSIP_TICKER_OVERRIDES_CACHE = None
    _WEB_METADATA_CACHE.clear()
    _ISHARES_FUND_CACHE.clear()
    _BOJ_SERIES_CACHE.clear()
    _PENTAGON_PIZZA_CACHE.clear()
    _YAHOO_QUOTE_CACHE.clear()
    _STOOQ_QUOTE_CACHE.clear()
    _FINNHUB_QUOTE_CACHE.clear()
    _TWELVE_DATA_QUOTE_CACHE.clear()
    _TREASURY_YIELD_CACHE = None
    _GDELT_ARTICLE_CACHE.clear()
    _RSS_ARTICLE_CACHE.clear()
    _GEOPOLITICAL_REGISTRY_CACHE = None
    _SECTOR_SHORT_FACT_CACHE.clear()
    _LAST_FRED_REQUEST_AT = 0.0
    _LAST_KRX_REQUEST_AT = 0.0
    _LAST_FINRA_REQUEST_AT = 0.0
    _LAST_HTTP_PROVIDER_REQUEST_AT.clear()


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


def _boj_daily_rate_series(db: str, code: str, generated_at: datetime) -> dict[str, Any] | None:
    months = _recent_boj_months(generated_at)
    cache_key = (db, code, ",".join(months))
    if cache_key in _BOJ_SERIES_CACHE:
        return _BOJ_SERIES_CACHE[cache_key]
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    generated_day_jst = (generated_at + timedelta(hours=9)).date()
    points: list[dict[str, Any]] = []
    last_update: str | None = None

    for month in reversed(months):
        params = {
            "format": "json",
            "lang": "en",
            "db": db,
            "code": code,
            "startDate": month,
            "endDate": month,
        }
        try:
            payload = _http_json(
                f"{BOJ_TIMESERIES_API_URL}?{parse.urlencode(params)}",
                headers={"Accept": "application/json", "User-Agent": user_agent},
                timeout=20,
                throttle_key="boj_timeseries",
                max_bytes=600_000,
            )
        except Exception:
            continue
        if not isinstance(payload, dict) or payload.get("STATUS") != 200:
            continue
        for series in payload.get("RESULTSET", []):
            if not isinstance(series, dict) or series.get("SERIES_CODE") != code:
                continue
            last_update = _iso_date(str(series.get("LAST_UPDATE") or "")) or last_update
            values = series.get("VALUES") if isinstance(series.get("VALUES"), dict) else {}
            dates = values.get("SURVEY_DATES")
            observed_values = values.get("VALUES")
            if not isinstance(dates, list) or not isinstance(observed_values, list):
                continue
            for raw_date, raw_value in zip(dates, observed_values):
                date = _iso_date(str(raw_date))
                value = _numeric_value(raw_value)
                if not date or value is None:
                    continue
                try:
                    observed_day = datetime.strptime(date, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if observed_day <= generated_day_jst:
                    points.append({"date": date, "value": value})

    if not points:
        _BOJ_SERIES_CACHE[cache_key] = None
        return None
    points = sorted(points, key=lambda point: point["date"])
    deduped: dict[str, dict[str, Any]] = {str(point["date"]): point for point in points}
    points = list(deduped.values())[-8:]
    latest_point = points[-1]
    source_month = str(latest_point["date"]).replace("-", "")[:6]
    source_url = _boj_timeseries_source_url(db, code, source_month)
    result = {
        "date": latest_point["date"],
        "value": latest_point["value"],
        "points": points,
        "last_update": last_update or latest_point["date"],
        "source_url": source_url,
    }
    _BOJ_SERIES_CACHE[cache_key] = result
    return result


def _recent_boj_months(generated_at: datetime, lookback_months: int = 3) -> list[str]:
    day = (generated_at + timedelta(hours=9)).date()
    year = day.year
    month = day.month
    months = []
    for _ in range(lookback_months):
        months.append(f"{year:04d}{month:02d}")
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return months


def _boj_timeseries_source_url(db: str, code: str, month: str) -> str:
    return f"{BOJ_TIMESERIES_API_URL}?{parse.urlencode({'format': 'csv', 'lang': 'en', 'db': db, 'code': code, 'startDate': month, 'endDate': month})}"


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
                max_bytes=8_000_000,
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
            max_bytes=120_000,
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


def _cusip_ticker_overrides() -> dict[str, str]:
    global _CUSIP_TICKER_OVERRIDES_CACHE
    if _CUSIP_TICKER_OVERRIDES_CACHE is not None:
        return {
            cusip: ticker
            for cusip, ticker in _CUSIP_TICKER_OVERRIDES_CACHE.items()
            if isinstance(ticker, str) and ticker
        }
    if not CUSIP_TICKER_OVERRIDES_PATH.exists():
        _CUSIP_TICKER_OVERRIDES_CACHE = {}
        return {}
    try:
        payload = json.loads(CUSIP_TICKER_OVERRIDES_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        _CUSIP_TICKER_OVERRIDES_CACHE = {}
        return {}
    raw = payload.get("overrides") if isinstance(payload, dict) else payload
    if not isinstance(raw, dict):
        _CUSIP_TICKER_OVERRIDES_CACHE = {}
        return {}
    _CUSIP_TICKER_OVERRIDES_CACHE = {
        str(cusip).strip().upper(): str(ticker).strip().upper()
        for cusip, ticker in raw.items()
        if str(cusip).strip() and isinstance(ticker, str) and ticker.strip()
    }
    return dict(_CUSIP_TICKER_OVERRIDES_CACHE)


def _sec_archive_base_url(cik: str, accession_number: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_number.replace('-', '')}"


def _latest_sec_13f_filing(cik: str) -> dict[str, Any] | None:
    submissions = _sec_submissions(cik)
    if not submissions:
        return None
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    filing_dates = recent.get("filingDate") or []
    report_dates = recent.get("reportDate") or []
    primary_documents = recent.get("primaryDocument") or []
    for index, form_type in enumerate(forms):
        if str(form_type) not in {"13F-HR", "13F-HR/A"}:
            continue
        accession_number = str(accessions[index])
        primary_document = str(primary_documents[index] or "primary_doc.xml").split("/")[-1]
        base_url = _sec_archive_base_url(cik, accession_number)
        return {
            "form_type": str(form_type),
            "accession_number": accession_number,
            "filed_at": str(filing_dates[index]),
            "report_date": str(report_dates[index]),
            "archive_base_url": base_url,
            "primary_document_url": f"{base_url}/{primary_document}",
        }
    return None


def _sec_filing_index_items(base_url: str) -> list[dict[str, Any]]:
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    try:
        payload = _http_json(
            f"{base_url}/index.json",
            headers={"Accept": "application/json", "User-Agent": user_agent},
            timeout=20,
            throttle_key="sec_edgar",
            max_bytes=600_000,
        )
    except Exception:
        return []
    items = payload.get("directory", {}).get("item", []) if isinstance(payload, dict) else []
    return [item for item in items if isinstance(item, dict)]


def _find_13f_information_table_url(base_url: str) -> str | None:
    items = _sec_filing_index_items(base_url)
    xml_names = [
        str(item.get("name") or "")
        for item in items
        if str(item.get("name") or "").lower().endswith(".xml")
    ]
    candidates = [
        name
        for name in xml_names
        if name.lower() != "primary_doc.xml" and ("13f" in name.lower() or "infotable" in name.lower() or "xml" in name.lower())
    ]
    if not candidates:
        candidates = [name for name in xml_names if name.lower() != "primary_doc.xml"]
    if not candidates:
        return None
    return f"{base_url}/{candidates[0]}"


def _xml_child_text(element: ElementTree.Element, local_name: str) -> str:
    child = element.find(f".//{{*}}{local_name}")
    if child is None or child.text is None:
        return ""
    return unescape(child.text.strip())


def _parse_sec_number(value: str | None) -> float | None:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_sec_13f_information_table(xml_text: str, *, source_url: str) -> list[dict[str, Any]]:
    overrides = _cusip_ticker_overrides()
    root = ElementTree.fromstring(xml_text.encode())
    rows: list[dict[str, Any]] = []
    for index, table in enumerate(root.findall(".//{*}infoTable")):
        cusip = _xml_child_text(table, "cusip").upper()
        put_call_text = _xml_child_text(table, "putCall")
        put_call = put_call_text if put_call_text in {"Call", "Put"} else None
        holding_kind = str(put_call).lower() if put_call else "stock"
        value = _parse_sec_number(_xml_child_text(table, "value")) or 0.0
        shares = _parse_sec_number(_xml_child_text(table, "sshPrnamt"))
        symbol = overrides.get(cusip)
        rows.append(
            {
                "id": hashlib.sha1(f"{source_url}:{index}:{cusip}:{put_call or 'stock'}".encode()).hexdigest()[:16],
                "symbol": symbol,
                "issuer_name": _xml_child_text(table, "nameOfIssuer"),
                "title_of_class": _xml_child_text(table, "titleOfClass"),
                "cusip": cusip,
                "value_usd": round(value),
                "shares": round(shares) if shares is not None else None,
                "share_type": _xml_child_text(table, "sshPrnamtType") or None,
                "put_call": put_call,
                "holding_kind": holding_kind if holding_kind in {"stock", "call", "put"} else "other",
                "portfolio_weight": 0.0,
                "source_url": source_url,
                "source_lineage": "SEC EDGAR 13F information table XML",
            }
        )
    total_value = sum(float(row["value_usd"] or 0) for row in rows)
    if total_value > 0:
        for row in rows:
            row["portfolio_weight"] = round(float(row["value_usd"] or 0) / total_value, 6)
    return rows


def _sec_13f_portfolio(fund_key: str) -> dict[str, Any] | None:
    if fund_key in _SEC_FUND_PORTFOLIO_CACHE:
        return _SEC_FUND_PORTFOLIO_CACHE[fund_key]
    config = FUND_PORTFOLIOS.get(fund_key)
    if not config:
        _SEC_FUND_PORTFOLIO_CACHE[fund_key] = None
        return None
    cik = str(config["cik"])
    filing = _latest_sec_13f_filing(cik)
    if not filing:
        _SEC_FUND_PORTFOLIO_CACHE[fund_key] = None
        return None
    information_table_url = _find_13f_information_table_url(str(filing["archive_base_url"]))
    if not information_table_url:
        _SEC_FUND_PORTFOLIO_CACHE[fund_key] = None
        return None
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    xml_text = _http_text(
        information_table_url,
        headers={"Accept": "application/xml,text/xml", "User-Agent": user_agent},
        timeout=20,
        max_bytes=3_000_000,
        throttle_key="sec_edgar",
    )
    if not xml_text:
        _SEC_FUND_PORTFOLIO_CACHE[fund_key] = None
        return None
    holdings = _parse_sec_13f_information_table(xml_text, source_url=information_table_url)
    holdings.sort(key=lambda row: float(row.get("value_usd") or 0), reverse=True)
    stock_holdings = [holding for holding in holdings if holding["holding_kind"] == "stock"]
    option_holdings = [holding for holding in holdings if holding["holding_kind"] in {"call", "put"}]
    payload = {
        "filing": {
            "source": "SEC_EDGAR_13F",
            "form_type": filing["form_type"],
            "accession_number": filing["accession_number"],
            "report_date": filing["report_date"],
            "filed_at": filing["filed_at"],
            "primary_document_url": filing["primary_document_url"],
            "information_table_url": information_table_url,
        },
        "holdings": holdings,
        "top_equity_holdings": sorted(stock_holdings, key=lambda row: float(row.get("value_usd") or 0), reverse=True)[:25],
        "option_holdings": sorted(option_holdings, key=lambda row: float(row.get("value_usd") or 0), reverse=True),
    }
    _SEC_FUND_PORTFOLIO_CACHE[fund_key] = payload
    return payload


def _web_metadata(url: str) -> dict[str, str] | None:
    if url in _WEB_METADATA_CACHE:
        return _WEB_METADATA_CACHE[url]
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    try:
        html = _http_text(
            url,
            headers={"User-Agent": user_agent, "Accept": "text/html"},
            timeout=8,
            max_bytes=300_000,
            max_attempts=1,
        )
    except Exception:
        _WEB_METADATA_CACHE[url] = None
        return None
    if not html:
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


def _http_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
    max_bytes: int = 600_000,
    throttle_key: str | None = None,
    max_attempts: int = HTTP_DEFAULT_MAX_ATTEMPTS,
) -> str | None:
    try:
        return _http_bytes(
            url,
            headers=headers,
            timeout=timeout,
            max_bytes=max_bytes,
            throttle_key=throttle_key,
            max_attempts=max_attempts,
        ).decode("utf-8", errors="ignore")
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
        throttle_key="ishares_ewy",
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


def _yahoo_chart_series(symbol: str) -> dict[str, Any] | None:
    cache_key = symbol.upper()
    if cache_key in _YAHOO_QUOTE_CACHE:
        return _YAHOO_QUOTE_CACHE[cache_key]
    encoded_symbol = parse.quote(symbol, safe="")
    params = parse.urlencode({"interval": "1m", "range": "1d"})
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    try:
        payload = _http_json(
            f"{YAHOO_FINANCE_CHART_URL}/{encoded_symbol}?{params}",
            headers={"Accept": "application/json", "User-Agent": user_agent},
            timeout=12,
            throttle_key="yahoo_finance_delayed_quote",
            max_bytes=1_000_000,
        )
    except Exception:
        _YAHOO_QUOTE_CACHE[cache_key] = None
        return None
    result = _list_item(payload.get("chart", {}).get("result"), 0) if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        _YAHOO_QUOTE_CACHE[cache_key] = None
        return None
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    price = _numeric_value(meta.get("regularMarketPrice"))
    timestamp = _numeric_value(meta.get("regularMarketTime"))
    if price is None or timestamp is None:
        _YAHOO_QUOTE_CACHE[cache_key] = None
        return None
    previous = _numeric_value(meta.get("previousClose"))
    points = _yahoo_chart_points(result)
    updated_at = datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    date = updated_at[:10]
    result_payload: dict[str, Any] = {
        "date": date,
        "value": price,
        "updated_at": updated_at,
        "points": points or [{"date": updated_at, "value": price}],
        "source_url": _yahoo_chart_source_url(symbol),
    }
    if previous is not None:
        result_payload["change"] = price - previous
        if previous:
            result_payload["percent_change"] = ((price - previous) / previous) * 100
    _YAHOO_QUOTE_CACHE[cache_key] = result_payload
    return result_payload


def _yahoo_chart_source_url(symbol: str) -> str:
    params = parse.urlencode({"range": "1d", "interval": "1m"})
    return f"{YAHOO_FINANCE_CHART_URL}/{parse.quote(symbol, safe='')}?{params}"


def _yahoo_chart_points(result: dict[str, Any]) -> list[dict[str, Any]]:
    timestamps = result.get("timestamp")
    indicators = result.get("indicators") if isinstance(result.get("indicators"), dict) else {}
    quote = _list_item(indicators.get("quote"), 0)
    closes = quote.get("close") if isinstance(quote, dict) else None
    if not isinstance(timestamps, list) or not isinstance(closes, list):
        return []
    points: list[dict[str, Any]] = []
    for timestamp, close in zip(timestamps, closes):
        value = _numeric_value(close)
        if value is None:
            continue
        try:
            date = datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except (OSError, ValueError, TypeError):
            continue
        points.append({"date": date, "value": value})
    if len(points) <= 8:
        return points
    step = max(1, len(points) // 8)
    sampled = points[::step]
    if sampled[-1] != points[-1]:
        sampled.append(points[-1])
    return sampled[-8:]


def _stooq_quote_series(symbol: str) -> dict[str, Any] | None:
    cache_key = symbol.upper()
    if cache_key in _STOOQ_QUOTE_CACHE:
        return _STOOQ_QUOTE_CACHE[cache_key]
    params = parse.urlencode({"s": symbol, "f": "sd2t2ohlcv", "h": "", "e": "csv"})
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    text = _http_text(
        f"{STOOQ_QUOTE_URL}?{params}",
        headers={"Accept": "text/csv,*/*", "User-Agent": user_agent},
        timeout=12,
        max_bytes=80_000,
        throttle_key="stooq_delayed_quote",
    )
    if not text:
        _STOOQ_QUOTE_CACHE[cache_key] = None
        return None
    rows = list(csv.DictReader(io.StringIO(text)))
    row = rows[0] if rows else {}
    close = _numeric_value(row.get("Close"))
    date = _iso_date(str(row.get("Date") or ""))
    time_value = str(row.get("Time") or "").strip()
    if close is None or not date or date == "N/D":
        _STOOQ_QUOTE_CACHE[cache_key] = None
        return None
    updated_at = _quote_timestamp(date, time_value)
    previous = _numeric_value(row.get("Open"))
    result_payload: dict[str, Any] = {
        "date": date,
        "value": close,
        "updated_at": updated_at,
        "points": _ohlc_points(date, row),
        "source_url": f"https://stooq.com/q/?s={parse.quote(symbol)}",
    }
    if previous is not None:
        result_payload["change"] = close - previous
        if previous:
            result_payload["percent_change"] = ((close - previous) / previous) * 100
    _STOOQ_QUOTE_CACHE[cache_key] = result_payload
    return result_payload


def _finnhub_quote_series(symbol: str) -> dict[str, Any] | None:
    cache_key = symbol.upper()
    if cache_key in _FINNHUB_QUOTE_CACHE:
        return _FINNHUB_QUOTE_CACHE[cache_key]
    token = str(_runtime_env().get("FINNHUB_API_KEY") or "").strip()
    if not token:
        _FINNHUB_QUOTE_CACHE[cache_key] = None
        return None
    params = parse.urlencode({"symbol": symbol, "token": token})
    try:
        payload = _http_json(
            f"{FINNHUB_QUOTE_URL}?{params}",
            headers={"Accept": "application/json"},
            timeout=12,
            throttle_key="finnhub_quote",
            max_bytes=80_000,
        )
    except Exception:
        _FINNHUB_QUOTE_CACHE[cache_key] = None
        return None
    price = _numeric_value(payload.get("c")) if isinstance(payload, dict) else None
    timestamp = _numeric_value(payload.get("t")) if isinstance(payload, dict) else None
    previous = _numeric_value(payload.get("pc")) if isinstance(payload, dict) else None
    if price is None or price <= 0 or timestamp is None or timestamp <= 0:
        _FINNHUB_QUOTE_CACHE[cache_key] = None
        return None
    updated_at = datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    points = [{"date": updated_at, "value": price}]
    if previous is not None and previous > 0:
        prior_date = (datetime.fromtimestamp(float(timestamp), tz=timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        points.insert(0, {"date": prior_date, "value": previous})
    result_payload: dict[str, Any] = {
        "date": updated_at[:10],
        "value": price,
        "updated_at": updated_at,
        "points": points,
        "source_url": f"https://finnhub.io/api/v1/quote?symbol={parse.quote(symbol)}",
    }
    if previous is not None:
        result_payload["change"] = price - previous
        if previous:
            result_payload["percent_change"] = ((price - previous) / previous) * 100
    _FINNHUB_QUOTE_CACHE[cache_key] = result_payload
    return result_payload


def _twelve_data_quote_series(symbol: str) -> dict[str, Any] | None:
    cache_key = symbol.upper()
    if cache_key in _TWELVE_DATA_QUOTE_CACHE:
        return _TWELVE_DATA_QUOTE_CACHE[cache_key]
    api_key = str(_runtime_env().get("TWELVE_DATA_API_KEY") or "").strip()
    if not api_key:
        _TWELVE_DATA_QUOTE_CACHE[cache_key] = None
        return None
    params = parse.urlencode({"symbol": symbol, "apikey": api_key})
    try:
        payload = _http_json(
            f"{TWELVE_DATA_QUOTE_URL}?{params}",
            headers={"Accept": "application/json"},
            timeout=12,
            throttle_key="twelve_data_quote",
            max_bytes=120_000,
        )
    except Exception:
        _TWELVE_DATA_QUOTE_CACHE[cache_key] = None
        return None
    if not isinstance(payload, dict) or str(payload.get("status") or "").lower() == "error":
        _TWELVE_DATA_QUOTE_CACHE[cache_key] = None
        return None
    price = _numeric_value(payload.get("close"))
    previous = _numeric_value(payload.get("previous_close"))
    date_text = _iso_date(str(payload.get("datetime") or ""))
    if price is None or price <= 0 or not date_text:
        _TWELVE_DATA_QUOTE_CACHE[cache_key] = None
        return None
    updated_at = f"{date_text}T00:00:00Z"
    points = [{"date": updated_at, "value": price}]
    if previous is not None and previous > 0:
        prior_date = (datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc) - timedelta(days=1)).date().isoformat()
        points.insert(0, {"date": f"{prior_date}T00:00:00Z", "value": previous})
    result_payload: dict[str, Any] = {
        "date": date_text,
        "value": price,
        "updated_at": updated_at,
        "points": points,
        "source_url": "https://twelvedata.com/",
    }
    if previous is not None:
        result_payload["change"] = price - previous
        if previous:
            result_payload["percent_change"] = ((price - previous) / previous) * 100
    _TWELVE_DATA_QUOTE_CACHE[cache_key] = result_payload
    return result_payload


def _freshest_quote_candidate(candidates: list[tuple[str, dict[str, Any] | None]]) -> tuple[str, dict[str, Any]] | None:
    valid: list[tuple[datetime, str, dict[str, Any]]] = []
    for source_name, series in candidates:
        if not series:
            continue
        timestamp = _parse_snapshot_datetime(str(series.get("updated_at") or ""))
        if timestamp is None:
            continue
        valid.append((timestamp, source_name, series))
    if not valid:
        return None
    _timestamp, source_name, series = max(valid, key=lambda item: item[0])
    return source_name, series


def _parse_snapshot_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _market_pulse_public_provider_allowed(provider_key: str) -> bool:
    allowlist = str(_runtime_env().get("MARKET_PULSE_PUBLIC_PROVIDER_ALLOWLIST") or "").strip().lower()
    if not allowlist:
        return False
    values = {item.strip() for item in allowlist.split(",") if item.strip()}
    return "all" in values or provider_key.lower() in values


def _treasury_yield_curve_series(term_key: str, generated_at: datetime) -> dict[str, Any] | None:
    rows = _treasury_yield_curve_rows(generated_at)
    points: list[dict[str, Any]] = []
    for row in rows:
        value = _numeric_value(row.get(term_key))
        date = _iso_date(str(row.get("NEW_DATE") or "").split("T", 1)[0])
        if value is None or not date:
            continue
        points.append({"date": date, "value": value})
    if not points:
        return None
    points = sorted(points, key=lambda point: point["date"])[-8:]
    latest_point = points[-1]
    return {"date": latest_point["date"], "value": latest_point["value"], "points": points}


def _treasury_yield_curve_rows(generated_at: datetime) -> list[dict[str, str]]:
    global _TREASURY_YIELD_CACHE
    if _TREASURY_YIELD_CACHE is not None:
        return _TREASURY_YIELD_CACHE
    params = parse.urlencode({"data": "daily_treasury_yield_curve", "field_tdr_date_value": str(generated_at.year)})
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    text = _http_text(
        f"{TREASURY_YIELD_XML_URL}?{params}",
        headers={"Accept": "application/xml,text/xml,*/*", "User-Agent": user_agent},
        timeout=20,
        max_bytes=2_500_000,
    )
    if not text:
        _TREASURY_YIELD_CACHE = []
        return _TREASURY_YIELD_CACHE
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        _TREASURY_YIELD_CACHE = []
        return _TREASURY_YIELD_CACHE
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    }
    rows: list[dict[str, str]] = []
    for entry in root.findall("atom:entry", ns):
        props = entry.find("atom:content/m:properties", ns)
        if props is None:
            continue
        row: dict[str, str] = {}
        for child in list(props):
            tag = child.tag.rsplit("}", 1)[-1]
            row[tag] = (child.text or "").strip()
        if row.get("NEW_DATE"):
            rows.append(row)
    _TREASURY_YIELD_CACHE = rows
    return _TREASURY_YIELD_CACHE


def _quote_timestamp(date: str, time_value: str) -> str:
    if time_value and time_value != "N/D":
        try:
            local_time = datetime.strptime(f"{date} {time_value}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=STOOQ_QUOTE_TIMEZONE)
            return local_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    return f"{date}T21:00:00Z"


def _ohlc_points(date: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    points = []
    for offset, key in enumerate(("Open", "Low", "High", "Close")):
        value = _numeric_value(row.get(key))
        if value is not None:
            points.append({"date": f"{date}T{12 + offset:02d}:00:00Z", "value": value})
    return points


def _observation_updated_at(date: str) -> str:
    iso_date = _iso_date(date) or date[:10]
    return f"{iso_date}T21:00:00Z"


def _observation_freshness(date: str, generated_at: datetime, *, max_age_days: int = 3) -> str:
    iso_date = _iso_date(date)
    if not iso_date:
        return "watch"
    try:
        observed = datetime.strptime(iso_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return "watch"
    return "fresh" if generated_at - observed <= timedelta(days=max_age_days) else "watch"


def _timestamp_freshness(
    updated_at: str,
    generated_at: datetime,
    *,
    fresh_after_minutes: int,
    stale_after_hours: int,
) -> str:
    try:
        observed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return "watch"
    age = generated_at - observed.astimezone(timezone.utc)
    if age < timedelta(minutes=-5):
        return "watch"
    if age <= timedelta(minutes=fresh_after_minutes):
        return "fresh"
    if age <= timedelta(hours=stale_after_hours):
        return "watch"
    return "stale"


def _pentagon_pizza_payload(base_url: str) -> dict[str, Any] | None:
    if base_url in _PENTAGON_PIZZA_CACHE:
        return _PENTAGON_PIZZA_CACHE[base_url]
    env = _runtime_env()
    user_agent = env.get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    function_url = str(env.get("PENTAGON_PIZZA_FUNCTION_URL") or "").strip()
    anon_key = str(env.get("PENTAGON_PIZZA_SUPABASE_ANON_KEY") or "").strip()
    html = _http_text(
        base_url,
        headers={"User-Agent": user_agent, "Accept": "text/html"},
        timeout=8,
        max_bytes=500_000,
        max_attempts=1,
    )
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


def _gdelt_articles(
    query: str,
    *,
    maxrecords: int = 5,
    generated_at: datetime | None = None,
    max_age_hours: int = 24,
) -> list[dict[str, str]]:
    cache_key = f"{query}:{maxrecords}:{generated_at.isoformat() if generated_at else 'now'}:{max_age_hours}"
    if cache_key in _GDELT_ARTICLE_CACHE:
        return _GDELT_ARTICLE_CACHE[cache_key]
    params = parse.urlencode(
        {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "sort": "datedesc",
            "timespan": f"{max_age_hours}h",
            "maxrecords": str(maxrecords),
        }
    )
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    try:
        payload = _http_json(
            f"{GDELT_DOC_API_URL}?{params}",
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=5,
            throttle_key="gdelt_doc",
            max_bytes=1_000_000,
            max_attempts=1,
        )
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
        seen_at = _parse_gdelt_seen_datetime(str(article.get("seendate") or ""))
        if generated_at and not _is_recent_timestamp(seen_at, generated_at, max_age_hours=max_age_hours):
            continue
        rows.append(
            {
                "key": hashlib.sha1(f"{query}:{index}:{url}".encode()).hexdigest()[:12],
                "title": title[:140],
                "url": url,
                "domain": str(article.get("domain") or parse.urlparse(url).netloc or "news").strip()[:80],
                "seen_date": str(article.get("seendate") or "")[:14],
                "seen_at": seen_at or "",
                "language": str(article.get("language") or "").strip()[:24],
            }
        )
    _GDELT_ARTICLE_CACHE[cache_key] = rows
    return rows


def _rss_articles(
    url: str,
    *,
    cache_key: str,
    maxrecords: int = 5,
    generated_at: datetime | None = None,
    max_age_hours: int = 24,
) -> list[dict[str, str]]:
    cache_id = f"{cache_key}:{generated_at.isoformat() if generated_at else 'now'}:{max_age_hours}"
    if cache_id in _RSS_ARTICLE_CACHE:
        return _RSS_ARTICLE_CACHE[cache_id]
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    try:
        xml_text = _http_text(
            url,
            headers={"User-Agent": user_agent, "Accept": "application/rss+xml, application/xml"},
            timeout=5,
            max_bytes=800_000,
            max_attempts=1,
        )
    except Exception:
        _RSS_ARTICLE_CACHE[cache_id] = []
        return []
    if not xml_text:
        _RSS_ARTICLE_CACHE[cache_id] = []
        return []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        _RSS_ARTICLE_CACHE[cache_id] = []
        return []
    rows: list[dict[str, str]] = []
    for index, item in enumerate(root.findall(".//item")):
        title = _xml_text(item, "title")
        link = _xml_text(item, "link")
        if not title or not link:
            continue
        seen_at = _parse_rss_datetime(_xml_text(item, "pubDate"))
        if generated_at and not _is_recent_timestamp(seen_at, generated_at, max_age_hours=max_age_hours):
            continue
        domain = parse.urlparse(link).netloc or _xml_text(item, "source") or "rss"
        rows.append(
            {
                "key": hashlib.sha1(f"{cache_key}:{index}:{link}".encode()).hexdigest()[:12],
                "title": title[:140],
                "url": link,
                "domain": domain[:80],
                "seen_date": _xml_text(item, "pubDate")[:32],
                "seen_at": seen_at or "",
            }
        )
        if len(rows) >= maxrecords:
            break
    _RSS_ARTICLE_CACHE[cache_id] = rows
    return rows


def _gdelt_bulk_articles(
    *,
    generated_at: datetime,
    maxrecords: int = 8,
    max_age_hours: int = 24,
) -> list[dict[str, str]]:
    cache_key = f"bulk:{generated_at.isoformat()}:{maxrecords}:{max_age_hours}"
    if cache_key in _GDELT_ARTICLE_CACHE:
        return _GDELT_ARTICLE_CACHE[cache_key]
    user_agent = _runtime_env().get("SEC_USER_AGENT") or "StonksRadar contact@example.com"
    lastupdate = _http_text(
        GDELT_LASTUPDATE_URL,
        headers={"User-Agent": user_agent},
        timeout=8,
        max_bytes=20_000,
        throttle_key="gdelt_doc",
        max_attempts=1,
    )
    selected = _select_gdelt_bulk_file(lastupdate or "", suffix=GDELT_EXPORT_SUFFIX)
    if selected is None:
        _GDELT_ARTICLE_CACHE[cache_key] = []
        return []
    try:
        payload = _http_bytes(
            selected["url"],
            headers={"User-Agent": user_agent},
            timeout=12,
            max_bytes=750_000,
            throttle_key="gdelt_doc",
            max_attempts=1,
        )
    except Exception:
        _GDELT_ARTICLE_CACHE[cache_key] = []
        return []
    rows = _parse_gdelt_bulk_export(
        payload,
        selected=selected,
        generated_at=generated_at,
        maxrecords=maxrecords,
        max_age_hours=max_age_hours,
    )
    _GDELT_ARTICLE_CACHE[cache_key] = rows
    return rows


def _select_gdelt_bulk_file(text: str, *, suffix: str) -> dict[str, str] | None:
    for raw_line in text.splitlines():
        parts = raw_line.split()
        if len(parts) < 3:
            continue
        url = parts[2].strip()
        if not url.endswith(suffix):
            continue
        match = re.search(r"/(\d{14})\.", url)
        return {"url": url, "timestamp": match.group(1) if match else ""}
    return None


def _parse_gdelt_bulk_export(
    payload: bytes,
    *,
    selected: dict[str, str],
    generated_at: datetime,
    maxrecords: int,
    max_age_hours: int,
) -> list[dict[str, str]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile:
        return []
    names = archive.namelist()
    if len(names) != 1:
        return []
    rows: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    with archive.open(names[0]) as raw_file:
        text_file = io.TextIOWrapper(raw_file, encoding="utf-8", errors="ignore", newline="")
        for index, row in enumerate(csv.reader(text_file, delimiter="\t")):
            if index >= 6000 or len(rows) >= maxrecords:
                break
            parsed = _gdelt_export_row(
                row,
                selected=selected,
                generated_at=generated_at,
                max_age_hours=max_age_hours,
            )
            if parsed is None or parsed["url"] in seen_urls:
                continue
            seen_urls.add(parsed["url"])
            rows.append(parsed)
    return rows


def _gdelt_export_row(
    row: list[str],
    *,
    selected: dict[str, str],
    generated_at: datetime,
    max_age_hours: int,
) -> dict[str, str] | None:
    if len(row) < 61:
        return None
    actor1 = row[6].strip()
    actor2 = row[16].strip()
    event_code = row[26].strip()
    quad_class = row[29].strip()
    place = row[53].strip()
    source_url = row[60].strip()
    if not source_url.startswith(("http://", "https://")):
        source_url = selected["url"]
    seen_at = _parse_gdelt_bulk_datetime(row[59].strip() or selected.get("timestamp", ""))
    if not _is_recent_timestamp(seen_at, generated_at, max_age_hours=max_age_hours):
        return None
    text_blob = " ".join([actor1, actor2, place, source_url, event_code, quad_class])
    if not _gdelt_bulk_row_relevant(text_blob, event_code=event_code, quad_class=quad_class):
        return None
    if not match_geo_points(texts=[text_blob], max_points=1):
        return None
    actors = " / ".join(value for value in (actor1, actor2) if value) or "reported actors"
    title = f"GDELT event {event_code or 'update'}: {actors}"
    if place:
        title = f"{title} near {place}"
    return {
        "key": hashlib.sha1(f"{row[0]}:{source_url}:{seen_at}".encode()).hexdigest()[:12],
        "title": _safe_display_text(title, 140),
        "url": source_url,
        "domain": parse.urlparse(source_url).netloc or "data.gdeltproject.org",
        "seen_date": seen_at or selected.get("timestamp", ""),
        "seen_at": seen_at or "",
        "severity": "critical" if quad_class == "4" else "high" if quad_class == "3" else "medium",
    }


def _parse_gdelt_bulk_datetime(value: str) -> str | None:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) < 14:
        return None
    try:
        parsed = datetime.strptime(digits[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return parsed.isoformat().replace("+00:00", "Z")


def _gdelt_bulk_row_relevant(text: str, *, event_code: str, quad_class: str) -> bool:
    lower = text.lower()
    return any(_gdelt_bulk_relevance_term_matches(lower, term) for term in _GDELT_BULK_RELEVANCE_TERMS)


def _gdelt_bulk_relevance_term_matches(text: str, term: str) -> bool:
    if re.search(r"[^a-z0-9]", term):
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


_GDELT_BULK_RELEVANCE_TERMS = (
    "hormuz",
    "red sea",
    "taiwan",
    "iran",
    "israel",
    "ukraine",
    "russia",
    "sanction",
    "export-control",
    "export control",
    "chip",
    "semiconductor",
    "oil",
    "lng",
    "shipping",
    "missile",
    "strike",
    "war",
    "conflict",
    "tariff",
    "supply chain",
)


def _parse_gdelt_seen_datetime(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    for fmt, length in (("%Y%m%d%H%M%S", 14), ("%Y%m%d%H%M", 12)):
        try:
            return datetime.strptime(text[:length], fmt).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            continue
    return None


def _parse_rss_datetime(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_recent_timestamp(value: str | None, generated_at: datetime, *, max_age_hours: int) -> bool:
    if not value:
        return False
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return timedelta(0) <= generated_at - observed <= timedelta(hours=max_age_hours)


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
    max_bytes: int = 2_000_000,
    max_attempts: int = HTTP_DEFAULT_MAX_ATTEMPTS,
) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    body = _http_bytes(
        url,
        method=method,
        headers=headers,
        data=data,
        timeout=timeout,
        throttle_key=throttle_key,
        max_bytes=max_bytes,
        max_attempts=max_attempts,
    )
    return json.loads(body.decode())


def _http_bytes(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    timeout: int = 20,
    throttle_key: str | None = None,
    max_bytes: int = 2_000_000,
    max_attempts: int = HTTP_DEFAULT_MAX_ATTEMPTS,
) -> bytes:
    attempts = max(1, max_attempts)
    last_error: Exception | None = None
    for attempt in range(attempts):
        _throttle_http_provider(throttle_key)
        req = request.Request(url, data=data, headers=headers or {}, method=method)
        try:
            with request.urlopen(req, timeout=timeout) as response:
                body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError(f"response exceeded {max_bytes} bytes")
            _mark_http_provider(throttle_key)
            return body
        except error.HTTPError as exc:
            _mark_http_provider(throttle_key)
            last_error = exc
            delay = _http_retry_delay(exc, attempt)
            if exc.code in HTTP_RETRY_STATUS_CODES and delay is not None and attempt + 1 < attempts:
                time.sleep(delay)
                continue
            raise
        except (TimeoutError, error.URLError) as exc:
            _mark_http_provider(throttle_key)
            last_error = exc
            delay = _http_retry_delay(exc, attempt)
            if delay is not None and attempt + 1 < attempts:
                time.sleep(delay)
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("HTTP request failed before an attempt was made")


def _throttle_http_provider(throttle_key: str | None) -> None:
    if not throttle_key:
        return
    min_interval = HTTP_PROVIDER_MIN_INTERVAL_SECONDS.get(throttle_key)
    if min_interval is None:
        return
    elapsed = time.monotonic() - _LAST_HTTP_PROVIDER_REQUEST_AT.get(throttle_key, 0.0)
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)


def _mark_http_provider(throttle_key: str | None) -> None:
    if throttle_key:
        _LAST_HTTP_PROVIDER_REQUEST_AT[throttle_key] = time.monotonic()


def _http_retry_delay(exc: Exception, attempt: int) -> float | None:
    retry_after = _http_retry_after_seconds(exc)
    if retry_after is not None:
        if retry_after > HTTP_DEFAULT_MAX_RETRY_DELAY_SECONDS:
            return None
        return max(0.0, retry_after)
    return min(HTTP_DEFAULT_MAX_RETRY_DELAY_SECONDS, 0.5 * (2**attempt))


def _http_retry_after_seconds(exc: Exception) -> float | None:
    headers = getattr(exc, "headers", None)
    if not headers:
        return None
    raw_value = headers.get("Retry-After") if hasattr(headers, "get") else None
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds())


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
            {"source_key": "yahoo_finance_delayed_quote", "policy_version": 1},
            {"source_key": "stooq_delayed_quote", "policy_version": 1},
            {"source_key": "treasury_xml_feed", "policy_version": 1},
            {"source_key": "krx_open_api", "policy_version": 1},
            {"source_key": "data_go_kr", "policy_version": 1},
            {"source_key": "japan_mof_jgb_csv", "policy_version": 1},
            {"source_key": "bis", "policy_version": 1},
            {"source_key": "who", "policy_version": 1},
            {"source_key": "cdc", "policy_version": 1},
            {"source_key": "company_ir", "policy_version": 1},
            {"source_key": "ecb", "policy_version": 1},
            {"source_key": "bank_of_korea", "policy_version": 1},
            {"source_key": "bank_of_japan", "policy_version": 1},
            {"source_key": "bcb", "policy_version": 1},
            {"source_key": "rocket_lab_ir", "policy_version": 1},
            {"source_key": "ionq_ir", "policy_version": 1},
            {"source_key": "iea", "policy_version": 1},
            {"source_key": "source_policy", "policy_version": 1},
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
    ts = _seed_reference_event_timestamp()
    freshness = _seed_reference_freshness(generated_at)
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
            "freshness": freshness,
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
            "freshness": freshness,
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
            "freshness": freshness,
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


def _seed_reference_event_timestamp() -> str:
    return "2026-05-25T00:00:00Z"


def _seed_reference_freshness(generated_at: datetime) -> str:
    reference = datetime(2026, 5, 25, tzinfo=timezone.utc)
    age = generated_at - reference
    if age < timedelta(0):
        return "watch"
    if age <= timedelta(hours=24):
        return "fresh"
    if age <= timedelta(days=7):
        return "watch"
    return "stale"


def _write_news_snapshots(
    manifest: dict[str, Any],
    locale: str,
    generated_at: datetime,
    stale_after: datetime,
    hard_expires_at: datetime,
    events: list[dict[str, Any]] | None = None,
    list_items: list[dict[str, Any]] | None = None,
) -> None:
    events = events or _news_event_details(locale, generated_at)
    if list_items is None:
        list_items = [_news_list_item(event) for event in events]
        list_items.sort(key=lambda event: (event["breaking_score"], event["last_seen_at"]), reverse=True)

    _write(
        manifest,
        "news_index",
        locale,
        ["news", "index.json"],
        _envelope(
            locale,
            generated_at,
            stale_after,
            hard_expires_at,
            "news_index",
            "news_index",
            {
                "generated_label": generated_at.isoformat().replace("+00:00", "Z"),
                "filters": _news_filters(list_items, locale),
                "events": list_items,
            },
        ),
    )

    for event in events:
        _write(
            manifest,
            f"news_event_{event['id']}",
            locale,
            ["news", "events", f"{event['id']}.json"],
            _envelope(
                locale,
                generated_at,
                stale_after,
                hard_expires_at,
                "news_event",
                f"news_event_{event['id']}",
                event,
            ),
        )

    for symbol, profile in NEWS_TICKER_PROFILES.items():
        symbol_events = [
            item
            for item in list_items
            if any(ticker["symbol"].upper() == symbol.upper() for ticker in item["tickers"])
        ]
        symbol_key = _news_symbol_key(symbol)
        _write(
            manifest,
            f"news_ticker_{symbol_key}",
            locale,
            ["news", "tickers", f"{symbol_key}.json"],
            _envelope(
                locale,
                generated_at,
                stale_after,
                hard_expires_at,
                "news_ticker",
                f"news_ticker_{symbol_key}",
                {
                    "symbol": symbol,
                    "name": _t(locale, profile["name_en"], profile["name_ko"]),
                    "generated_label": generated_at.isoformat().replace("+00:00", "Z"),
                    "summary": _news_ticker_summary(symbol, profile, symbol_events, locale),
                    "events": symbol_events,
                },
            ),
        )

    for region_key in NEWS_REGION_KEYS:
        region_events = [
            item
            for item in list_items
            if any(region["key"] == region_key for region in item["regions"])
        ]
        _write(
            manifest,
            f"news_region_{region_key}",
            locale,
            ["news", "regions", f"{region_key}.json"],
            _envelope(
                locale,
                generated_at,
                stale_after,
                hard_expires_at,
                "news_region",
                f"news_region_{region_key}",
                {
                    "key": region_key,
                    "name": _news_region_name(region_key, locale),
                    "generated_label": generated_at.isoformat().replace("+00:00", "Z"),
                    "regional_brief": _news_region_brief(region_key, region_events, locale),
                    "events": region_events,
                },
            ),
        )

    for topic_key in NEWS_TOPIC_KEYS:
        topic_events = [
            item
            for item in list_items
            if any(topic["key"] == topic_key for topic in item["topics"])
        ]
        label_en, label_ko = NEWS_TOPIC_LABELS[topic_key]
        _write(
            manifest,
            f"news_topic_{topic_key}",
            locale,
            ["news", "topics", f"{topic_key}.json"],
            _envelope(
                locale,
                generated_at,
                stale_after,
                hard_expires_at,
                "news_topic",
                f"news_topic_{topic_key}",
                {
                    "key": topic_key,
                    "label": _t(locale, label_en, label_ko),
                    "generated_label": generated_at.isoformat().replace("+00:00", "Z"),
                    "topic_brief": _news_topic_brief(topic_key, topic_events, locale),
                    "events": topic_events,
                },
            ),
        )


def _news_event_details(locale: str, generated_at: datetime) -> list[dict[str, Any]]:
    ts = generated_at.isoformat().replace("+00:00", "Z")
    early = (generated_at - timedelta(hours=4)).isoformat().replace("+00:00", "Z")
    prior = (generated_at - timedelta(hours=18)).isoformat().replace("+00:00", "Z")
    old = (generated_at - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    events = [
        {
            "id": "semiconductor_export_controls_seed",
            "title": _t(locale, "China-origin export-control risk remains elevated for AI-chip supply chains", "중국발 수출통제 리스크가 AI 반도체 공급망에 높은 상태로 유지"),
            "summary": _t(locale, "Official-policy monitoring links export controls to NVIDIA, Samsung Electronics, Japan equipment suppliers, and EU tooling exposure.", "공식 정책 모니터링은 수출통제를 엔비디아, 삼성전자, 일본 장비 업체, 유럽 장비 노출과 연결합니다."),
            "event_type": "trade_policy",
            "first_seen_at": old,
            "last_seen_at": ts,
            "published_at": ts,
            "freshness": "fresh",
            "severity": "high",
            "confidence": 0.78,
            "breaking_score": 76,
            "trust_score": 88,
            "source_count": 3,
            "tickers": [
                _news_ticker_ref("NVDA", "affected_company", 0.88, locale),
                _news_ticker_ref("005930.KS", "affected_company", 0.84, locale),
            ],
            "regions": [
                _news_region_ref("CHN", "event_region", 0.92, locale),
                _news_region_ref("USA", "affected_region", 0.86, locale),
                _news_region_ref("KOR", "affected_region", 0.84, locale),
                _news_region_ref("JPN", "affected_region", 0.78, locale),
                _news_region_ref("EU", "affected_region", 0.72, locale),
                _news_region_ref("USA", "market_region", 0.76, locale),
                _news_region_ref("KOR", "market_region", 0.74, locale),
            ],
            "topics": [
                _news_topic_ref("semiconductors", 0.94, locale),
                _news_topic_ref("geopolitics", 0.79, locale),
                _news_topic_ref("trade_policy", 0.86, locale),
                _news_topic_ref("supply_chain", 0.77, locale),
            ],
            "market_direction": "mixed",
            "source_links": [
                _news_source_ref("BIS", "https://www.bis.gov/", "bis", "Bureau of Industry and Security export controls", "미 산업안보국 수출통제", "T0_OFFICIAL", prior, locale),
                _news_source_ref("SEC EDGAR", "https://www.sec.gov/edgar/search/", "sec_edgar", "Issuer filings for affected companies", "영향 기업 공시", "T1_REGULATED_FILING", prior, locale, False),
                _news_source_ref("Source policy", "https://www.bis.gov/regulations/ear/table-of-contents", "source_policy", "Export Administration Regulations reference", "수출관리규정 참고", "T3_REVIEWED_PUBLIC_SOURCE", prior, locale, False),
            ],
            "one_sentence_summary": _t(locale, "Export-control monitoring remains a cross-region semiconductor risk, not a trade recommendation.", "수출통제 모니터링은 매매 추천이 아니라 지역 간 반도체 리스크입니다."),
            "what_happened": [
                _t(locale, "The seed event models an official-policy event originating in China-facing export controls.", "시드 이벤트는 중국 관련 수출통제에서 발생하는 공식 정책 이벤트를 모델링합니다."),
                _t(locale, "Affected regions distinguish event location from likely market impact.", "영향 지역은 이벤트 발생지와 시장 영향 가능 지역을 구분합니다."),
            ],
            "why_it_matters": [
                _t(locale, "AI accelerator availability, memory demand, equipment channels, and capex timing can move together.", "AI 가속기 가용성, 메모리 수요, 장비 채널, 투자 시점이 함께 움직일 수 있습니다."),
                _t(locale, "Korea and Japan exposure is shown as affected-market context, not as the source of the policy.", "한국과 일본 노출은 정책 출처가 아니라 영향 시장 맥락으로 표시됩니다."),
            ],
            "known_facts": [
                _t(locale, "Only source-linked public metadata and short summaries are published.", "출처 연결 공개 메타데이터와 짧은 요약만 게시합니다."),
                _t(locale, "Ticker links require company/entity matching, not naive text search.", "티커 연결은 단순 텍스트 검색이 아닌 회사/엔티티 매칭을 요구합니다."),
            ],
            "uncertainties": [
                _t(locale, "Actual shipment, revenue, and compliance impacts require issuer-specific filings or guidance.", "실제 선적, 매출, 컴플라이언스 영향은 기업별 공시나 가이던스가 필요합니다."),
            ],
            "conflicting_reports": [],
            "market_relevance": {
                "direction": "mixed",
                "confidence": "medium",
                "reasoning": _t(locale, "Restrictions can pressure revenue channels while supporting constrained-supply pricing in parts of the chain.", "제한은 매출 채널을 압박할 수 있지만 공급 제약 구간의 가격을 지지할 수도 있습니다."),
            },
            "methodology": _news_methodology(locale),
            "disclaimer": _news_disclaimer(locale),
        },
        {
            "id": "central_bank_policy_watch_seed",
            "title": _t(locale, "Central-bank decision calendar clusters FOMC, BoJ, BoK, ECB, and Brazil COPOM risk", "FOMC, 일본은행, 한국은행, ECB, 브라질 COPOM 결정 일정 리스크"),
            "summary": _t(locale, "Official calendars are grouped into one policy-event watch so users can scan rate dates without leaving the app.", "공식 일정을 하나의 정책 이벤트 워치로 묶어 앱을 벗어나지 않고 금리 결정일을 확인할 수 있습니다."),
            "event_type": "central_bank_calendar",
            "first_seen_at": old,
            "last_seen_at": ts,
            "published_at": ts,
            "freshness": "fresh",
            "severity": "medium",
            "confidence": 0.86,
            "breaking_score": 58,
            "trust_score": 96,
            "source_count": 5,
            "tickers": [
                _news_ticker_ref("005930.KS", "affected_company", 0.58, locale),
            ],
            "regions": [
                _news_region_ref("USA", "event_region", 0.88, locale),
                _news_region_ref("JPN", "event_region", 0.88, locale),
                _news_region_ref("KOR", "event_region", 0.88, locale),
                _news_region_ref("EU", "event_region", 0.85, locale),
                _news_region_ref("BRA", "event_region", 0.84, locale),
                _news_region_ref("USA", "market_region", 0.72, locale),
                _news_region_ref("KOR", "market_region", 0.68, locale),
            ],
            "topics": [
                _news_topic_ref("central_banks", 0.96, locale),
                _news_topic_ref("macro", 0.82, locale),
            ],
            "market_direction": "unclear",
            "source_links": [
                _news_source_ref("Federal Reserve", OFFICIAL_POLICY_CALENDAR_URLS["federal_reserve"], "federal_reserve", "FOMC calendars", "FOMC 일정", "T0_OFFICIAL", prior, locale),
                _news_source_ref("Bank of Korea", OFFICIAL_POLICY_CALENDAR_URLS["bank_of_korea"], "bank_of_korea", "Monetary policy schedule", "통화정책 일정", "T0_OFFICIAL", prior, locale),
                _news_source_ref("Bank of Japan", OFFICIAL_POLICY_CALENDAR_URLS["bank_of_japan"], "bank_of_japan", "Monetary policy meetings", "통화정책회의", "T0_OFFICIAL", prior, locale),
                _news_source_ref("ECB", OFFICIAL_POLICY_CALENDAR_URLS["ecb"], "ecb", "Governing Council calendars", "ECB 정책위원회 일정", "T0_OFFICIAL", prior, locale),
                _news_source_ref("BCB", OFFICIAL_POLICY_CALENDAR_URLS["bcb"], "bcb", "COPOM calendar", "COPOM 일정", "T0_OFFICIAL", prior, locale),
            ],
            "one_sentence_summary": _t(locale, "Rate-decision dates are grouped as official calendar context, not a rate forecast.", "금리 결정일은 금리 전망이 아닌 공식 일정 맥락으로 묶입니다."),
            "what_happened": [
                _t(locale, "The event clusters official policy calendars across major monitored regions.", "이 이벤트는 주요 모니터링 지역의 공식 정책 일정을 클러스터링합니다."),
            ],
            "why_it_matters": [
                _t(locale, "Rate decisions can affect FX, discount rates, sector rotations, and liquidity-sensitive equities.", "금리 결정은 환율, 할인율, 섹터 로테이션, 유동성 민감 주식에 영향을 줄 수 있습니다."),
            ],
            "known_facts": [
                _t(locale, "Calendar sources are official central-bank or monetary-authority pages.", "일정 출처는 공식 중앙은행 또는 통화당국 페이지입니다."),
            ],
            "uncertainties": [
                _t(locale, "The snapshot does not infer the decision outcome.", "스냅샷은 결정 결과를 추론하지 않습니다."),
            ],
            "conflicting_reports": [],
            "market_relevance": {
                "direction": "unclear",
                "confidence": "medium",
                "reasoning": _t(locale, "The event is date-sensitive; direction depends on the decision and statement language.", "이 이벤트는 날짜 민감 이벤트이며 방향성은 결정과 성명 문구에 달려 있습니다."),
            },
            "methodology": _news_methodology(locale),
            "disclaimer": _news_disclaimer(locale),
        },
        {
            "id": "public_health_alert_seed",
            "title": _t(locale, "Public-health alert monitoring covers Brazil, US, Europe, and Asia travel-sensitive markets", "공중보건 경보 모니터링이 브라질, 미국, 유럽, 아시아 여행 민감 시장을 포괄"),
            "summary": _t(locale, "Official public-health feeds are classified separately from financial news and surfaced only as market-context risk.", "공식 공중보건 피드는 금융 뉴스와 별도로 분류되어 시장 맥락 리스크로만 표시됩니다."),
            "event_type": "public_health_alert",
            "first_seen_at": old,
            "last_seen_at": early,
            "published_at": early,
            "freshness": "watch",
            "severity": "medium",
            "confidence": 0.74,
            "breaking_score": 63,
            "trust_score": 92,
            "source_count": 2,
            "tickers": [],
            "regions": [
                _news_region_ref("BRA", "event_region", 0.72, locale),
                _news_region_ref("USA", "affected_region", 0.58, locale),
                _news_region_ref("EU", "affected_region", 0.56, locale),
                _news_region_ref("JPN", "affected_region", 0.54, locale),
                _news_region_ref("KOR", "affected_region", 0.54, locale),
            ],
            "topics": [
                _news_topic_ref("public_health", 0.96, locale),
                _news_topic_ref("macro", 0.52, locale),
            ],
            "market_direction": "unclear",
            "source_links": [
                _news_source_ref("WHO", "https://www.who.int/emergencies/disease-outbreak-news", "who", "Disease Outbreak News", "질병 발생 뉴스", "T0_OFFICIAL", prior, locale),
                _news_source_ref("CDC", "https://www.cdc.gov/travel/notices", "cdc", "Travel health notices", "여행 건강 고지", "T0_OFFICIAL", prior, locale, False),
            ],
            "one_sentence_summary": _t(locale, "Public-health items are risk context and are not converted into trading calls.", "공중보건 항목은 리스크 맥락이며 거래 신호로 변환하지 않습니다."),
            "what_happened": [
                _t(locale, "The seed classifier identifies official outbreak and travel-health sources.", "시드 분류기는 공식 질병 발생 및 여행 건강 출처를 식별합니다."),
            ],
            "why_it_matters": [
                _t(locale, "Large alerts can affect travel, logistics, consumer behavior, and regional risk premia.", "대형 경보는 여행, 물류, 소비 행동, 지역 리스크 프리미엄에 영향을 줄 수 있습니다."),
            ],
            "known_facts": [
                _t(locale, "Only official public-health source links are used for this seed event.", "이 시드 이벤트는 공식 공중보건 출처 링크만 사용합니다."),
            ],
            "uncertainties": [
                _t(locale, "Market effects require severity, spread, and policy-response confirmation.", "시장 영향은 심각도, 확산, 정책 대응 확인이 필요합니다."),
            ],
            "conflicting_reports": [],
            "market_relevance": {
                "direction": "unclear",
                "confidence": "low",
                "reasoning": _t(locale, "Health alerts can affect sectors unevenly and should stay separate from unsupported market claims.", "보건 경보는 섹터별 영향이 다를 수 있어 근거 없는 시장 주장과 분리해야 합니다."),
            },
            "methodology": _news_methodology(locale),
            "disclaimer": _news_disclaimer(locale),
        },
        {
            "id": "rklb_launch_window_seed",
            "title": _t(locale, "Rocket Lab launch-window monitoring is linked to source evidence for RKLB", "로켓랩 발사 일정 모니터링이 RKLB 원문 근거와 연결"),
            "summary": _t(locale, "Company and filing sources are grouped into a ticker-specific event for Rocket Lab launch-cadence monitoring.", "회사 및 공시 출처를 로켓랩 발사 빈도 모니터링을 위한 티커별 이벤트로 묶습니다."),
            "event_type": "company_update",
            "first_seen_at": prior,
            "last_seen_at": ts,
            "published_at": ts,
            "freshness": "fresh",
            "severity": "medium",
            "confidence": 0.8,
            "breaking_score": 68,
            "trust_score": 90,
            "source_count": 2,
            "tickers": [_news_ticker_ref("RKLB", "direct_subject", 0.92, locale)],
            "regions": [
                _news_region_ref("USA", "company_region", 0.84, locale),
                _news_region_ref("USA", "market_region", 0.84, locale),
                _news_region_ref("JPN", "affected_region", 0.48, locale),
            ],
            "topics": [
                _news_topic_ref("space", 0.94, locale),
                _news_topic_ref("supply_chain", 0.44, locale),
            ],
            "market_direction": "mixed",
            "source_links": [
                _news_source_ref("Rocket Lab", "https://www.rocketlabusa.com/updates/", "rocket_lab_ir", "Rocket Lab updates", "로켓랩 업데이트", "T0_OFFICIAL", prior, locale),
                _news_source_ref("SEC EDGAR", "https://www.sec.gov/edgar/browse/?CIK=1819994", "sec_edgar", "Rocket Lab SEC filings", "로켓랩 SEC 공시", "T1_REGULATED_FILING", prior, locale, False),
            ],
            "one_sentence_summary": _t(locale, "RKLB event rows link to company and filing evidence rather than unsourced social chatter.", "RKLB 이벤트 행은 출처 없는 소셜 소문이 아니라 회사 및 공시 근거에 연결됩니다."),
            "what_happened": [
                _t(locale, "The seed event demonstrates ticker-level company news grouping for a tracked space company.", "시드 이벤트는 추적 우주 기업의 티커별 회사 뉴스 그룹화를 보여줍니다."),
            ],
            "why_it_matters": [
                _t(locale, "Launch cadence, backlog execution, and mission risk are central inputs for space-sector monitoring.", "발사 빈도, 수주 실행, 미션 리스크는 우주 섹터 모니터링의 핵심 입력값입니다."),
            ],
            "known_facts": [
                _t(locale, "Source links are official company updates and regulated filings.", "출처 링크는 공식 회사 업데이트 및 규제 공시입니다."),
            ],
            "uncertainties": [
                _t(locale, "Specific launch timing can change and should be verified against the source page.", "구체적 발사 시각은 변동될 수 있으므로 원문 페이지로 확인해야 합니다."),
            ],
            "conflicting_reports": [],
            "market_relevance": {
                "direction": "mixed",
                "confidence": "medium",
                "reasoning": _t(locale, "Operational cadence can support sentiment, but execution delays can offset it.", "운영 빈도는 심리를 지지할 수 있지만 실행 지연이 이를 상쇄할 수 있습니다."),
            },
            "methodology": _news_methodology(locale),
            "disclaimer": _news_disclaimer(locale),
        },
        {
            "id": "ionq_contract_watch_seed",
            "title": _t(locale, "IonQ contract and funding news is classified as quantum-sector ticker context", "아이온큐 계약 및 자금 뉴스가 양자 섹터 티커 맥락으로 분류"),
            "summary": _t(locale, "IONQ appears in the ticker news layer only when company, filing, or sector-context evidence is present.", "IONQ는 회사, 공시, 섹터 맥락 근거가 있을 때만 티커 뉴스 레이어에 표시됩니다."),
            "event_type": "company_update",
            "first_seen_at": prior,
            "last_seen_at": early,
            "published_at": early,
            "freshness": "watch",
            "severity": "medium",
            "confidence": 0.76,
            "breaking_score": 61,
            "trust_score": 88,
            "source_count": 2,
            "tickers": [_news_ticker_ref("IONQ", "direct_subject", 0.9, locale)],
            "regions": [
                _news_region_ref("USA", "company_region", 0.88, locale),
                _news_region_ref("USA", "market_region", 0.88, locale),
                _news_region_ref("EU", "affected_region", 0.42, locale),
                _news_region_ref("KOR", "mentioned_region", 0.3, locale),
            ],
            "topics": [
                _news_topic_ref("quantum", 0.96, locale),
                _news_topic_ref("macro", 0.38, locale),
            ],
            "market_direction": "mixed",
            "source_links": [
                _news_source_ref("IonQ", "https://ionq.com/news", "ionq_ir", "IonQ news", "아이온큐 뉴스", "T0_OFFICIAL", prior, locale),
                _news_source_ref("SEC EDGAR", "https://www.sec.gov/edgar/browse/?CIK=1824920", "sec_edgar", "IonQ SEC filings", "아이온큐 SEC 공시", "T1_REGULATED_FILING", prior, locale, False),
            ],
            "one_sentence_summary": _t(locale, "IONQ coverage is source-linked ticker context, not a model-generated price call.", "IONQ 커버리지는 출처 연결 티커 맥락이며 모델 생성 가격 의견이 아닙니다."),
            "what_happened": [
                _t(locale, "The seed event demonstrates ambiguous/high-beta ticker matching with official sources.", "시드 이벤트는 공식 출처 기반의 고베타 티커 매칭을 보여줍니다."),
            ],
            "why_it_matters": [
                _t(locale, "Quantum-sector news often needs source strength and milestone validation before becoming market context.", "양자 섹터 뉴스는 시장 맥락이 되기 전에 출처 강도와 마일스톤 검증이 필요합니다."),
            ],
            "known_facts": [
                _t(locale, "The event is tied to official company and SEC source pages.", "이 이벤트는 공식 회사 및 SEC 출처 페이지에 연결됩니다."),
            ],
            "uncertainties": [
                _t(locale, "Technical milestones and commercial revenue impact need separate verification.", "기술 마일스톤과 상업 매출 영향은 별도 검증이 필요합니다."),
            ],
            "conflicting_reports": [],
            "market_relevance": {
                "direction": "mixed",
                "confidence": "medium",
                "reasoning": _t(locale, "Contract news can support narrative momentum, but milestone risk remains high.", "계약 뉴스는 내러티브 모멘텀을 지지할 수 있지만 마일스톤 리스크는 여전히 높습니다."),
            },
            "methodology": _news_methodology(locale),
            "disclaimer": _news_disclaimer(locale),
        },
        {
            "id": "energy_geopolitical_supply_risk_seed",
            "title": _t(locale, "Energy supply-risk watch links shipping chokepoints, inventories, and inflation-sensitive markets", "에너지 공급 리스크 워치가 해상 요충지, 재고, 인플레이션 민감 시장을 연결"),
            "summary": _t(locale, "Official energy data and reviewed geopolitical context are grouped as a supply-risk event affecting the US, Europe, China, Korea, Japan, and Brazil.", "공식 에너지 데이터와 검토된 지정학 맥락을 미국, 유럽, 중국, 한국, 일본, 브라질에 영향을 줄 수 있는 공급 리스크 이벤트로 묶습니다."),
            "event_type": "geopolitical_supply_risk",
            "first_seen_at": old,
            "last_seen_at": ts,
            "published_at": ts,
            "freshness": "fresh",
            "severity": "high",
            "confidence": 0.72,
            "breaking_score": 82,
            "trust_score": 84,
            "source_count": 3,
            "tickers": [],
            "regions": [
                _news_region_ref("USA", "affected_region", 0.76, locale),
                _news_region_ref("EU", "affected_region", 0.74, locale),
                _news_region_ref("CHN", "affected_region", 0.72, locale),
                _news_region_ref("KOR", "affected_region", 0.7, locale),
                _news_region_ref("JPN", "affected_region", 0.7, locale),
                _news_region_ref("BRA", "affected_region", 0.54, locale),
            ],
            "topics": [
                _news_topic_ref("energy", 0.96, locale),
                _news_topic_ref("geopolitics", 0.86, locale),
                _news_topic_ref("supply_chain", 0.72, locale),
            ],
            "market_direction": "mixed",
            "source_links": [
                _news_source_ref("EIA", "https://www.eia.gov/petroleum/supply/weekly/", "eia", "Weekly petroleum status report", "주간 석유 현황 보고서", "T0_OFFICIAL", prior, locale),
                _news_source_ref("IEA", "https://www.iea.org/reports/oil-market-report", "iea", "Oil market report", "석유 시장 보고서", "T3_REVIEWED_PUBLIC_SOURCE", prior, locale, False),
                _news_source_ref("Source policy", "https://www.eia.gov/", "source_policy", "Official energy-data context", "공식 에너지 데이터 맥락", "T3_REVIEWED_PUBLIC_SOURCE", prior, locale, False),
            ],
            "one_sentence_summary": _t(locale, "Supply-risk monitoring separates official energy data from weaker geopolitical discovery signals.", "공급 리스크 모니터링은 공식 에너지 데이터와 약한 지정학 발견 신호를 구분합니다."),
            "what_happened": [
                _t(locale, "The event models an energy chokepoint/inventory monitoring cluster.", "이 이벤트는 에너지 해상 요충지/재고 모니터링 클러스터를 모델링합니다."),
            ],
            "why_it_matters": [
                _t(locale, "Energy supply shocks can feed inflation, rates, FX, transportation, and commodity-linked equities.", "에너지 공급 충격은 인플레이션, 금리, 환율, 운송, 원자재 연계 주식에 영향을 줄 수 있습니다."),
            ],
            "known_facts": [
                _t(locale, "Official inventory sources are kept separate from discovery-only feeds.", "공식 재고 출처는 발견 전용 피드와 분리됩니다."),
            ],
            "uncertainties": [
                _t(locale, "Chokepoint closure probability and duration require continuous source corroboration.", "요충지 폐쇄 가능성과 기간은 지속적인 출처 확인이 필요합니다."),
            ],
            "conflicting_reports": [],
            "market_relevance": {
                "direction": "mixed",
                "confidence": "medium",
                "reasoning": _t(locale, "Supply risk can lift energy inputs while pressuring inflation-sensitive growth assets.", "공급 리스크는 에너지 가격을 높일 수 있지만 인플레이션 민감 성장자산에는 압박이 될 수 있습니다."),
            },
            "methodology": _news_methodology(locale),
            "disclaimer": _news_disclaimer(locale),
        },
    ]
    list_items = [_news_list_item(event) for event in events]
    for event in events:
        event.setdefault("ticker_implications", _seed_ticker_implications(event, locale))
        related = [
            item
            for item in list_items
            if item["id"] != event["id"]
            and (
                {topic["key"] for topic in item["topics"]} & {topic["key"] for topic in event["topics"]}
                or {region["key"] for region in item["regions"]} & {region["key"] for region in event["regions"]}
            )
        ]
        event["related_events"] = related[:3]
    return events


def _seed_ticker_implications(event: dict[str, Any], locale: str) -> list[dict[str, str]]:
    direction = str(event.get("market_direction") or "unclear")
    if direction not in {"bullish", "bearish", "mixed", "unclear"}:
        direction = "unclear"
    confidence = "medium" if float(event.get("confidence") or 0) >= 0.7 else "low"
    implications: list[dict[str, str]] = []
    for ticker in event.get("tickers", []):
        symbol = str(ticker.get("symbol") or "").strip()
        if not symbol:
            continue
        relationship = str(ticker.get("relationship") or "").replace("_", " ")
        implications.append(
            {
                "symbol": symbol,
                "implication": _t(
                    locale,
                    f"{symbol} is linked as {relationship}; review the cited public sources before treating this as ticker-specific evidence.",
                    f"{symbol}은(는) {relationship} 관계로 연결됩니다. 티커별 근거로 보기 전에 인용된 공개 출처를 확인하세요.",
                ),
                "direction": direction,
                "confidence": confidence,
            }
        )
    return implications


def _news_list_item(event: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "id",
        "title",
        "summary",
        "event_type",
        "first_seen_at",
        "last_seen_at",
        "published_at",
        "freshness",
        "severity",
        "confidence",
        "breaking_score",
        "trust_score",
        "source_count",
        "tickers",
        "regions",
        "topics",
        "market_direction",
        "source_links",
    ]
    return {key: event[key] for key in keys}


def _news_filters(events: list[dict[str, Any]], locale: str) -> dict[str, list[dict[str, Any]]]:
    return {
        "regions": _news_facets(events, "regions", "key", locale),
        "topics": _news_facets(events, "topics", "key", locale),
        "tickers": _news_facets(events, "tickers", "symbol", locale),
        "trust_tiers": _news_trust_facets(events, locale),
    }


def _news_facets(events: list[dict[str, Any]], field: str, key_field: str, locale: str) -> list[dict[str, Any]]:
    labels: dict[str, str] = {}
    counts: dict[str, int] = {}
    for event in events:
        seen: set[str] = set()
        for ref in event.get(field, []):
            key = str(ref.get(key_field) or "")
            if not key or key in seen:
                continue
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
            labels[key] = str(ref.get("label") or ref.get("name") or _news_fallback_label(field, key, locale))
    return [
        {"key": key, "label": labels.get(key, key), "count": counts[key]}
        for key in sorted(counts, key=lambda item: (-counts[item], item))
    ]


def _news_trust_facets(events: list[dict[str, Any]], locale: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for event in events:
        seen = {str(source.get("trust_tier") or "") for source in event.get("source_links", [])}
        for key in seen:
            if key:
                counts[key] = counts.get(key, 0) + 1
    return [
        {"key": key, "label": _t(locale, *NEWS_TRUST_LABELS.get(key, (key, key))), "count": counts[key]}
        for key in sorted(counts, key=lambda item: (-counts[item], item))
    ]


def _news_fallback_label(field: str, key: str, locale: str) -> str:
    if field == "regions":
        return _news_region_name(key, locale)
    if field == "topics":
        label_en, label_ko = NEWS_TOPIC_LABELS.get(key, (key.replace("_", " ").title(), key))
        return _t(locale, label_en, label_ko)
    return key


def _news_ticker_ref(symbol: str, relationship: str, confidence: float, locale: str) -> dict[str, Any]:
    profile = NEWS_TICKER_PROFILES[symbol]
    return {
        "symbol": symbol,
        "name": _t(locale, profile["name_en"], profile["name_ko"]),
        "exchange": profile["exchange"],
        "relationship": relationship,
        "confidence": confidence,
    }


def _news_region_ref(key: str, relation: str, confidence: float, locale: str) -> dict[str, Any]:
    return {
        "key": key,
        "name": _news_region_name(key, locale),
        "relation": relation,
        "confidence": confidence,
    }


def _news_topic_ref(key: str, confidence: float, locale: str) -> dict[str, Any]:
    label_en, label_ko = NEWS_TOPIC_LABELS.get(key, (key.replace("_", " ").title(), key))
    return {"key": key, "label": _t(locale, label_en, label_ko), "confidence": confidence}


def _news_source_ref(
    label: str,
    url: str,
    source_key: str,
    title_en: str,
    title_ko: str,
    trust_tier: str,
    published_at: str,
    locale: str,
    is_primary: bool = True,
) -> dict[str, Any]:
    return {
        "label": label,
        "url": url,
        "source_key": source_key,
        "policy_version": 1,
        "title": _t(locale, title_en, title_ko),
        "published_at": published_at,
        "trust_tier": trust_tier,
        "is_primary": is_primary,
    }


def _news_region_name(key: str, locale: str) -> str:
    if key in COUNTRIES:
        return _t(locale, COUNTRIES[key][0], COUNTRIES[key][1])
    if key in REGIONS:
        return _t(locale, REGIONS[key][0], REGIONS[key][1])
    if key == "EU":
        return _t(locale, "European Union", "유럽연합")
    return key


def _news_symbol_key(symbol: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", symbol.upper()).strip("_")


def _news_ticker_summary(symbol: str, profile: dict[str, str], events: list[dict[str, Any]], locale: str) -> str:
    name = _t(locale, profile["name_en"], profile["name_ko"])
    if not events:
        return _t(locale, f"No approved news events are currently linked to {symbol}.", f"{symbol}에 연결된 승인 뉴스 이벤트가 아직 없습니다.")
    return _t(
        locale,
        f"{name} has {len(events)} approved, source-linked news event(s) in the public snapshot.",
        f"{name}에 대해 공개 스냅샷에 승인·출처 연결 뉴스 이벤트 {len(events)}건이 있습니다.",
    )


def _news_region_brief(region_key: str, events: list[dict[str, Any]], locale: str) -> str:
    name = _news_region_name(region_key, locale)
    return _t(
        locale,
        f"{name} has {len(events)} approved news event(s), with relation labels separating event location, affected region, and market region.",
        f"{name} 관련 승인 뉴스 이벤트 {len(events)}건이 있으며 발생지, 영향 지역, 시장 지역 라벨을 분리합니다.",
    )


def _news_topic_brief(topic_key: str, events: list[dict[str, Any]], locale: str) -> str:
    label_en, label_ko = NEWS_TOPIC_LABELS[topic_key]
    label = _t(locale, label_en, label_ko)
    return _t(
        locale,
        f"{label} includes {len(events)} approved event cluster(s) built from source-linked public metadata.",
        f"{label}에는 출처 연결 공개 메타데이터에서 만든 승인 이벤트 클러스터 {len(events)}건이 포함됩니다.",
    )


def _news_methodology(locale: str) -> str:
    return _t(
        locale,
        "Snapshot-first news: documents are normalized, entity/region/topic classified, clustered, reviewed, and published as source-linked metadata. Public users never trigger provider or LLM calls.",
        "스냅샷 우선 뉴스: 문서를 정규화하고 엔티티/지역/토픽을 분류한 뒤 클러스터링·검토하여 출처 연결 메타데이터로 게시합니다. 공개 사용자는 공급자나 LLM 호출을 유발하지 않습니다.",
    )


def _news_disclaimer(locale: str) -> str:
    return _t(
        locale,
        "News summaries are source-linked research context, not personalized investment advice.",
        "뉴스 요약은 출처 연결 리서치 맥락이며 개인화된 투자 조언이 아닙니다.",
    )


def _preserve_previous_active_macro_tiles(locale: str, tiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous = _previous_macro_tiles(locale)
    if not previous:
        return tiles
    preserved: list[dict[str, Any]] = []
    for tile in tiles:
        previous_tile = previous.get(str(tile.get("key")))
        if str(tile.get("key")) in TIME_SENSITIVE_MARKET_TILE_KEYS and _is_metric_tile_unavailable(tile):
            preserved.append(tile)
            continue
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
            _observation_freshness(str(series["date"]), generated_at),
            unit,
            f"{FRED_SERIES_BASE_URL}/{series_id}",
            series["points"],
            "active",
            next_event,
            refresh_seconds,
            _observation_updated_at(str(series["date"])),
        )

    def mof_jgb_tile(
        key: str,
        label_en: str,
        label_ko: str,
        term: str,
        next_event: dict[str, str] | None = None,
        refresh_seconds: int = 2_592_000,
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
            _observation_freshness(str(series["date"]), generated_at),
            "%",
            MOF_JGB_PAGE_URL,
            series["points"],
            "active",
            next_event,
            refresh_seconds,
            _observation_updated_at(str(series["date"])),
        )

    def treasury_tile(
        key: str,
        label_en: str,
        label_ko: str,
        term_key: str,
        term_label: str,
        next_event: dict[str, str] | None = None,
        refresh_seconds: int = 43200,
    ) -> dict[str, Any]:
        series = _treasury_yield_curve_series(term_key, generated_at)
        if not series:
            return coverage_gap_tile(
                key,
                label_en,
                label_ko,
                "U.S. Treasury XML feed",
                "Treasury Daily Interest Rate XML feed unavailable during snapshot build",
                "스냅샷 생성 중 미국 재무부 일일 금리 XML 피드를 사용할 수 없습니다.",
                "%",
                TREASURY_YIELD_FEED_DOC_URL,
                refresh_seconds,
            )
        return tile(
            key,
            label_en,
            label_ko,
            _format_metric_value(series["value"], 2),
            "U.S. Treasury XML feed",
            _actual_delay_label(locale, f"Treasury {term_label}", series["date"]),
            _observation_freshness(str(series["date"]), generated_at),
            "%",
            TREASURY_YIELD_FEED_DOC_URL,
            series["points"],
            "active",
            next_event,
            refresh_seconds,
            _observation_updated_at(str(series["date"])),
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
        fresh_after_minutes: int = 90,
        stale_after_hours: int = 36,
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
            _observation_freshness(str(series["date"]), generated_at),
            unit,
            source_url,
            series["points"],
            "active",
            None,
            refresh_seconds,
            _observation_updated_at(str(series["date"])),
        )

    def market_quote_tile(
        key: str,
        label_en: str,
        label_ko: str,
        *,
        yahoo_symbol: str | None = None,
        stooq_symbol: str | None = None,
        finnhub_symbol: str | None = None,
        twelve_data_symbol: str | None = None,
        source_name: str,
        unit: str | None = None,
        decimals: int = 2,
        refresh_seconds: int = 900,
        fresh_after_minutes: int = 90,
        stale_after_hours: int = 36,
        stooq_multiplier: float = 1.0,
    ) -> dict[str, Any]:
        candidates: list[tuple[str, dict[str, Any] | None]] = []
        if yahoo_symbol:
            candidates.append(("Yahoo Finance delayed quote", _yahoo_chart_series(yahoo_symbol)))
        if stooq_symbol:
            candidates.append(("Stooq delayed quote", scale_quote_series(_stooq_quote_series(stooq_symbol), stooq_multiplier)))
        if finnhub_symbol and _market_pulse_public_provider_allowed("finnhub"):
            candidates.append(("Finnhub quote", _finnhub_quote_series(finnhub_symbol)))
        if twelve_data_symbol and _market_pulse_public_provider_allowed("twelve_data"):
            candidates.append(("Twelve Data quote", _twelve_data_quote_series(twelve_data_symbol)))
        selected = _freshest_quote_candidate(candidates)
        selected_source_name = selected[0] if selected else source_name
        series = selected[1] if selected else None
        source_url = str(series.get("source_url") or "") if series else None
        if not series:
            return coverage_gap_tile(
                key,
                label_en,
                label_ko,
                source_name,
                f"{source_name} quote unavailable during snapshot build; stale FRED replacement is intentionally blocked for this time-sensitive tile",
                f"스냅샷 생성 중 {source_name} 시세를 사용할 수 없어, 시간 민감 항목에 오래된 FRED 대체값을 사용하지 않았습니다.",
                unit,
                source_url,
                refresh_seconds,
            )
        freshness = _timestamp_freshness(
            str(series["updated_at"]),
            generated_at,
            fresh_after_minutes=fresh_after_minutes,
            stale_after_hours=stale_after_hours,
        )
        effective_refresh_seconds = refresh_seconds if freshness == "fresh" else max(refresh_seconds, 43200)
        source_label = (
            selected_source_name
            if selected_source_name.lower().endswith("quote")
            else f"{selected_source_name} quote"
        )
        detail_en = (
            f"{source_label} observed at {series['updated_at']}; "
            "not guaranteed realtime exchange tape."
        )
        detail_ko = (
            f"{source_label} 관측 {series['updated_at']}; "
            "실시간 거래소 시세를 보장하지 않습니다."
        )
        if freshness != "fresh":
            detail_en = (
                f"Latest available {source_label} observed at {series['updated_at']}; "
                "market may be closed or the public feed may be delayed; not guaranteed realtime exchange tape."
            )
            detail_ko = (
                f"사용 가능한 최신 {source_label} 관측 {series['updated_at']}; "
                "시장이 닫혔거나 공개 피드가 지연될 수 있습니다. 실시간 거래소 시세를 보장하지 않습니다."
            )
        payload = tile(
            key,
            label_en,
            label_ko,
            _format_metric_value(float(series["value"]), decimals),
            selected_source_name,
            _t(locale, detail_en, detail_ko),
            freshness,
            unit,
            source_url,
            series.get("points"),
            "active",
            None,
            effective_refresh_seconds,
            str(series["updated_at"]),
        )
        if series.get("change") is not None:
            payload["refresh_delta"] = series["change"]
        if series.get("percent_change") is not None:
            payload["refresh_delta_percent"] = series["percent_change"]
        return payload

    def scale_quote_series(series: dict[str, Any] | None, multiplier: float) -> dict[str, Any] | None:
        if not series or multiplier == 1.0:
            return series
        scaled = dict(series)
        for key in ("value", "change"):
            if scaled.get(key) is not None:
                scaled[key] = float(scaled[key]) * multiplier
        if scaled.get("points"):
            scaled["points"] = [
                {**point, "value": float(point["value"]) * multiplier}
                for point in scaled["points"]
                if point.get("value") is not None
            ]
        return scaled

    def boj_policy_rate_tile() -> dict[str, Any]:
        series = _boj_daily_rate_series("FM01", "STRDCLUCON", generated_at)
        source = "BoJ Time-Series Data Search"
        if not series:
            return coverage_gap_tile(
                "japan_policy_rate",
                "BoJ overnight call rate",
                "일본은행 무담보 익일물 콜금리",
                source,
                "BoJ FM01/STRDCLUCON daily call-rate data unavailable during snapshot build; stale FRED/OECD monthly data remains blocked.",
                "스냅샷 생성 중 일본은행 FM01/STRDCLUCON 일일 콜금리 데이터를 사용할 수 없어 오래된 FRED/OECD 월간 데이터는 계속 차단했습니다.",
                "%",
                OFFICIAL_POLICY_CALENDAR_URLS["bank_of_japan"],
                43200,
            )
        last_update = str(series.get("last_update") or series["date"])
        detail = _t(
            locale,
            f"BoJ FM01/STRDCLUCON daily average actual through {series['date']}; API last updated {last_update}.",
            f"일본은행 FM01/STRDCLUCON 일일 평균 실제값, {series['date']}까지; API 최종 갱신 {last_update}.",
        )
        return tile(
            "japan_policy_rate",
            "BoJ overnight call rate",
            "일본은행 무담보 익일물 콜금리",
            _format_metric_value(float(series["value"]), 3),
            source,
            detail,
            _observation_freshness(last_update, generated_at, max_age_days=5),
            "%",
            str(series.get("source_url") or OFFICIAL_POLICY_CALENDAR_URLS["bank_of_japan"]),
            series.get("points"),
            "active",
            rate_event("japan"),
            43200,
            _observation_updated_at(last_update),
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
            _observation_freshness(str(series["date"]), generated_at),
            "$",
            ISHARES_EWY_URL,
            series.get("points"),
            "active",
            None,
            43200,
            _observation_updated_at(str(series["date"])),
        )
        if series.get("change") is not None:
            payload["refresh_delta"] = series["change"]
        if series.get("percent_change") is not None:
            payload["refresh_delta_percent"] = series["percent_change"]
        return payload

    def korea_equity_tiles() -> list[dict[str, Any]]:
        direct_tiles = [
            market_quote_tile(
                "kospi",
                "KOSPI",
                "코스피",
                yahoo_symbol="^KS11",
                stooq_symbol="^kospi",
                source_name="Yahoo/Stooq delayed quote",
            ),
            market_quote_tile(
                "kodex_200",
                "KODEX 200 ETF",
                "KODEX 200 ETF",
                yahoo_symbol="069500.KS",
                source_name="Yahoo Finance delayed quote",
                unit="KRW",
                decimals=0,
            ),
        ]
        if all(tile.get("coverage_status") == "active" for tile in direct_tiles):
            return direct_tiles
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
            unit,
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
        market_quote_tile(
            "nasdaq_composite",
            "Nasdaq Composite",
            "나스닥 종합",
            yahoo_symbol="^IXIC",
            source_name="Yahoo Finance delayed quote",
        ),
        market_quote_tile(
            "nasdaq_100",
            "Nasdaq 100",
            "나스닥 100",
            yahoo_symbol="^NDX",
            stooq_symbol="^ndx",
            source_name="Yahoo/Stooq delayed quote",
        ),
        *korea_equity_tiles(),
        market_quote_tile(
            "wti_crude",
            "WTI crude oil futures",
            "WTI 원유 선물",
            yahoo_symbol="CL=F",
            stooq_symbol="cl.f",
            source_name="Yahoo/Stooq delayed futures quote",
            unit="$",
            decimals=2,
            fresh_after_minutes=45,
            stale_after_hours=24,
        ),
        market_quote_tile(
            "gold_futures",
            "Gold futures",
            "금 선물",
            yahoo_symbol="GC=F",
            stooq_symbol="gc.f",
            source_name="Yahoo/Stooq delayed futures quote",
            unit="$",
            decimals=2,
            fresh_after_minutes=45,
            stale_after_hours=24,
        ),
        market_quote_tile(
            "silver_futures",
            "Silver futures",
            "은 선물",
            yahoo_symbol="SI=F",
            stooq_symbol="si.f",
            source_name="Yahoo/Stooq delayed futures quote",
            unit="$",
            decimals=3,
            fresh_after_minutes=45,
            stale_after_hours=24,
            stooq_multiplier=0.01,
        ),
        market_quote_tile(
            "copper_futures",
            "Copper futures",
            "구리 선물",
            yahoo_symbol="HG=F",
            stooq_symbol="hg.f",
            source_name="Yahoo/Stooq delayed futures quote",
            unit="$",
            decimals=4,
            fresh_after_minutes=45,
            stale_after_hours=24,
            stooq_multiplier=0.01,
        ),
        market_quote_tile("vix", "VIX", "VIX", yahoo_symbol="^VIX", source_name="Yahoo Finance delayed quote", fresh_after_minutes=45, stale_after_hours=24),
        market_quote_tile(
            "usd_krw",
            "USD/KRW",
            "달러/원",
            yahoo_symbol="KRW=X",
            twelve_data_symbol="USD/KRW",
            source_name="Yahoo Finance delayed FX quote",
            unit="KRW",
            decimals=2,
            fresh_after_minutes=30,
            stale_after_hours=24,
        ),
        market_quote_tile(
            "usd_jpy",
            "USD/JPY",
            "달러/엔",
            yahoo_symbol="JPY=X",
            twelve_data_symbol="USD/JPY",
            source_name="Yahoo Finance delayed FX quote",
            unit="JPY",
            decimals=2,
            fresh_after_minutes=30,
            stale_after_hours=24,
        ),
        treasury_tile("us_2y", "US Treasury 2Y", "미국 국채 2년", "BC_2YEAR", "2Y", rate_event("us")),
        treasury_tile("us_3y", "US Treasury 3Y", "미국 국채 3년", "BC_3YEAR", "3Y", rate_event("us")),
        treasury_tile("us_5y", "US Treasury 5Y", "미국 국채 5년", "BC_5YEAR", "5Y", rate_event("us")),
        treasury_tile("us_10y", "US Treasury 10Y", "미국 국채 10년", "BC_10YEAR", "10Y", rate_event("us")),
        boj_policy_rate_tile(),
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
        updated_at: str | None = None,
        symbols: list[str] | None = None,
        dataset: str | None = None,
        as_of_date: str | None = None,
        provider_observation_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": f"{lane_key}_{key}",
            "label": _t(locale, label_en, label_ko),
            "value": value,
            "detail": _t(locale, detail_en, detail_ko),
            "source": source,
            "freshness": freshness,
            "severity": severity,
            "updated_at": updated_at or updated,
        }
        if source_url:
            payload["source_url"] = source_url
        if symbols:
            payload["symbols"] = symbols
        if dataset:
            payload["dataset"] = dataset
        if as_of_date:
            payload["as_of_date"] = as_of_date
        if provider_observation_key:
            payload["provider_observation_key"] = provider_observation_key
        return payload

    symbols = _symbol_list(env.get("SHORT_VOLUME_MONITORED_TICKERS") or DEFAULT_SHORT_TICKERS)
    short_interest = _latest_short_interest(_finra_short_interest_rows(symbols), symbols)
    short_volume = _latest_short_volume(_finra_short_volume_rows(symbols), symbols)
    trump_documents = _recent_sec_documents(DEFAULT_TRUMP_CIKS["DJT"])
    ai_summary_ready = any(
        _env_has(env, key)
        for key in (
            "NVIDIA_NIM_API_KEY",
            "NVIDIA_API_KEY",
            "GEMINI_API_KEY",
            "GROQ_API_KEY",
            "CEREBRAS_API_KEY",
            "MISTRAL_API_KEY",
            "OPENROUTER_API_KEY",
        )
    )
    summary_status = _t(locale, "ready", "준비됨") if ai_summary_ready else _t(locale, "remote LLM key needed", "원격 LLM 키 필요")
    news_max_age_hours = 24
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
        for article in _gdelt_articles(query, maxrecords=8, generated_at=generated_at, max_age_hours=news_max_age_hours):
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
                    article.get("seen_at") or None,
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
            f"{GOOGLE_NEWS_RSS_URL}?{parse.urlencode({'q': '(Iran OR Hormuz OR Taiwan OR \"Red Sea\") (oil OR shipping OR markets) when:1d', 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})}",
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
        for article in _rss_articles(url, cache_key=source_key, maxrecords=8, generated_at=generated_at, max_age_hours=news_max_age_hours):
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
                    article.get("seen_at") or None,
                )
            )
    if len(market_news_items) < 4:
        for article in _gdelt_bulk_articles(generated_at=generated_at, maxrecords=8, max_age_hours=news_max_age_hours):
            if article["url"] in seen_news_urls:
                continue
            seen_news_urls.add(article["url"])
            market_news_items.append(
                item(
                    "breaking_market_news",
                    f"gdelt_bulk_{article['key']}",
                    article["title"],
                    article["title"],
                    _t(locale, "event metadata", "이벤트 메타데이터"),
                    f"GDELT event file; {article['domain']}; seen {article['seen_date']}",
                    f"GDELT 이벤트 파일; {article['domain']}; 관측 {article['seen_date']}",
                    "GDELT Event Files",
                    article.get("severity") or "medium",
                    "fresh",
                    article["url"],
                    article.get("seen_at") or None,
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
                "No max-24h breaking headlines passed the recency gate during this snapshot build.",
                "이번 스냅샷 빌드에서 최대 24시간 이내 속보 헤드라인이 통과하지 못했습니다.",
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
            symbols=[row["symbol"]],
            dataset="consolidatedShortInterest",
            as_of_date=row["date"],
            provider_observation_key=_short_fact_observation_key("consolidatedShortInterest", row["symbol"], row["date"], row["value"]),
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
            symbols=[row["symbol"]],
            dataset="regShoDaily",
            as_of_date=row["date"],
            provider_observation_key=_short_fact_observation_key("regShoDaily", row["symbol"], row["date"], row["value"]),
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
            else _t(locale, "no current headlines", "현재 속보 없음"),
            "cadence": _t(locale, "5-minute target; only max-24h headlines are shown as breaking.", "5분 목표; 최대 24시간 이내 헤드라인만 속보로 표시합니다."),
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
            "value": _t(locale, "7 sources", "7개 출처"),
            "cadence": _t(locale, "15-minute source checks once live ingestion is enabled.", "라이브 수집 활성화 후 15분 간격으로 출처를 점검합니다."),
            "source": "public research websites/RSS/news",
            "freshness": "watch",
            "severity": "high",
            "refresh_seconds": 900,
            "items": [
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


def match_geo_points(
    *,
    texts: list[str],
    region_keys: list[str] | None = None,
    topic_keys: list[str] | None = None,
    max_points: int = 4,
) -> list[dict[str, Any]]:
    normalized_text = " ".join(text.lower() for text in texts if text).strip()
    explicit_region_keys = {str(key).upper() for key in (region_keys or []) if str(key).strip()}
    topics = {str(key).lower() for key in (topic_keys or []) if str(key).strip()}
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for area in _geopolitical_registry_payload()["areas"]:
        score, reason_codes = _geo_area_score(area, normalized_text, explicit_region_keys, topics)
        if score < 0.7 or area["key"] in seen:
            continue
        seen.add(area["key"])
        matches.append(
            {
                "point_id": f"geo_{area['key'].lower()}",
                "area_key": area["key"],
                "area_label": area["name"],
                "relation": "chokepoint" if area["kind"] == "chokepoint" else "event_location",
                "latitude": area["latitude"],
                "longitude": area["longitude"],
                "geo_confidence": round(score, 3),
                "market_themes": area["market_themes"],
                "area_priority": area["base_market_weight"],
                "score_reason_codes": reason_codes,
            }
        )
    matches.sort(key=lambda item: (item["area_priority"], item["geo_confidence"], item["area_key"]), reverse=True)
    return matches[:max_points]


def registry_version() -> int:
    return int(_geopolitical_registry_payload().get("version") or 1)


def registry_scoring_version() -> str:
    return str(_geopolitical_registry_payload().get("scoring_version") or "geo-priority-v1")


def registry_thinning_version() -> str:
    return str(_geopolitical_registry_payload().get("thinning_version") or "freshness-area-cap-v1")


def _geopolitical_registry_payload() -> dict[str, Any]:
    global _GEOPOLITICAL_REGISTRY_CACHE
    if _GEOPOLITICAL_REGISTRY_CACHE is not None:
        return _GEOPOLITICAL_REGISTRY_CACHE
    try:
        payload = json.loads(GEOPOLITICAL_WATCH_REGISTRY_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        payload = {}
    areas: list[dict[str, Any]] = []
    raw_areas = payload.get("areas", []) if isinstance(payload, dict) else []
    for raw in raw_areas:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "").upper().strip()
        name = str(raw.get("name") or "").strip()
        aliases = [str(alias).lower().strip() for alias in raw.get("aliases", []) if str(alias).strip()]
        try:
            latitude = float(raw.get("latitude"))
            longitude = float(raw.get("longitude"))
            weight = int(raw.get("base_market_weight") or 50)
        except (TypeError, ValueError):
            continue
        if not key or not name or not aliases:
            continue
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue
        if abs(latitude) < 0.0001 and abs(longitude) < 0.0001:
            continue
        areas.append(
            {
                "key": key,
                "kind": "chokepoint" if raw.get("kind") == "chokepoint" else "country",
                "name": name,
                "aliases": aliases,
                "latitude": latitude,
                "longitude": longitude,
                "base_market_weight": max(0, min(100, weight)),
                "market_themes": [str(theme).strip() for theme in raw.get("market_themes", []) if str(theme).strip()],
            }
        )
    _GEOPOLITICAL_REGISTRY_CACHE = {
        "version": int(payload.get("version") or 1) if isinstance(payload, dict) else 1,
        "scoring_version": str(payload.get("scoring_version") or "geo-priority-v1") if isinstance(payload, dict) else "geo-priority-v1",
        "thinning_version": str(payload.get("thinning_version") or "freshness-area-cap-v1") if isinstance(payload, dict) else "freshness-area-cap-v1",
        "areas": areas,
    }
    return _GEOPOLITICAL_REGISTRY_CACHE


def _geo_area_score(area: dict[str, Any], text: str, region_keys: set[str], topics: set[str]) -> tuple[float, list[str]]:
    score = 0.0
    reason_codes: list[str] = []
    if area["key"] in region_keys:
        score += 0.85
        reason_codes.append("explicit_region")
    for alias in area["aliases"]:
        if alias in text:
            score += 0.82 if area["kind"] == "chokepoint" else 0.72
            reason_codes.append("alias_match")
            break
    theme_hits = {theme for theme in area["market_themes"] if theme.lower() in topics or theme.lower() in text}
    if theme_hits:
        score += min(0.18, 0.06 * len(theme_hits))
        reason_codes.append("market_theme")
    if area["kind"] == "chokepoint" and any(term in text for term in ("shipping", "oil", "lng", "freight", "strait", "canal")):
        score += 0.08
        reason_codes.append("chokepoint_context")
    return min(1.0, score), reason_codes


def _breaking_market_projection_from_signals(lanes: list[dict[str, Any]], *, generated_at: datetime) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for lane in lanes:
        if lane.get("key") != "breaking_market_news":
            continue
        for item in lane.get("items", []):
            event = _breaking_market_event_from_signal(item, generated_at=generated_at)
            if event is not None:
                events.append(event)
    events.sort(
        key=lambda event: (
            event["urgency_score"],
            event["freshness_confidence"],
            event["geo_confidence"],
            event["source_published_at"],
        ),
        reverse=True,
    )
    points = [point for event in events for point in event["geo_points"]]
    points.sort(
        key=lambda point: (
            point["urgency_score"],
            point["area_priority"],
            point["geo_confidence"],
            point["source_published_at"],
            point["event_id"],
        ),
        reverse=True,
    )
    total_count = len(points)
    capped_points = points[:250]
    capped_events = _events_for_map_points(events, capped_points)
    payload = _breaking_market_payload(
        events=capped_events,
        points=capped_points,
        total_count=total_count,
        generated_at=generated_at,
    )
    while _breaking_payload_size(payload) > 250_000 and payload["map_points"]:
        payload["map_points"] = payload["map_points"][:-1]
        payload["events"] = _events_for_map_points(events, payload["map_points"])
        payload["shown_count"] = len(payload["map_points"])
        payload["ranking_cutoff"] = _ranking_cutoff(payload["map_points"], total_count)
    return payload


def _breaking_market_event_from_signal(item: dict[str, Any], *, generated_at: datetime) -> dict[str, Any] | None:
    source_published_at = _parse_snapshot_timestamp(str(item.get("updated_at") or ""))
    if source_published_at is None:
        return None
    age = generated_at - source_published_at
    if age < timedelta(0) or age > timedelta(hours=24):
        return None
    geo_matches = match_geo_points(
        texts=[
            str(item.get("label") or ""),
            str(item.get("detail") or ""),
            str(item.get("source") or ""),
        ],
        max_points=4,
    )
    if not geo_matches:
        return None
    severity = str(item.get("severity") or "medium")
    if severity not in {"low", "medium", "high", "critical"}:
        severity = "medium"
    urgency_score = _signal_urgency_score(item, source_published_at=source_published_at, generated_at=generated_at)
    observed_at = source_published_at
    label = _seed_breaking_label(
        urgency_score,
        generated_at=generated_at,
        source_published_at=source_published_at,
        observed_at=observed_at,
    )
    if label == "stale":
        return None
    source_url = _safe_public_url(str(item.get("source_url") or ""))
    event_seed = f"{item.get('key')}|{source_url}|{item.get('label')}"
    event_id = f"seed_{hashlib.sha1(event_seed.encode()).hexdigest()[:14]}"
    citation_id = hashlib.sha1(f"{item.get('source') or 'source'}|{source_url}".encode()).hexdigest()[:16] if source_url else event_id
    source_published_iso = source_published_at.isoformat().replace("+00:00", "Z")
    observed_iso = observed_at.isoformat().replace("+00:00", "Z")
    title = _safe_display_text(str(item.get("label") or "Market watch headline"), 180)
    summary = _safe_display_text(str(item.get("detail") or ""), 500)
    score_reason_codes = sorted(
        {
            "seed_snapshot",
            f"label_{label}",
            *[code for point in geo_matches for code in point["score_reason_codes"]],
        }
    )
    geo_confidence = max(point["geo_confidence"] for point in geo_matches)
    event: dict[str, Any] = {
        "event_id": event_id,
        "title": title,
        "summary": summary,
        "source_published_at": source_published_iso,
        "observed_at": observed_iso,
        "verified_at": observed_iso,
        "freshness_confidence": _seed_freshness_confidence(generated_at, source_published_at, observed_at),
        "urgency_score": urgency_score,
        "severity": severity,
        "trust_tier": "T4_WEAK_SIGNAL",
        "discovery_only": True,
        "review_state": "reviewed",
        "citation_ids": [citation_id],
        "retention_class": "metadata_only",
        "geo_points": [],
        "geo_confidence": geo_confidence,
        "score_reason_codes": score_reason_codes,
        "dedupe_key": hashlib.sha256(f"{event_id}|{source_published_iso}|{citation_id}".encode()).hexdigest(),
        "label": label,
        "tickers": [],
        "regions": [],
        "topics": [],
        "source_count": 1,
    }
    if source_url:
        event["source_url"] = source_url
    event_points: list[dict[str, Any]] = []
    for point in geo_matches:
        area_priority, priority_reason_codes = _area_priority(
            point,
            urgency_score=urgency_score,
            severity=severity,
            source_count=1,
            label=label,
        )
        event_points.append(
            {
                "point_id": f"{point['point_id']}_{event_id.removeprefix('seed_')}",
                "event_id": event_id,
                "title": title,
                "summary": summary,
                "area_key": point["area_key"],
                "area_label": point["area_label"],
                "relation": point["relation"],
                "latitude": point["latitude"],
                "longitude": point["longitude"],
                "severity": severity,
                "urgency_score": urgency_score,
                "source_published_at": source_published_iso,
                "observed_at": observed_iso,
                "source_count": 1,
                "geo_confidence": point["geo_confidence"],
                "area_priority": area_priority,
                "score_reason_codes": sorted(set(point["score_reason_codes"] + score_reason_codes + priority_reason_codes)),
            }
        )
    event["geo_points"] = event_points
    return event


def _area_priority(
    point: dict[str, Any],
    *,
    urgency_score: int,
    severity: str,
    source_count: int,
    label: str,
) -> tuple[int, list[str]]:
    priority = int(point.get("area_priority") or 0)
    reason_codes = ["base_market_weight"]
    if urgency_score >= 70:
        priority += 14
        reason_codes.append("urgent_event")
    elif urgency_score >= 50:
        priority += 8
        reason_codes.append("elevated_event")
    severity_boosts = {"critical": 16, "high": 12, "medium": 5, "low": 0}
    severity_boost = severity_boosts.get(severity, 0)
    if severity_boost:
        priority += severity_boost
        reason_codes.append("severity_boost")
    source_boost = min(10, max(0, source_count - 1) * 3)
    if source_boost:
        priority += source_boost
        reason_codes.append("source_velocity")
    if label == "breaking":
        priority += 10
        reason_codes.append("fresh_breaking")
    elif label == "developing":
        priority += 5
        reason_codes.append("developing_velocity")
    if point.get("relation") == "chokepoint":
        priority += 6
        reason_codes.append("chokepoint_market_weight")
    return max(0, min(100, priority)), reason_codes


def _events_for_map_points(events: list[dict[str, Any]], points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    point_ids_by_event: dict[str, set[str]] = {}
    for point in points:
        point_ids_by_event.setdefault(point["event_id"], set()).add(point["point_id"])
    trimmed_events: list[dict[str, Any]] = []
    for event in events:
        allowed_point_ids = point_ids_by_event.get(event["event_id"])
        if not allowed_point_ids:
            continue
        cloned = dict(event)
        cloned["geo_points"] = [point for point in event["geo_points"] if point["point_id"] in allowed_point_ids]
        trimmed_events.append(cloned)
    return trimmed_events


def _breaking_market_payload(
    *,
    events: list[dict[str, Any]],
    points: list[dict[str, Any]],
    total_count: int,
    generated_at: datetime,
) -> dict[str, Any]:
    return {
        "events": events,
        "map_points": points,
        "shown_count": len(points),
        "total_count": total_count,
        "ranking_cutoff": _ranking_cutoff(points, total_count),
        "registry_version": registry_version(),
        "scoring_version": registry_scoring_version(),
        "thinning_version": registry_thinning_version(),
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
    }


def _ranking_cutoff(points: list[dict[str, Any]], total_count: int) -> int | None:
    if not points or len(points) >= total_count:
        return None
    return int(points[-1]["urgency_score"])


def _breaking_payload_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())


def _signal_urgency_score(item: dict[str, Any], *, source_published_at: datetime, generated_at: datetime) -> int:
    age_minutes = max(0, int((generated_at - source_published_at).total_seconds() // 60))
    severity = str(item.get("severity") or "medium")
    base = {"critical": 88, "high": 76, "medium": 62, "low": 48}.get(severity, 62)
    recency_bonus = max(0, 18 - min(18, age_minutes // 10))
    return max(0, min(100, base + recency_bonus))


def _seed_breaking_label(
    urgency_score: int,
    *,
    generated_at: datetime,
    source_published_at: datetime,
    observed_at: datetime,
) -> str:
    published_age = generated_at - source_published_at
    observed_age = generated_at - observed_at
    if published_age <= timedelta(hours=2) and observed_age <= timedelta(minutes=20) and urgency_score >= 70:
        return "breaking"
    if published_age <= timedelta(hours=8) or urgency_score >= 65:
        return "developing"
    if published_age <= timedelta(hours=24):
        return "latest"
    return "stale"


def _seed_freshness_confidence(generated_at: datetime, source_published_at: datetime, observed_at: datetime) -> float:
    published_age = max(0.0, (generated_at - source_published_at).total_seconds())
    observed_age = max(0.0, (generated_at - observed_at).total_seconds())
    max_age = timedelta(hours=24).total_seconds()
    return round((max(0.0, 1.0 - published_age / max_age) * 0.72) + (max(0.0, 1.0 - observed_age / max_age) * 0.28), 3)


def _parse_snapshot_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_public_url(value: str) -> str:
    parsed = parse.urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    host = parsed.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port else host
    return parsed._replace(netloc=netloc, query="", fragment="").geturl()


def _safe_display_text(value: str, max_length: int) -> str:
    return re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]+", " ", value).strip()[:max_length]


def _entity_name(entity: dict[str, Any], locale: str) -> str:
    name = entity.get("name") if isinstance(entity.get("name"), dict) else {}
    return str(name.get(locale) or name.get("en") or entity.get("display_symbol") or entity.get("symbol") or "Tracked entity")


def _tracked_entity_ref(entity: dict[str, Any], locale: str, generated_at: datetime) -> dict[str, Any]:
    symbol = str(entity.get("symbol") or "").upper()
    route_kind = str(entity.get("route_kind") or "ticker")
    if route_kind not in {"ticker", "reference_entity"}:
        route_kind = "unsupported"
    return {
        "entity_id": str(entity.get("entity_id") or symbol.lower()),
        "symbol": symbol,
        "display_symbol": str(entity.get("display_symbol") or symbol),
        "name": _entity_name(entity, locale),
        "route_kind": route_kind,
        "route_key": str(entity.get("route_key") or _symbol_route_key(symbol)),
        "sector_keys": [str(key) for key in entity.get("sector_keys", []) if isinstance(key, str)],
        "tags": [str(tag) for tag in entity.get("tags", []) if isinstance(tag, str)],
        "source_strength": str(entity.get("source_strength") or "registry"),
        "freshness": _entity_registry_freshness(entity, generated_at),
    }


def _entity_registry_freshness(entity: dict[str, Any], generated_at: datetime) -> str:
    reviewed_at = str(entity.get("last_reviewed_at") or "")
    if not reviewed_at:
        return "watch"
    try:
        reviewed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError:
        return "watch"
    return "fresh" if generated_at - reviewed.astimezone(timezone.utc) <= timedelta(days=60) else "watch"


def _tracked_entities_for_sector(key: str) -> list[dict[str, Any]]:
    entities = [
        entity
        for entity in _tracked_entity_records()
        if key in [str(value) for value in entity.get("sector_keys", [])]
    ]
    return sorted(entities, key=lambda entity: (str(entity.get("route_kind") or ""), str(entity.get("symbol") or "")))


def _sector_news_items(key: str, news_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sector_symbols = {str(entity.get("symbol") or "").upper() for entity in _tracked_entities_for_sector(key)}
    direct = [
        item
        for item in news_items
        if any(str(ticker.get("symbol") or "").upper() in sector_symbols for ticker in item.get("tickers", []))
    ]
    if direct:
        return direct[:8]
    topic_aliases = {
        "oil-energy": {"energy", "geopolitics", "supply_chain"},
        "big-tech": {"semiconductors", "trade_policy"},
    }
    aliases = topic_aliases.get(key, {key})
    return [
        item
        for item in news_items
        if any(str(topic.get("key") or "") in aliases for topic in item.get("topics", []))
    ][:4]


def _ticker_calendar_items_for_sector(
    key: str,
    locale: str,
    news_items: list[dict[str, Any]],
    generated_at: datetime,
) -> list[dict[str, Any]]:
    sector_symbols = {str(entity.get("symbol") or "").upper() for entity in _tracked_entities_for_sector(key)}
    by_symbol = _tracked_entity_by_symbol()
    items: list[dict[str, Any]] = []
    for news in news_items:
        event_type = str(news.get("event_type") or "")
        catalyst_type = _catalyst_type_from_event(event_type)
        if catalyst_type is None:
            continue
        source_links = [source for source in news.get("source_links", []) if isinstance(source, dict)]
        source = source_links[0] if source_links else {}
        if not str(source.get("url") or "").startswith("http"):
            continue
        for ticker in news.get("tickers", []):
            symbol = str(ticker.get("symbol") or "").upper()
            if symbol not in sector_symbols or symbol not in by_symbol:
                continue
            entity = by_symbol[symbol]
            published_at = str(news.get("published_at") or generated_at.isoformat().replace("+00:00", "Z"))
            local_date = published_at[:10] if re.match(r"\d{4}-\d{2}-\d{2}", published_at) else generated_at.date().isoformat()
            items.append(
                {
                    "id": f"{key}_{_symbol_route_key(symbol)}_{news['id']}",
                    "entity_id": str(entity.get("entity_id") or symbol.lower()),
                    "symbol": symbol,
                    "title": _t(locale, f"{symbol}: {news['title']}", f"{symbol}: {news['title']}"),
                    "catalyst_type": catalyst_type,
                    "scheduled_at": published_at,
                    "scheduled_local_date": local_date,
                    "timezone": "UTC",
                    "source": str(source.get("label") or news.get("source") or "source"),
                    "source_url": str(source.get("url") or ""),
                    "freshness": str(news.get("freshness") or "watch"),
                    "confidence": float(news.get("confidence") or 0.5),
                }
            )
    deduped: dict[str, dict[str, Any]] = {}
    for item in items:
        deduped[item["id"]] = item
    return sorted(deduped.values(), key=lambda item: (item["scheduled_local_date"], item["symbol"]))[:8]


def _catalyst_type_from_event(event_type: str) -> str | None:
    normalized = event_type.lower()
    if normalized in {"company_update", "trade_policy"}:
        return "company_event" if normalized == "company_update" else "source_review"
    if "launch" in normalized:
        return "launch_window"
    if "contract" in normalized:
        return "contract_milestone"
    if "filing" in normalized:
        return "filing"
    return None


def _short_fact_observation_key(dataset: str, symbol: str, as_of_date: str, value: float | int | None) -> str:
    return hashlib.sha256(f"{dataset}|{symbol.upper()}|{as_of_date}|{value}".encode()).hexdigest()


def _short_fact_freshness(fact_type: str, as_of_date: str, generated_at: datetime) -> str:
    try:
        observed = datetime.strptime(as_of_date[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return "watch"
    max_fresh = timedelta(days=21 if fact_type == "short_interest" else 3)
    max_watch = timedelta(days=45 if fact_type == "short_interest" else 7)
    age = generated_at - observed
    if age <= max_fresh:
        return "fresh"
    if age <= max_watch:
        return "watch"
    return "stale"


def _sector_short_facts(key: str, generated_at: datetime) -> list[dict[str, Any]]:
    cache_key = (key, generated_at.date().isoformat())
    if cache_key in _SECTOR_SHORT_FACT_CACHE:
        return _SECTOR_SHORT_FACT_CACHE[cache_key]
    entities = [entity for entity in _tracked_entities_for_sector(key) if str(entity.get("route_kind") or "ticker") == "ticker"]
    symbols = [str(entity.get("symbol") or "").upper() for entity in entities if str(entity.get("symbol") or "").strip()]
    if not symbols:
        _SECTOR_SHORT_FACT_CACHE[cache_key] = []
        return []
    by_symbol = {str(entity.get("symbol") or "").upper(): entity for entity in entities}
    facts: list[dict[str, Any]] = []
    for row in _latest_short_interest(_finra_short_interest_rows(symbols), symbols):
        facts.append(_short_fact_from_row("short_interest", "consolidatedShortInterest", row, by_symbol, generated_at))
    for row in _latest_short_volume(_finra_short_volume_rows(symbols), symbols):
        facts.append(_short_fact_from_row("short_volume", "regShoDaily", row, by_symbol, generated_at))
    facts = [
        fact
        for fact in facts
        if fact["freshness"] != "stale"
    ][:12]
    _SECTOR_SHORT_FACT_CACHE[cache_key] = facts
    return facts


def _short_fact_from_row(
    fact_type: str,
    dataset: str,
    row: dict[str, Any],
    by_symbol: dict[str, dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any]:
    symbol = str(row["symbol"]).upper()
    entity = by_symbol.get(symbol, {})
    as_of_date = str(row["date"])
    value = float(row["value"])
    observed_key = _short_fact_observation_key(dataset, symbol, as_of_date, value)
    source_url = (
        "https://www.finra.org/finra-data/browse-catalog/equity-short-interest"
        if fact_type == "short_interest"
        else "https://developer.finra.org/docs/api-explorer/query_api-equity-reg_sho_daily_short_sale_volume"
    )
    caveat = (
        "Open short positions, not daily short-sale volume."
        if fact_type == "short_interest"
        else "Daily short-sale transaction flow, not outstanding short interest."
    )
    return {
        "id": f"{fact_type}_{_symbol_route_key(symbol)}_{as_of_date}",
        "entity_id": str(entity.get("entity_id") or symbol.lower()),
        "symbol": symbol,
        "fact_type": fact_type,
        "dataset": dataset,
        "as_of_date": as_of_date,
        "retrieved_at": generated_at.isoformat().replace("+00:00", "Z"),
        "last_attempted_at": generated_at.isoformat().replace("+00:00", "Z"),
        "attempt_status": "ok",
        "value": value,
        "unit": "shares",
        "source": "FINRA",
        "source_url": source_url,
        "provider_observation_key": observed_key,
        "freshness": _short_fact_freshness(fact_type, as_of_date, generated_at),
        "caveat": caveat,
    }


def _write_reference_entity_snapshots(
    manifest: dict[str, Any],
    locale: str,
    generated_at: datetime,
    stale_after: datetime,
    hard_expires_at: datetime,
    news_items: list[dict[str, Any]],
) -> None:
    references = [entity for entity in _tracked_entity_records() if str(entity.get("route_kind") or "") == "reference_entity"]
    for entity in references:
        route_key = str(entity.get("route_key") or _symbol_route_key(str(entity.get("symbol") or "")))
        symbol = str(entity.get("symbol") or route_key).upper()
        entity_ref = _tracked_entity_ref(entity, locale, generated_at)
        related_symbols = {str(value).upper() for value in entity.get("related_symbols", []) if isinstance(value, str)}
        latest_news = [
            item
            for item in news_items
            if any(str(ticker.get("symbol") or "").upper() == symbol for ticker in item.get("tickers", []))
        ][:6]
        related = [
            _tracked_entity_ref(candidate, locale, generated_at)
            for candidate in _tracked_entity_records()
            if str(candidate.get("symbol") or "").upper() in related_symbols
        ][:8]
        source_links = []
        for source in entity.get("sources", []) if isinstance(entity.get("sources"), list) else []:
            if not isinstance(source, dict):
                continue
            url = str(source.get("feed_url") or source.get("base_url") or "")
            if url.startswith("http"):
                source_links.append(
                    {
                        "label": str(source.get("source_name") or source.get("source_key") or "source"),
                        "url": url,
                        "source_key": str(source.get("source_key") or "tracked_entity_registry"),
                        "policy_version": 1,
                    }
                )
        _write(
            manifest,
            f"entity_{route_key}",
            locale,
            ["entities", f"{route_key}.json"],
            _envelope(
                locale,
                generated_at,
                stale_after,
                hard_expires_at,
                "reference_entity",
                route_key,
                {
                    "entity": entity_ref,
                    "summary": _t(
                        locale,
                        f"{entity_ref['name']} is tracked as a reference entity. It may be private or non-tradable, so market-price widgets are not shown.",
                        f"{entity_ref['name']}은 참고 엔티티로 추적됩니다. 비상장 또는 비거래 대상일 수 있어 시장가격 위젯은 표시하지 않습니다.",
                    ),
                    "source_links": source_links,
                    "latest_news": latest_news,
                    "ticker_calendar_items": _ticker_calendar_items_for_sector(str(entity_ref["sector_keys"][0]) if entity_ref["sector_keys"] else "", locale, latest_news, generated_at),
                    "related_entities": related,
                    "caveats": [
                        _t(locale, "Reference entities do not imply a tradeable public security.", "참고 엔티티는 거래 가능한 공개 증권을 의미하지 않습니다."),
                        _t(locale, "Only source-linked public updates are shown.", "출처 연결 공개 업데이트만 표시합니다."),
                    ],
                    "freshness": entity_ref["freshness"],
                },
            ),
        )


def _write_fund_portfolio_snapshots(
    manifest: dict[str, Any],
    locale: str,
    generated_at: datetime,
    stale_after: datetime,
    hard_expires_at: datetime,
) -> None:
    for fund_key, config in FUND_PORTFOLIOS.items():
        portfolio = _sec_13f_portfolio(fund_key)
        holdings = list(portfolio.get("holdings", [])) if portfolio else []
        top_equity = list(portfolio.get("top_equity_holdings", [])) if portfolio else []
        options = list(portfolio.get("option_holdings", [])) if portfolio else []
        equity_holdings = [holding for holding in holdings if holding.get("holding_kind") == "stock"]
        total_value = sum(float(holding.get("value_usd") or 0) for holding in holdings)
        equity_value = sum(float(holding.get("value_usd") or 0) for holding in equity_holdings)
        option_value = sum(float(holding.get("value_usd") or 0) for holding in options)
        filing = portfolio.get("filing") if portfolio else None
        freshness = "fresh" if filing and _is_filing_recent(str(filing.get("filed_at") or ""), generated_at, max_age_days=120) else "watch"
        _write(
            manifest,
            f"fund_portfolio_{fund_key}",
            locale,
            ["funds", f"{fund_key}.json"],
            _envelope(
                locale,
                generated_at,
                stale_after,
                hard_expires_at,
                "fund_portfolio",
                fund_key,
                {
                    "fund_key": fund_key,
                    "display_name": _t(locale, str(config["display_name"]), str(config["display_name_ko"])),
                    "manager_name": str(config["manager_name"]),
                    "fund_name": str(config["fund_name"]),
                    "cik": str(config["cik"]),
                    "generated_label": generated_at.isoformat().replace("+00:00", "Z"),
                    "source_url": str(config["source_url"]),
                    "filing": filing,
                    "summary_metrics": {
                        "total_reported_value_usd": round(total_value),
                        "long_equity_value_usd": round(equity_value),
                        "option_notional_value_usd": round(option_value),
                        "holding_count": len(holdings),
                        "equity_holding_count": len(equity_holdings),
                        "option_holding_count": len(options),
                    },
                    "holdings": holdings,
                    "top_equity_holdings": top_equity,
                    "option_holdings": options,
                    "caveats": [
                        _t(locale, "SEC 13F is quarterly and delayed; it is not a real-time portfolio feed.", "SEC 13F는 분기별 지연 공시이며 실시간 포트폴리오 피드가 아닙니다."),
                        _t(locale, "13F excludes cash, many shorts, most non-U.S. holdings, and positions below reporting scope.", "13F는 현금, 다수의 숏, 대부분의 비미국 보유, 보고 범위 밖 포지션을 제외합니다."),
                        _t(locale, "Options are shown as disclosed put/call rows and should not be treated as simple long equity exposure.", "옵션은 공시된 풋/콜 행으로 표시되며 단순 롱 주식 노출로 해석하면 안 됩니다."),
                        _t(locale, "Ticker mapping comes from a maintained CUSIP override file; unmapped rows remain visible by issuer and CUSIP.", "티커 매핑은 유지관리되는 CUSIP 오버라이드 파일을 사용하며 미매핑 행은 발행사와 CUSIP로 표시합니다."),
                    ],
                    "freshness": freshness,
                    "source_strength": "SEC EDGAR 13F XML",
                },
            ),
        )


def _is_filing_recent(date_text: str, generated_at: datetime, *, max_age_days: int) -> bool:
    try:
        filed_at = datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return timedelta(0) <= generated_at - filed_at <= timedelta(days=max_age_days)


def _sector_tile(key: str, locale: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    sector = SECTORS[key]
    count = sum(1 for event in events if key in event["sector_keys"])
    tracked_count = len(_tracked_entities_for_sector(key))
    return {
        "key": key,
        "name": sector[locale],
        "summary": _t(locale, f"Monitoring {tracked_count} registry-backed entities with source-linked sector events.", f"레지스트리 기반 엔티티 {tracked_count}개를 출처 연결 섹터 이벤트와 함께 모니터링합니다."),
        "source_strength": "tracked_entity_registry",
        "freshness": "fresh",
        "monitored_count": tracked_count,
        "event_count": count,
    }


def _sector_page(
    key: str,
    locale: str,
    events: list[dict[str, Any]],
    calendar: list[dict[str, Any]],
    news_items: list[dict[str, Any]],
    generated_at: datetime,
) -> dict[str, Any]:
    sector = SECTORS[key]
    macro_event_types = {"central_bank_calendar", "macro_calendar"}
    sector_events = [
        event
        for event in events
        if key in event["sector_keys"] and event.get("event_type") not in macro_event_types
    ]
    tracked_entities = [_tracked_entity_ref(entity, locale, generated_at) for entity in _tracked_entities_for_sector(key)]
    sector_news = _sector_news_items(key, news_items)
    ticker_calendar_items = _ticker_calendar_items_for_sector(key, locale, sector_news, generated_at)
    short_facts = _sector_short_facts(key, generated_at)
    instrument_labels = [
        _t(locale, f"{entity['display_symbol']} source-linked reference", f"{entity['display_symbol']} 출처 연결 참고")
        for entity in tracked_entities
        if entity["route_kind"] == "ticker"
    ][:8]
    indicators = _sector_reference_indicators(key, locale, generated_at)
    return {
        "key": key,
        "name": sector[locale],
        "overview": _t(locale, f"{sector['en']} coverage is now generated from the canonical tracked-entity registry, with ticker-specific news, catalysts, and short facts separated from macro calendars.", f"{sector['ko']} 커버리지는 표준 추적 엔티티 레지스트리에서 생성되며 티커별 뉴스, 촉매, 공매도 사실을 거시 일정과 분리합니다."),
        "tracked_entities": tracked_entities,
        "monitored_entities": [entity["name"] for entity in tracked_entities],
        "monitored_instruments": instrument_labels,
        "country_region_exposure": sector["exposure"],
        "recent_events": sector_events,
        "upcoming_calendar_items": [],
        "ticker_calendar_items": ticker_calendar_items,
        "sector_news": sector_news,
        "sector_short_facts": short_facts,
        "macro_geopolitical_drivers": sector[f"drivers_{locale}"],
        "reference_indicators": indicators,
        "scenario_baskets": [_scenario_summary(key2, locale) for key2 in SCENARIOS if key == "semiconductors" or key2 != "asia-semiconductor-risk"],
        "risks_and_caveats": [
            _t(locale, "Coverage is explicit; unsupported data remains labeled rather than inferred.", "지원 범위는 명시되며 미지원 데이터는 추론하지 않고 라벨링합니다."),
            _t(locale, "Market data is delayed/reference unless terms permit realtime public redistribution.", "시장 데이터는 조건상 실시간 공개 재배포가 허용되지 않는 한 지연/참조입니다."),
            _t(locale, "Scenario baskets are research watchlists, not personalized allocation advice.", "시나리오 바스켓은 리서치 워치리스트이며 개인화 배분 조언이 아닙니다."),
        ],
        "freshness": "fresh",
        "source_strength": "tracked_registry_and_source_backed_facts",
    }


def _sector_reference_indicators(key: str, locale: str, generated_at: datetime) -> list[dict[str, Any]]:
    macro_tiles = _macro_tiles(locale, generated_at)
    preferred: dict[str, tuple[str, ...]] = {
        "oil-energy": ("wti_crude", "gold_futures", "copper_futures", "silver_futures"),
        "semiconductors": ("nasdaq_composite", "nasdaq_100", "kodex_200", "ewy_korea_proxy"),
        "big-tech": ("nasdaq_composite", "nasdaq_100", "vix"),
        "space": ("nasdaq_composite", "vix"),
        "quantum": ("nasdaq_composite", "vix"),
    }
    wanted = preferred.get(key, ())
    selected = [tile for tile in macro_tiles if tile["key"] in wanted]
    return selected[:4]


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

    if _env_has(env, "FRED_API_KEY"):
        fred_status, fred_warning = "ready", "FRED is reference-only; do not use it for intraday or time-sensitive market pulse tiles"
    else:
        fred_status, fred_warning = "missing_credentials", "FRED_API_KEY only enables non-realtime reference series"
    bls_status, bls_warning = status_for("BLS_API_KEY", "BLS_API_KEY enables higher-limit BLS ingest")
    eia_status, eia_warning = status_for("EIA_API_KEY", "EIA_API_KEY required for live ingest")
    sec_user_agent = env.get("SEC_USER_AGENT", "")
    sec_status = "ready" if "@" in sec_user_agent and "contact@example.com" not in sec_user_agent else "degraded"
    sec_warning = None if sec_status == "ready" else "SEC_USER_AGENT must contain a real contact in production"
    twelve_status, twelve_warning = status_for("TWELVE_DATA_API_KEY", "TWELVE_DATA_API_KEY enables sparse equity/FX fallback checks; free quota is too small for broad market-pulse polling, so snapshots throttle it to at most one request every 10 seconds when allowlisted")
    alpha_status, alpha_warning = status_for("ALPHA_VANTAGE_API_KEY", "ALPHA_VANTAGE_API_KEY enables portfolio history fallback")
    fmp_status, fmp_warning = status_for("FMP_API_KEY", "FMP_API_KEY enables EOD/fundamental fallback")
    finnhub_status, finnhub_warning = status_for("FINNHUB_API_KEY", "FINNHUB_API_KEY enables current US equity quote probes with conservative throttling; public display requires MARKET_PULSE_PUBLIC_PROVIDER_ALLOWLIST=finnhub after source-policy approval")
    nasdaq_status, nasdaq_warning = status_for("NASDAQ_DATA_LINK_API_KEY", "NASDAQ_DATA_LINK_API_KEY enables future Nasdaq Data Link datasets")
    if any(_env_has(env, key) for key in ("DATA_GO_KR_SERVICE_KEY", "DATA_GO_KR_API_KEY", "PUBLIC_DATA_API_KEY", "KOREA_PUBLIC_DATA_API_KEY")):
        data_go_status, data_go_warning = "ready", None
    else:
        data_go_status, data_go_warning = (
            "missing_credentials",
            "DATA_GO_KR_SERVICE_KEY or alias enables official Korea public-data portal market-data fallbacks",
        )
    if any(_env_has(env, key) for key in ("KRX_OPEN_API_AUTH_KEY", "KRX_AUTH_KEY", "KRX_API_KEY")):
        krx_warning = _krx_recent_error(KRX_INDEX_DAILY_PATH, datetime.now(timezone.utc))
        if krx_warning:
            krx_status = "degraded"
        else:
            krx_probe_date = _recent_krx_dates(datetime.now(timezone.utc))[0]
            krx_probe_rows = _krx_rows(KRX_INDEX_DAILY_PATH, krx_probe_date)
            krx_warning = _krx_recent_error(KRX_INDEX_DAILY_PATH, datetime.now(timezone.utc))
            if krx_warning:
                krx_status = "degraded"
            elif krx_probe_rows:
                krx_status = "ready"
            else:
                krx_status = "degraded"
                krx_warning = "KRX key is configured, but the index daily-trading probe returned no rows"
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
    nvidia_status, nvidia_warning = status_for(("NVIDIA_NIM_API_KEY", "NVIDIA_API_KEY"), "NVIDIA_NIM_API_KEY or NVIDIA_API_KEY optional; NVIDIA NIM public facts only, with zero paid overflow and normal LLM hard-limit accounting")
    hf_status, hf_warning = status_for("HF_TOKEN", "HF_TOKEN optional; public facts only")

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
        ("krx_open_api", "official_api", krx_status, "FREE_ONLY", krx_warning or "Official Korea Exchange data is preferred when authorized; fall back to delayed public quotes while KRX service approval is unavailable"),
        ("data_go_kr", "official_api", data_go_status, "FREE_ONLY", data_go_warning),
        ("yahoo_finance_delayed_quote", "market_data", "ready", "FREE_ONLY", "Public delayed quote fallback for time-sensitive tiles when official/FRED series are stale; throttled and treated as not guaranteed realtime tape"),
        ("stooq_delayed_quote", "market_data", "ready", "FREE_ONLY", "Public delayed quote fallback for indexes/futures; selected only when fresher than Yahoo and throttled as an unofficial public feed"),
        ("treasury_xml_feed", "official_xml", "ready", "FREE_ONLY", None),
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
        ("nvidia_nim", "llm_provider", nvidia_status, "FREE_ONLY", nvidia_warning),
        ("huggingface", "llm_provider", hf_status, "FREE_ONLY", hf_warning),
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
