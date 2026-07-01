from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from frw_api.services.news.geopolitical_registry import (
    match_geo_points,
    registry_scoring_version,
    registry_thinning_version,
    registry_version,
)
from frw_api.services.news.taxonomy import TRUST_TIERS

SAFE_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
BREAKING_MARKET_MAX_AGE = timedelta(hours=24)
BREAKING_MARKET_BREAKING_AGE = timedelta(hours=2)
BREAKING_MARKET_DEVELOPING_AGE = timedelta(hours=8)
BREAKING_MARKET_OBSERVED_MAX_AGE = timedelta(minutes=20)
BREAKING_MARKET_FUTURE_SKEW = timedelta(minutes=10)
BREAKING_MARKET_MAX_POINTS = 250
BREAKING_MARKET_MAX_JSON_BYTES = 250_000
UTC_OFFSET_SUFFIX = "+00:00"


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
        "breaking_market": _breaking_market_projection(list_items, generated_label=generated_label),
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
        url = _public_source_url(str(row["url"] or ""))
        if not url:
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
        "source_published_at": _source_published_at(sources),
        "observed_at": _iso(event["last_seen_at"]),
        "freshness": _freshness_for_event(event, sources),
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
        "ticker_implications": _ticker_implications(item),
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
        "market_relevance": _market_relevance(item, locale),
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


def _breaking_market_projection(items: list[dict[str, Any]], *, generated_label: str) -> dict[str, Any]:
    now = _parse_iso(generated_label) or datetime.now(timezone.utc)
    events: list[dict[str, Any]] = []
    for item in items:
        event = _breaking_market_event(item, now)
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
    capped_points = points[:BREAKING_MARKET_MAX_POINTS]
    capped_events = _events_for_points(events, capped_points)
    payload = _breaking_payload(
        events=capped_events,
        points=capped_points,
        total_count=total_count,
        generated_label=generated_label,
    )
    while _payload_size(payload) > BREAKING_MARKET_MAX_JSON_BYTES and payload["map_points"]:
        payload["map_points"] = payload["map_points"][:-1]
        payload["events"] = _events_for_points(events, payload["map_points"])
        payload["shown_count"] = len(payload["map_points"])
        payload["ranking_cutoff"] = _ranking_cutoff(payload["map_points"], total_count)
    return payload


def _breaking_market_event(item: dict[str, Any], now: datetime) -> dict[str, Any] | None:
    timestamps = _breaking_event_timestamps(item, now)
    if timestamps is None:
        return None
    source_published_at, observed_at = timestamps
    label = _breaking_label(item, now, source_published_at, observed_at)
    if label == "stale":
        return None
    geo_points = _breaking_geo_points(item)
    if not geo_points:
        return None
    urgency_score = _clamp_int(item.get("breaking_score"))
    trust_tier = _primary_trust_tier(item)
    citation_ids = _citation_ids(item)
    source_url = _primary_source_url(item)
    event_id = str(item["id"])
    geo_confidence = max(point["geo_confidence"] for point in geo_points)
    score_reason_codes = _breaking_score_reason_codes(item, geo_points, label)
    source_published_iso = _utc_iso_z(source_published_at)
    observed_iso = _utc_iso_z(observed_at)
    severity = _severity(item.get("severity"))
    event = {
        "event_id": event_id,
        "title": _safe_display_text(str(item.get("title") or "Untitled market event"), 180),
        "summary": _safe_display_text(str(item.get("summary") or ""), 500),
        "source_published_at": source_published_iso,
        "observed_at": observed_iso,
        "verified_at": observed_iso,
        "freshness_confidence": _freshness_confidence(now, source_published_at, observed_at),
        "urgency_score": urgency_score,
        "severity": severity,
        "trust_tier": trust_tier,
        "discovery_only": trust_tier == "T4_WEAK_SIGNAL",
        "review_state": "reviewed",
        "citation_ids": citation_ids,
        "retention_class": "metadata_only",
        "geo_points": [],
        "geo_confidence": geo_confidence,
        "score_reason_codes": score_reason_codes,
        "dedupe_key": hashlib.sha256(f"{event_id}|{source_published_iso}|{','.join(citation_ids)}".encode()).hexdigest(),
        "label": label,
        "tickers": item.get("tickers", []),
        "regions": item.get("regions", []),
        "topics": item.get("topics", []),
        "source_count": int(item.get("source_count") or 0),
    }
    if source_url:
        event["source_url"] = source_url
    event_points: list[dict[str, Any]] = []
    for point in geo_points:
        area_priority, priority_reason_codes = _area_priority(
            point,
            urgency_score=urgency_score,
            severity=severity,
            source_count=event["source_count"],
            label=label,
        )
        event_point = {
            "point_id": f"{point['point_id']}_{hashlib.sha1(event_id.encode()).hexdigest()[:8]}",
            "event_id": event_id,
            "event_ids": [event_id],
            "title": event["title"],
            "summary": event["summary"],
            "area_id": point["area_key"],
            "area_key": point["area_key"],
            "area_label": point["area_label"],
            "relation": point["relation"],
            "latitude": point["latitude"],
            "longitude": point["longitude"],
            "severity": event["severity"],
            "urgency_score": urgency_score,
            "source_published_at": source_published_iso,
            "observed_at": observed_iso,
            "source_count": event["source_count"],
            "geo_confidence": point["geo_confidence"],
            "area_priority": area_priority,
            "score_reason_codes": sorted(set(point["score_reason_codes"] + score_reason_codes + priority_reason_codes)),
        }
        if source_url:
            event_point["source_url"] = source_url
        event_points.append(event_point)
    event["geo_points"] = event_points
    return event


def _breaking_event_timestamps(item: dict[str, Any], now: datetime) -> tuple[datetime, datetime] | None:
    source_published_at = _parse_iso(str(item.get("source_published_at") or item.get("published_at") or ""))
    observed_at = _parse_iso(str(item.get("observed_at") or item.get("last_seen_at") or ""))
    if source_published_at is None or observed_at is None:
        return None
    if source_published_at - now > BREAKING_MARKET_FUTURE_SKEW or observed_at - now > BREAKING_MARKET_FUTURE_SKEW:
        return None
    age = now - source_published_at
    if age < timedelta(0) or age > BREAKING_MARKET_MAX_AGE:
        return None
    return source_published_at, observed_at


def _breaking_score_reason_codes(
    item: dict[str, Any],
    geo_points: list[dict[str, Any]],
    label: str,
) -> list[str]:
    return sorted(
        {
            *[code for point in geo_points for code in point["score_reason_codes"]],
            *_urgency_reason_codes(item, label),
        }
    )


def _utc_iso_z(value: datetime) -> str:
    return value.isoformat().replace(UTC_OFFSET_SUFFIX, "Z")


def _breaking_geo_points(item: dict[str, Any]) -> list[dict[str, Any]]:
    texts = [
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
        " ".join(str(region.get("name") or region.get("key") or "") for region in item.get("regions", [])),
        " ".join(str(topic.get("label") or topic.get("key") or "") for topic in item.get("topics", [])),
    ]
    region_keys = [str(region.get("key") or "") for region in item.get("regions", []) if isinstance(region, dict)]
    topic_keys = [str(topic.get("key") or "") for topic in item.get("topics", []) if isinstance(topic, dict)]
    return match_geo_points(texts=texts, region_keys=region_keys, topic_keys=topic_keys)


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


def _breaking_label(item: dict[str, Any], now: datetime, source_published_at: datetime, observed_at: datetime) -> str:
    urgency = _clamp_int(item.get("breaking_score"))
    published_age = now - source_published_at
    observed_age = now - observed_at
    if published_age <= BREAKING_MARKET_BREAKING_AGE and observed_age <= BREAKING_MARKET_OBSERVED_MAX_AGE and urgency >= 70:
        return "breaking"
    if published_age <= BREAKING_MARKET_DEVELOPING_AGE or urgency >= 65:
        return "developing"
    if published_age <= BREAKING_MARKET_MAX_AGE:
        return "latest"
    return "stale"


def _events_for_points(events: list[dict[str, Any]], points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    point_ids_by_event: dict[str, set[str]] = {}
    for point in points:
        point_ids_by_event.setdefault(point["event_id"], set()).add(point["point_id"])
    trimmed_events = []
    for event in events:
        allowed_point_ids = point_ids_by_event.get(event["event_id"])
        if not allowed_point_ids:
            continue
        cloned = dict(event)
        cloned["geo_points"] = [point for point in event["geo_points"] if point["point_id"] in allowed_point_ids]
        trimmed_events.append(cloned)
    return trimmed_events


def _breaking_payload(
    *,
    events: list[dict[str, Any]],
    points: list[dict[str, Any]],
    total_count: int,
    generated_label: str,
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
        "generated_at": generated_label,
    }


def _ranking_cutoff(points: list[dict[str, Any]], total_count: int) -> int | None:
    if not points or len(points) >= total_count:
        return None
    return int(points[-1]["urgency_score"])


def _payload_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())


def _freshness_confidence(now: datetime, source_published_at: datetime, observed_at: datetime) -> float:
    published_age = max(0.0, (now - source_published_at).total_seconds())
    observed_age = max(0.0, (now - observed_at).total_seconds())
    published_score = max(0.0, 1.0 - published_age / BREAKING_MARKET_MAX_AGE.total_seconds())
    observed_score = max(0.0, 1.0 - observed_age / max(1.0, BREAKING_MARKET_MAX_AGE.total_seconds()))
    return round((published_score * 0.72) + (observed_score * 0.28), 3)


def _primary_trust_tier(item: dict[str, Any]) -> str:
    links = item.get("source_links", [])
    if not isinstance(links, list) or not links:
        return "T3_REVIEWED_PUBLIC_SOURCE"
    tier = str((links[0] if isinstance(links[0], dict) else {}).get("trust_tier") or "T3_REVIEWED_PUBLIC_SOURCE")
    return tier if tier in TRUST_TIERS else "T3_REVIEWED_PUBLIC_SOURCE"


def _primary_source_url(item: dict[str, Any]) -> str:
    links = item.get("source_links", [])
    if not isinstance(links, list):
        return ""
    for link in links:
        if isinstance(link, dict):
            url = _public_source_url(str(link.get("url") or ""))
            if url:
                return url
    return ""


def _citation_ids(item: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for link in item.get("source_links", []):
        if not isinstance(link, dict):
            continue
        source_key = str(link.get("source_key") or "source")[:80]
        url = _public_source_url(str(link.get("url") or ""))
        if not url:
            continue
        ids.append(hashlib.sha1(f"{source_key}|{url}".encode()).hexdigest()[:16])
    return ids[:12]


def _urgency_reason_codes(item: dict[str, Any], label: str) -> list[str]:
    codes = [f"label_{label}"]
    if _clamp_int(item.get("breaking_score")) >= 70:
        codes.append("high_breaking_score")
    if int(item.get("source_count") or 0) > 1:
        codes.append("multi_source")
    return codes


def _safe_display_text(value: str, max_length: int) -> str:
    return re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]+", " ", value).strip()[:max_length]


def _summary_list(item: dict[str, Any], key: str) -> list[str]:
    summary_json = item.get("summary_json") or {}
    values = summary_json.get(key) if isinstance(summary_json, dict) else None
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value).strip()]


def _ticker_implications(item: dict[str, Any]) -> list[dict[str, str]]:  # NOSONAR - deterministic ticker implication extraction is kept in one pass.
    summary_json = item.get("summary_json") or {}
    values = summary_json.get("ticker_implications") if isinstance(summary_json, dict) else None
    if not isinstance(values, list):
        return []
    implications: list[dict[str, str]] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        symbol = str(value.get("symbol") or "").upper().strip()
        implication = str(value.get("implication") or "").strip()
        direction = str(value.get("direction") or "unclear").strip()
        confidence = str(value.get("confidence") or "low").strip()
        if not symbol or not implication:
            continue
        implications.append(
            {
                "symbol": symbol[:24],
                "implication": implication[:360],
                "direction": direction if direction in {"bullish", "bearish", "mixed", "unclear"} else "unclear",
                "confidence": confidence if confidence in {"low", "medium", "high"} else "low",
            }
        )
    return implications[:8]


def _market_relevance(item: dict[str, Any], locale: str) -> dict[str, str]:  # NOSONAR - bilingual relevance fallback logic is intentionally colocated.
    summary_json = item.get("summary_json") or {}
    value = summary_json.get("market_relevance") if isinstance(summary_json, dict) else None
    if isinstance(value, dict):
        direction = str(value.get("direction") or item["market_direction"])
        confidence = str(value.get("confidence") or ("medium" if item["confidence"] >= 0.7 else "low"))
        reasoning = str(value.get("reasoning") or "").strip()
        if reasoning:
            return {
                "direction": direction if direction in {"bullish", "bearish", "mixed", "unclear"} else "unclear",
                "confidence": confidence if confidence in {"low", "medium", "high"} else "low",
                "reasoning": reasoning[:500],
            }
    return {
        "direction": str(item["market_direction"]) if str(item["market_direction"]) in {"bullish", "bearish", "mixed", "unclear"} else "unclear",
        "confidence": "medium" if item["confidence"] >= 0.7 else "low",
        "reasoning": _localized(
            locale,
            "Direction is kept conservative unless the source evidence explicitly supports a directional market claim.",
            "출처 근거가 명시적으로 방향성 시장 주장을 뒷받침하지 않는 한 방향 판단은 보수적으로 유지됩니다.",
        ),
    }


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
        "CAN": "Canada",
        "KOR": "Korea",
        "JPN": "Japan",
        "BRA": "Brazil",
        "ZAF": "South Africa",
        "GBR": "United Kingdom",
        "DEU": "Germany",
        "FRA": "France",
        "ITA": "Italy",
        "MEX": "Mexico",
        "NOR": "Norway",
        "TWN": "Taiwan",
        "IRN": "Iran",
        "ISR": "Israel",
        "RUS": "Russia",
        "UKR": "Ukraine",
        "SAU": "Saudi Arabia",
        "ARE": "United Arab Emirates",
        "QAT": "Qatar",
        "IND": "India",
        "AUS": "Australia",
        "ESP": "Spain",
        "IDN": "Indonesia",
        "TUR": "Turkiye",
        "NLD": "Netherlands",
        "CHE": "Switzerland",
        "POL": "Poland",
        "BEL": "Belgium",
        "ARG": "Argentina",
        "IRL": "Ireland",
        "SWE": "Sweden",
        "SGP": "Singapore",
        "AUT": "Austria",
        "THA": "Thailand",
        "EU": "Europe",
        "CHN": "China",
        "GLOBAL": "Global",
        "HORMUZ": "Strait of Hormuz",
        "RED_SEA": "Red Sea / Bab el-Mandeb",
        "SUEZ": "Suez Canal",
        "PANAMA_CANAL": "Panama Canal",
        "TAIWAN_STRAIT": "Taiwan Strait",
        "SOUTH_CHINA_SEA": "South China Sea",
        "BLACK_SEA": "Black Sea",
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


def _public_source_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port else host
    return parsed._replace(netloc=netloc, query="", fragment="").geturl()


def _source_published_at(sources: list[dict[str, Any]]) -> str:
    timestamps = sorted(source.get("published_at", "") for source in sources if source.get("published_at"))
    return timestamps[-1] if timestamps else ""


def _freshness_for_event(event: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    timestamp = _source_published_at(sources) or _iso(event.get("published_at")) or _iso(event.get("last_seen_at"))
    parsed = _parse_iso(timestamp)
    if parsed is None:
        return "watch"
    now = datetime.now(timezone.utc)
    age_seconds = (now - parsed).total_seconds()
    if age_seconds < 0:
        return "watch"
    if age_seconds <= 24 * 60 * 60:
        return "fresh"
    if age_seconds <= 7 * 24 * 60 * 60:
        return "watch"
    return "stale"


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
