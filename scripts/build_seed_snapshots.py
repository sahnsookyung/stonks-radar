from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = ROOT / "apps" / "web" / "public" / "public"
VERSION = 1
LOCALES = ["en", "ko"]

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
                    "macro_tiles": _macro_tiles(locale, generated_at),
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
            "why_it_matters": _t(locale, "Calendar visibility reduces silent unsupported coverage and makes stale policy data visible.", "캘린더 가시성은 미지원 범위를 숨기지 않고 오래된 정책 데이터를 드러냅니다."),
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
            "source_links": [{"label": "Federal Reserve", "url": "https://www.federalreserve.gov", "source_key": "federal_reserve", "policy_version": 1}],
            "correction_status": "none",
        },
    ]


def _calendar(locale: str) -> list[dict[str, Any]]:
    items = [
        ("cal_fomc", "FOMC policy decision", "FOMC 정책 결정", "USA", "central_bank", "2026-06-17", "America/New_York", "official_projection", "policy path not a consensus", "Federal Reserve"),
        ("cal_ecb", "ECB monetary-policy decision", "ECB 통화정책 결정", "EUROZONE", "central_bank", "2026-06-04", "Europe/Frankfurt", "official_projection", "staff projections where published", "ECB"),
        ("cal_boe", "BoE MPC decision", "영란은행 MPC 결정", "GBR", "central_bank", "2026-06-18", "Europe/London", "unknown", None, "BoE"),
        ("cal_boj", "BoJ monetary-policy meeting", "일본은행 통화정책회의", "JPN", "central_bank", "2026-06-16", "Asia/Tokyo", "unknown", None, "BoJ"),
        ("cal_bok", "Bank of Korea decision", "한국은행 기준금리 결정", "KOR", "central_bank", "2026-05-28", "Asia/Seoul", "unknown", None, "BoK"),
        ("cal_copom", "Brazil COPOM decision", "브라질 COPOM 결정", "BRA", "central_bank", "2026-06-17", "America/Sao_Paulo", "unknown", None, "BCB"),
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
    market_delay = _t(locale, "source-gated market feed", "출처 게이트 시장 피드")
    official_delay = _t(locale, "official reference", "공식 참조")

    def tile(
        key: str,
        label_en: str,
        label_ko: str,
        value: str,
        source: str,
        delay_label: str,
        freshness: str = "watch",
        unit: str | None = None,
        points: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": key,
            "label": _t(locale, label_en, label_ko),
            "value": value,
            "source": source,
            "freshness": freshness,
            "delay_label": delay_label,
            "updated_at": updated,
        }
        if unit:
            payload["unit"] = unit
        if points:
            payload["points"] = points
        return payload

    return [
        tile(
            "nasdaq_composite",
            "Nasdaq Composite",
            "나스닥 종합",
            "Pending",
            "Nasdaq / licensed market feed",
            market_delay,
            points=[{"date": "T-3", "value": 100}, {"date": "T-2", "value": 101.4}, {"date": "T-1", "value": 100.8}, {"date": "T", "value": 102.1}],
        ),
        tile(
            "nasdaq_100_futures",
            "Nasdaq 100 futures",
            "나스닥 100 선물",
            "Pending",
            "CME / licensed futures feed",
            market_delay,
            points=[{"date": "T-3", "value": 100}, {"date": "T-2", "value": 100.6}, {"date": "T-1", "value": 99.8}, {"date": "T", "value": 101.2}],
        ),
        tile(
            "kospi",
            "KOSPI",
            "코스피",
            "Pending",
            "KRX / licensed market feed",
            market_delay,
            points=[{"date": "T-3", "value": 100}, {"date": "T-2", "value": 99.7}, {"date": "T-1", "value": 100.9}, {"date": "T", "value": 101.1}],
        ),
        tile("kodex_200", "KODEX 200 ETF", "KODEX 200 ETF", "Pending", "KRX / Samsung AM", market_delay),
        tile("kospi_200_futures", "KOSPI 200 futures", "코스피 200 선물", "Pending", "KRX derivatives feed", market_delay),
        tile("wti_crude", "WTI crude oil", "WTI 원유", "Pending", "EIA / exchange reference", market_delay),
        tile("vix", "VIX", "VIX", "Pending", "Cboe / licensed market feed", market_delay),
        tile("usd_krw", "USD/KRW", "달러/원", "Pending", "BOK / licensed FX feed", market_delay),
        tile("usd_jpy", "USD/JPY", "달러/엔", "Pending", "BoJ / licensed FX feed", market_delay),
        tile("us_2y", "US Treasury 2Y", "미국 국채 2년", "Reference", "US Treasury", official_delay, "fresh", "%"),
        tile("us_3y", "US Treasury 3Y", "미국 국채 3년", "Reference", "US Treasury", official_delay, "fresh", "%"),
        tile("us_5y", "US Treasury 5Y", "미국 국채 5년", "Reference", "US Treasury", official_delay, "fresh", "%"),
        tile("us_10y", "US Treasury 10Y", "미국 국채 10년", "Reference", "US Treasury", official_delay, "fresh", "%"),
        tile("japan_policy_rate", "BoJ policy rate", "일본은행 정책금리", "Reference", "Bank of Japan", official_delay, "fresh", "%"),
        tile("japan_2y", "Japan govt 2Y", "일본 국채 2년", "Reference", "Japan MOF / BoJ", official_delay, "fresh", "%"),
        tile("japan_5y", "Japan govt 5Y", "일본 국채 5년", "Reference", "Japan MOF / BoJ", official_delay, "fresh", "%"),
        tile("japan_10y", "Japan govt 10Y", "일본 국채 10년", "Reference", "Japan MOF / BoJ", official_delay, "fresh", "%"),
    ]


def _alternative_signals(locale: str, generated_at: datetime) -> list[dict[str, Any]]:
    updated = generated_at.isoformat().replace("+00:00", "Z")

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

    return [
        {
            "key": "highest_short_interest",
            "title": _t(locale, "Highest short interest", "공매도 잔고 상위"),
            "summary": _t(
                locale,
                "Ranks securities by reported short interest once official/vendor float data is connected.",
                "공식/벤더 유통주식 데이터 연결 후 공매도 잔고 기준으로 종목을 랭킹합니다.",
            ),
            "value": _t(locale, "ranking pending", "랭킹 대기"),
            "cadence": _t(locale, "FINRA short interest is bi-monthly; ranking needs float/share data.", "FINRA 공매도 잔고는 월 2회 공개되며 랭킹에는 유통주식 데이터가 필요합니다."),
            "source": "FINRA short interest + licensed float feed",
            "source_url": "https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest",
            "freshness": "watch",
            "severity": "medium",
            "refresh_seconds": 43200,
            "items": [
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
            ],
        },
        {
            "key": "short_volume_monitor",
            "title": _t(locale, "Short volume monitor", "공매도 거래량 모니터"),
            "summary": _t(
                locale,
                "Ticker-level daily short sale volume for monitored symbols after FINRA publishes same-day files.",
                "FINRA 당일 파일 공개 후 모니터링 티커별 일별 공매도 거래량을 표시합니다.",
            ),
            "value": "DJT / TSLA / NVDA",
            "cadence": _t(locale, "Daily after FINRA posts files, no later than 6:00 p.m. ET.", "FINRA 파일 공개 후 매일 갱신, 동부시간 오후 6시 이전 공개."),
            "source": "FINRA Reg SHO Daily Short Sale Volume",
            "source_url": "https://developer.finra.org/docs/api-explorer/query_api-equity-reg_sho_daily_short_sale_volume",
            "freshness": "watch",
            "severity": "medium",
            "refresh_seconds": 900,
            "items": [
                item(
                    "short_volume_monitor",
                    "monitored",
                    "Monitored tickers",
                    "모니터링 티커",
                    "DJT, TSLA, NVDA",
                    "Configurable via SHORT_VOLUME_MONITORED_TICKERS.",
                    "SHORT_VOLUME_MONITORED_TICKERS로 변경 가능합니다.",
                    "configuration",
                    "medium",
                    "watch",
                )
            ],
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
                item("short_research_reports", "spruce_point", "Spruce Point", "스프루스 포인트", "active watch", "Public forensic short research source.", "공개 포렌식 숏 리서치 출처입니다.", "Spruce Point", "medium", "watch", "https://www.sprucepointcap.com/"),
                item("short_research_reports", "kerrisdale", "Kerrisdale Capital", "케리스데일 캐피털", "active watch", "Publishes short and long research letters.", "롱/숏 리서치 레터를 공개합니다.", "Kerrisdale", "medium", "watch", "https://www.kerrisdalecap.com/"),
                item("short_research_reports", "culper", "Culper Research", "컬퍼 리서치", "active watch", "Public short research publisher.", "공개 숏 리서치 발행사입니다.", "Culper", "medium", "watch", "https://culperresearch.com/"),
                item("short_research_reports", "blue_orca", "Blue Orca Capital", "블루 오르카 캐피털", "active watch", "Known for public short reports.", "공개 숏 보고서로 알려져 있습니다.", "Blue Orca", "medium", "watch", "https://www.blueorcacapital.com/"),
                item("short_research_reports", "grizzly", "Grizzly Research", "그리즐리 리서치", "active watch", "Public short research source.", "공개 숏 리서치 출처입니다.", "Grizzly", "medium", "watch", "https://grizzlyreports.com/"),
            ],
        },
        {
            "key": "pentagon_pizza_index",
            "title": _t(locale, "Pentagon pizza index", "펜타곤 피자 지수"),
            "summary": _t(
                locale,
                "OSINT-style activity monitor; useful as weak context, never a standalone market signal.",
                "OSINT식 활동 모니터이며 단독 시장 신호가 아닌 약한 맥락 신호로만 사용합니다.",
            ),
            "value": _t(locale, "external live source", "외부 라이브 출처"),
            "cadence": _t(locale, "5-minute polling target; weak-source label required.", "5분 폴링 목표; 약한 출처 라벨 필수."),
            "source": "Pentagon.Pizza",
            "source_url": "https://pentagon.pizza/",
            "freshness": "watch",
            "severity": "low",
            "refresh_seconds": 300,
            "items": [
                item("pentagon_pizza_index", "method", "Weak OSINT context", "약한 OSINT 맥락", "watch only", "Collate with geopolitical news; do not publish as a causal claim.", "지정학 뉴스와 함께 보되 인과 주장으로 공개하지 않습니다.", "source policy", "low", "watch", "https://pentagon.pizza/")
            ],
        },
        {
            "key": "trump_filings",
            "title": _t(locale, "Trump-family filings", "트럼프 일가 공시"),
            "summary": _t(
                locale,
                "Monitors public SEC/ethics filings for named entities; family-office 13F scope must be explicitly resolved.",
                "지정 엔티티의 SEC/윤리 공시를 추적하며 패밀리오피스 13F 범위는 명시적으로 확정해야 합니다.",
            ),
            "value": _t(locale, "entity resolution required", "엔티티 확정 필요"),
            "cadence": _t(locale, "SEC polling every 15 minutes after entity list is approved.", "엔티티 목록 승인 후 SEC를 15분 간격으로 확인합니다."),
            "source": "SEC EDGAR / OGE disclosures",
            "source_url": "https://www.sec.gov/search-filings",
            "freshness": "watch",
            "severity": "medium",
            "refresh_seconds": 900,
            "items": [
                item("trump_filings", "djt", "Trump Media & Technology Group", "트럼프 미디어", "SEC monitor", "Track DJT issuer filings and insider Forms 3/4/5.", "DJT 발행사 공시와 내부자 Form 3/4/5를 추적합니다.", "SEC EDGAR", "medium", "watch", "https://www.sec.gov/edgar/browse/?CIK=1849635"),
                item("trump_filings", "trust", "Donald J. Trump Revocable Trust", "도널드 J. 트럼프 취소가능 신탁", "SEC monitor", "Track beneficial-ownership filings where present; this is not automatically a 13F manager.", "존재하는 수익소유 공시를 추적합니다. 자동으로 13F 운용사라는 뜻은 아닙니다.", "SEC EDGAR", "medium", "watch"),
            ],
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
    providers = [
        ("fred", "official_api", "missing_credentials", "FREE_ONLY", "FRED_API_KEY required for live ingest"),
        ("bls", "official_api", "ready", "FREE_ONLY", None),
        ("eia", "official_api", "missing_credentials", "FREE_ONLY", "EIA_API_KEY required for live ingest"),
        ("sec_edgar", "filing", "ready", "FREE_ONLY", "SEC_USER_AGENT must contain contact in production"),
        ("twelve_data", "market_data", "missing_credentials", "FREE_ONLY", "TWELVE_DATA_API_KEY enables portfolio history primary"),
        ("alpha_vantage", "market_data", "missing_credentials", "FREE_ONLY", "ALPHA_VANTAGE_API_KEY enables portfolio history fallback"),
        ("fmp", "market_data", "missing_credentials", "FREE_ONLY", "FMP_API_KEY enables EOD/fundamental fallback"),
        (
            "finra",
            "official_api",
            "missing_credentials",
            "FREE_ONLY",
            "FINRA_API_TOKEN required for short interest and Reg SHO short volume ingest",
        ),
        ("pentagon_pizza", "weak_osint", "degraded", "FREE_ONLY", "Weak OSINT only; cannot publish standalone high-confidence events"),
        ("public_short_research", "public_web", "degraded", "FREE_ONLY", "Public short-report monitors need source-specific parser review"),
        ("gemini", "llm_provider", "missing_credentials", "FREE_ONLY", "GEMINI_API_KEY optional; public facts only"),
        ("groq", "llm_provider", "missing_credentials", "FREE_ONLY", "GROQ_API_KEY optional; public facts only"),
        ("local", "llm_provider", "ready", "LOCAL_ONLY", "LOCAL_LLM_BASE_URL used for private research"),
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
