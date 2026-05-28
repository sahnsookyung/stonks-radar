from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Iterable
from urllib.parse import urlparse

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from frw_api.services.news.taxonomy import TRUST_TIERS

SAFE_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


def news_symbol_key(symbol: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", symbol.upper()).strip("_")


def news_snapshot_object_keys(event_ids: Iterable[str], symbols: Iterable[str], regions: Iterable[str], topics: Iterable[str]) -> list[str]:
    keys = ["news_index"]
    keys.extend(f"news_event_{event_id}" for event_id in event_ids)
    keys.extend(f"news_ticker_{news_symbol_key(symbol)}" for symbol in symbols)
    keys.extend(f"news_region_{region}" for region in regions)
    keys.extend(f"news_topic_{topic}" for topic in topics)
    return keys


def build_reviewed_news_snapshots(db: Session, *, locale: str, generated_label: str) -> dict[str, Any]:
    events = _reviewed_events(db, locale=locale)
    if not events:
        return {}
    event_ids = [event["id"] for event in events]
    tickers = _event_tickers(db, event_ids)
    regions = _event_regions(db, event_ids)
    topics = _event_topics(db, event_ids)
    sources = _event_sources(db, event_ids)
    events = [event for event in events if sources.get(event["id"])]
    if not events:
        return {}
    list_items = [
        _event_list_item(
            event,
            tickers=tickers.get(event["id"], []),
            regions=regions.get(event["id"], []),
            topics=topics.get(event["id"], []),
            sources=sources.get(event["id"], []),
        )
        for event in events
    ]
    by_id = {item["id"]: item for item in list_items}
    return {
        "index": {
            "generated_label": generated_label,
            "filters": _filters(list_items),
            "events": list_items,
        },
        "events": {
            event_id: _event_detail(by_id[event_id], list_items, locale=locale)
            for event_id in by_id
        },
        "tickers": _grouped_snapshot(
            list_items,
            group_fn=lambda item: [ticker["symbol"] for ticker in item["tickers"]],
            generated_label=generated_label,
            make_data=lambda key, grouped: {
                "symbol": key,
                "name": _ticker_name(grouped, key),
                "generated_label": generated_label,
                "summary": _localized(locale, f"{len(grouped)} reviewed event clusters mention {key}.", f"{key} 관련 검토 이벤트 {len(grouped)}건."),
                "events": grouped,
            },
            key_fn=news_symbol_key,
        ),
        "regions": _grouped_snapshot(
            list_items,
            group_fn=lambda item: [region["key"] for region in item["regions"]],
            generated_label=generated_label,
            make_data=lambda key, grouped: {
                "key": key,
                "name": _region_name(key),
                "generated_label": generated_label,
                "regional_brief": _localized(locale, f"{len(grouped)} reviewed event clusters are linked to {_region_name(key)}.", f"{_region_name(key)} 관련 검토 이벤트 {len(grouped)}건."),
                "events": grouped,
            },
        ),
        "topics": _grouped_snapshot(
            list_items,
            group_fn=lambda item: [topic["key"] for topic in item["topics"]],
            generated_label=generated_label,
            make_data=lambda key, grouped: {
                "key": key,
                "label": _topic_label(key),
                "generated_label": generated_label,
                "topic_brief": _localized(locale, f"{len(grouped)} reviewed event clusters are tagged {_topic_label(key)}.", f"{_topic_label(key)} 주제 검토 이벤트 {len(grouped)}건."),
                "events": grouped,
            },
        ),
    }


def _reviewed_events(db: Session, *, locale: str = "en") -> list[dict[str, Any]]:
    try:
        rows = db.execute(
            text(
                """
                select id, canonical_title, event_type, first_seen_at, last_seen_at,
                       coalesce(published_at, last_seen_at) as published_at,
                       severity, confidence, breaking_score, trust_score, novelty_score,
                       source_count, summary_json
                from (
                  select c.id, c.canonical_title, c.event_type, c.first_seen_at, c.last_seen_at,
                         c.published_at, c.severity, c.confidence, c.breaking_score,
                         c.trust_score, c.novelty_score, c.source_count, s.summary_json
                  from news_event_cluster c
                  join lateral (
                    select summary_json
                    from news_event_summary s
                    where s.event_id = c.id
                      and s.locale = :locale
                      and s.status = 'succeeded'
                      and s.public_allowed = true
                      and s.review_state in ('approved','reviewed','published')
                    order by s.updated_at desc
                    limit 1
                  ) s on true
                  where c.status = 'active'
                    and c.review_state in ('approved', 'reviewed', 'published', 'auto_reviewed')
                ) reviewed
                order by last_seen_at desc
                limit 200
                """
            ),
            {"locale": locale},
        ).mappings().all()
    except SQLAlchemyError:
        return []
    return [dict(row) for row in rows if SAFE_EVENT_ID_RE.fullmatch(str(row["id"]))]


def _event_tickers(db: Session, event_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not event_ids:
        return {}
    rows = db.execute(
        text(
            """
            select event_id, entity_key, relationship, confidence
            from news_event_entity
            where event_id in :event_ids
              and entity_type in ('ticker', 'security', 'company')
            order by confidence desc
            """
        ).bindparams(bindparam("event_ids", expanding=True)),
        {"event_ids": event_ids},
    ).mappings().all()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        symbol = str(row["entity_key"]).upper()
        grouped[str(row["event_id"])].append(
            {
                "symbol": symbol,
                "name": symbol,
                "relationship": _ticker_relationship(str(row["relationship"])),
                "confidence": _clamp_float(row["confidence"]),
            }
        )
    return grouped


def _event_regions(db: Session, event_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not event_ids:
        return {}
    rows = db.execute(
        text(
            """
            select event_id, region_key, relation, confidence
            from news_event_region
            where event_id in :event_ids
            order by confidence desc
            """
        ).bindparams(bindparam("event_ids", expanding=True)),
        {"event_ids": event_ids},
    ).mappings().all()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(row["region_key"])
        grouped[str(row["event_id"])].append(
            {
                "key": key,
                "name": _region_name(key),
                "relation": str(row["relation"]),
                "confidence": _clamp_float(row["confidence"]),
            }
        )
    return grouped


def _event_topics(db: Session, event_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not event_ids:
        return {}
    rows = db.execute(
        text(
            """
            select event_id, topic_key, confidence
            from news_event_topic
            where event_id in :event_ids
            order by confidence desc
            """
        ).bindparams(bindparam("event_ids", expanding=True)),
        {"event_ids": event_ids},
    ).mappings().all()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(row["topic_key"])
        grouped[str(row["event_id"])].append(
            {
                "key": key,
                "label": _topic_label(key),
                "confidence": _clamp_float(row["confidence"]),
            }
        )
    return grouped


def _event_sources(db: Session, event_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not event_ids:
        return {}
    rows = db.execute(
        text(
            """
            select ed.event_id,
                   coalesce(ds.display_name, d.publisher, ds.source_key, 'source') as label,
                   coalesce(d.canonical_url, d.original_url, '') as url,
                   coalesce(ds.source_key, d.publisher, 'unknown') as source_key,
                   coalesce(d.title, 'Source document') as title,
                   coalesce(d.source_published_at, d.fetched_at, d.created_at) as published_at,
                   coalesce(d.metadata->>'trust_tier', 'T3_REVIEWED_PUBLIC_SOURCE') as trust_tier,
                   ed.is_primary_source
            from news_event_document ed
            join source_document d on d.id = ed.document_id
            left join data_source ds on ds.id = d.source_id
            where ed.event_id in :event_ids
              and d.public_allowed = true
            order by ed.is_primary_source desc, published_at desc
            """
        ).bindparams(bindparam("event_ids", expanding=True)),
        {"event_ids": event_ids},
    ).mappings().all()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        trust_tier = str(row["trust_tier"])
        if trust_tier not in TRUST_TIERS or trust_tier in {"T5_UNREVIEWED", "T6_BLOCKED"}:
            continue
        url = str(row["url"] or "")
        if not _safe_http_url(url):
            continue
        grouped[str(row["event_id"])].append(
            {
                "label": str(row["label"]),
                "url": url,
                "source_key": str(row["source_key"]),
                "policy_version": 1,
                "title": str(row["title"]),
                "published_at": _iso(row["published_at"]),
                "trust_tier": trust_tier,
                "is_primary": bool(row["is_primary_source"]),
            }
        )
    return grouped


def _event_list_item(
    event: dict[str, Any],
    *,
    tickers: list[dict[str, Any]],
    regions: list[dict[str, Any]],
    topics: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    title = str(event["canonical_title"])
    summary_json = event.get("summary_json") or {}
    if not isinstance(summary_json, dict):
        summary_json = {}
    return {
        "id": str(event["id"]),
        "title": title,
        "summary": str(summary_json.get("one_sentence_summary") or f"Reviewed event cluster: {title}"),
        "event_type": str(event["event_type"]),
        "first_seen_at": _iso(event["first_seen_at"]),
        "last_seen_at": _iso(event["last_seen_at"]),
        "published_at": _iso(event["published_at"]),
        "freshness": "fresh",
        "severity": _severity(event["severity"]),
        "confidence": _clamp_float(event["confidence"]),
        "breaking_score": _clamp_int(event["breaking_score"]),
        "trust_score": _clamp_int(event["trust_score"]),
        "source_count": len(sources),
        "tickers": tickers,
        "regions": regions,
        "topics": topics,
        "market_direction": str((summary_json.get("market_relevance") or {}).get("direction") or "unclear"),
        "source_links": sources,
        "summary_json": summary_json,
    }


def _event_detail(item: dict[str, Any], all_items: list[dict[str, Any]], *, locale: str) -> dict[str, Any]:
    related = [candidate for candidate in all_items if candidate["id"] != item["id"]][:5]
    source_count = item["source_count"]
    return {
        **item,
        "one_sentence_summary": item["summary"],
        "what_happened": _summary_list(item, "what_happened") or [_localized(locale, item["summary"], item["summary"])],
        "why_it_matters": _summary_list(item, "why_it_matters") or [
            _localized(
                locale,
                "The event is connected to tracked tickers, regions, or macro topics and has passed source-policy review.",
                "이 이벤트는 추적 중인 티커, 지역 또는 거시 주제와 연결되어 있으며 출처 정책 검토를 통과했습니다.",
            )
        ],
        "known_facts": _summary_list(item, "known_facts") or [
            _localized(locale, f"{source_count} public source(s) are linked to this event.", f"공개 출처 {source_count}개가 이 이벤트에 연결되어 있습니다.")
        ],
        "uncertainties": _summary_list(item, "uncertainties") or [
            _localized(
                locale,
                "Market impact is contextual and should not be interpreted as a buy/sell recommendation.",
                "시장 영향은 맥락 정보이며 매수/매도 추천으로 해석하면 안 됩니다.",
            )
        ],
        "conflicting_reports": [],
        "market_relevance": {
            "direction": item["market_direction"],
            "confidence": "medium" if item["confidence"] >= 0.7 else "low",
            "reasoning": _localized(
                locale,
                "Direction is kept conservative unless the source evidence explicitly supports a directional market claim.",
                "출처 근거가 명시적으로 방향성 시장 주장을 뒷받침하지 않는 한 방향 판단은 보수적으로 유지됩니다.",
            ),
        },
        "related_events": related,
        "methodology": _localized(
            locale,
            "Reviewed database events are projected into public snapshots after source-policy, trust-tier, and raw-text safety checks.",
            "검토된 데이터베이스 이벤트는 출처 정책, 신뢰 등급, 원문 안전성 검사를 거쳐 공개 스냅샷으로 변환됩니다.",
        ),
        "disclaimer": _localized(
            locale,
            "News summaries are source-linked research context, not personalized investment advice.",
            "뉴스 요약은 출처 연결 리서치 맥락이며 개인화된 투자 조언이 아닙니다.",
        ),
    }


def _filters(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    regions = Counter(region["key"] for item in items for region in item["regions"])
    topics = Counter(topic["key"] for item in items for topic in item["topics"])
    tickers = Counter(ticker["symbol"] for item in items for ticker in item["tickers"])
    trusts = Counter(source["trust_tier"] for item in items for source in item["source_links"])
    return {
        "regions": [{"key": key, "label": _region_name(key), "count": count} for key, count in sorted(regions.items())],
        "topics": [{"key": key, "label": _topic_label(key), "count": count} for key, count in sorted(topics.items())],
        "tickers": [{"key": key, "label": key, "count": count} for key, count in sorted(tickers.items())],
        "trust_tiers": [{"key": key, "label": key, "count": count} for key, count in sorted(trusts.items())],
    }


def _summary_list(item: dict[str, Any], key: str) -> list[str]:
    summary_json = item.get("summary_json") or {}
    values = summary_json.get(key) if isinstance(summary_json, dict) else None
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value).strip()]


def _grouped_snapshot(
    items: list[dict[str, Any]],
    *,
    group_fn: Any,
    generated_label: str,
    make_data: Any,
    key_fn: Any | None = None,
) -> dict[str, dict[str, Any]]:
    _ = generated_label
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        for raw_key in group_fn(item):
            key = key_fn(raw_key) if key_fn else raw_key
            grouped[key].append(item)
    return {key: make_data(key, group) for key, group in grouped.items()}


def _ticker_name(items: list[dict[str, Any]], symbol: str) -> str:
    for item in items:
        for ticker in item["tickers"]:
            if news_symbol_key(ticker["symbol"]) == symbol:
                return str(ticker["name"])
    return symbol


def _ticker_relationship(value: str) -> str:
    if value in {"direct_subject", "affected_company", "competitor", "supplier", "customer", "mentioned_only"}:
        return value
    return "affected_company"


def _region_name(key: str) -> str:
    return {
        "USA": "United States",
        "KOR": "Korea",
        "JPN": "Japan",
        "BRA": "Brazil",
        "EU": "Europe",
        "CHN": "China",
        "GLOBAL": "Global",
    }.get(key, key)


def _topic_label(key: str) -> str:
    return key.replace("_", " ").title()


def _severity(value: Any) -> str:
    return str(value) if str(value) in {"low", "medium", "high", "critical"} else "medium"


def _clamp_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return max(0.0, min(1.0, number))


def _clamp_int(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    return max(0, min(100, number))


def _localized(locale: str, en: str, ko: str) -> str:
    return ko if locale == "ko" else en


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.isoformat()


def _safe_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
