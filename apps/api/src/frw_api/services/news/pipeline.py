from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from frw_api.core.settings import get_settings
from frw_api.services.news.clusterer import cluster_documents
from frw_api.services.news.entity_matcher import EntityProfile, match_entities
from frw_api.services.news.facts import ensure_news_event_facts
from frw_api.services.news.region_classifier import classify_regions
from frw_api.services.news.scoring import breaking_score, trust_score
from frw_api.services.news.source_registry import source_registry
from frw_api.services.news.topic_classifier import classify_topics
from frw_api.services.news.watchlist import watchlist_entity_dicts


def _watchlist_entity_profile(entry: dict[str, Any]) -> EntityProfile:
    return EntityProfile(
        symbol=str(entry["symbol"]).upper(),
        legal_name=str(entry.get("legal_name") or entry["symbol"]),
        aliases=tuple(entry.get("aliases") or ()),
        official_domains=tuple(entry.get("official_domains") or ()),
        sector_terms=tuple(entry.get("sector_terms") or ()),
    )


DEFAULT_TRACKED_ENTITY_PROFILES: tuple[EntityProfile, ...] = tuple(
    _watchlist_entity_profile(entry) for entry in watchlist_entity_dicts()
)


def normalize_news_documents(db: Session, *, limit: int = 500) -> dict[str, int]:
    rows = _news_documents(db, limit=limit, require_unclassified=False)
    touched = 0
    for row in rows:
        metadata = dict(row["metadata"] or {})
        if metadata.get("news_normalized_at"):
            continue
        metadata["news_normalized_at"] = _now()
        metadata.setdefault("news_publication_note", "metadata_only_source_document")
        _update_document_metadata(db, row["id"], metadata, status="normalized")
        touched += 1
    return {"documents_seen": len(rows), "documents_normalized": touched}


def classify_news_documents(db: Session, *, limit: int = 500) -> dict[str, int]:
    rows = _news_documents(db, limit=limit, require_unclassified=True)
    classified = 0
    profiles = news_entity_profiles()
    for row in rows:
        document = _document_payload(row)
        entities = match_entities(document, profiles)
        regions = classify_regions(document)
        topics = classify_topics(document)
        metadata = dict(row["metadata"] or {})
        metadata.update(
            {
                "news_classified_at": _now(),
                "news_entities": [entity.__dict__ for entity in entities],
                "news_regions": [region.__dict__ for region in regions],
                "news_topics": [topic.__dict__ for topic in topics],
            }
        )
        _update_document_metadata(db, row["id"], metadata, status="classified")
        classified += 1
    return {"documents_seen": len(rows), "documents_classified": classified}


def cluster_news_documents(db: Session, *, limit: int = 500) -> dict[str, int]:
    rows = _classified_news_documents(db, limit=limit)
    if not rows:
        return {"documents_seen": 0, "clusters_upserted": 0, "links_upserted": 0}
    documents, rows_by_index = _documents_for_clustering(rows)
    clusters = cluster_documents(documents)
    cluster_count = 0
    link_count = 0
    for cluster in clusters:
        cluster_rows = [rows_by_index[str(document["_row_index"])] for document in cluster["documents"]]
        if not cluster_rows:
            continue
        event = _cluster_event_payload(cluster, cluster_rows)
        _upsert_news_event_cluster(db, event)
        cluster_count += 1
        link_count += _upsert_cluster_document_links(db, event, cluster_rows)
        _upsert_event_entities(db, event["id"], event["entities"])
        _upsert_event_regions(db, event["id"], event["regions"])
        _upsert_event_topics(db, event["id"], event["topics"])
    return {"documents_seen": len(rows), "clusters_upserted": cluster_count, "links_upserted": link_count}


def _documents_for_clustering(
    rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    documents = []
    rows_by_index: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        document = _document_payload(row)
        document["_row_index"] = str(index)
        documents.append(document)
        rows_by_index[str(index)] = row
    return documents, rows_by_index


def _cluster_event_payload(cluster: dict[str, Any], cluster_rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = cluster_rows[0]
    metadata_rows = [dict(row["metadata"] or {}) for row in cluster_rows]
    trust_tiers = [
        str(metadata.get("trust_tier") or "T3_REVIEWED_PUBLIC_SOURCE")
        for metadata in metadata_rows
    ]
    event_topics = _dedupe_metadata_items(metadata_rows, "news_topics", "key")
    event_regions = _dedupe_metadata_items(metadata_rows, "news_regions", "key", "relation")
    event_entities = _dedupe_metadata_items(metadata_rows, "news_entities", "symbol", "relationship")
    score = trust_score(trust_tiers)
    confidence = min(0.9, max(0.35, score / 100))
    return {
        "id": str(cluster["id"]),
        "canonical_title": str(first["title"] or "Untitled news event")[:500],
        "event_type": _event_type(event_topics),
        "first_seen_at": cluster["first_seen_at"] or _now(),
        "last_seen_at": cluster["last_seen_at"] or _now(),
        "published_at": cluster["last_seen_at"] or cluster["first_seen_at"] or _now(),
        "primary_region": event_regions[0].get("key") if event_regions else None,
        "severity": _severity(event_topics),
        "confidence": confidence,
        "breaking_score": _cluster_breaking_score(score, cluster_rows, event_entities, event_regions, event_topics),
        "trust_score": score,
        "novelty_score": 55,
        "source_count": len(cluster_rows),
        "entities": event_entities,
        "regions": event_regions,
        "topics": event_topics,
    }


def _cluster_breaking_score(
    source_trust_score: int,
    cluster_rows: list[dict[str, Any]],
    event_entities: list[dict[str, Any]],
    event_regions: list[dict[str, Any]],
    event_topics: list[dict[str, Any]],
) -> int:
    return breaking_score(
        recency_score=75,
        source_trust_score=source_trust_score,
        source_velocity_score=min(100, len(cluster_rows) * 20),
        novelty_score=55,
        affected_entity_importance_score=70 if event_entities else 35,
        topic_severity_score=70 if event_topics else 35,
        cross_region_impact_score=70 if len({item.get("key") for item in event_regions}) > 1 else 30,
    )


def _upsert_news_event_cluster(db: Session, event: dict[str, Any]) -> None:
    db.execute(
        text(
            """
            insert into news_event_cluster(
              id, canonical_title, event_type, first_seen_at, last_seen_at, published_at,
              primary_region, severity, confidence, breaking_score, trust_score, novelty_score,
              source_count, review_state, status
            )
            values (
              :id, :canonical_title, :event_type, :first_seen_at, :last_seen_at, :published_at,
              :primary_region, :severity, :confidence, :breaking_score, :trust_score, :novelty_score,
              :source_count, 'candidate', 'active'
            )
            on conflict (id) do update
            set canonical_title = excluded.canonical_title,
                last_seen_at = excluded.last_seen_at,
                confidence = excluded.confidence,
                breaking_score = excluded.breaking_score,
                trust_score = excluded.trust_score,
                source_count = excluded.source_count,
                updated_at = now()
            """
        ),
        event,
    )


def _upsert_cluster_document_links(
    db: Session, event: dict[str, Any], cluster_rows: list[dict[str, Any]]
) -> int:
    for row in cluster_rows:
        db.execute(
            text(
                """
                insert into news_event_document(event_id, document_id, relationship, confidence, is_primary_source)
                values (:event_id, :document_id, 'supporting_source', :confidence, :is_primary)
                on conflict (event_id, document_id) do update
                set confidence = excluded.confidence,
                    is_primary_source = excluded.is_primary_source
                """
            ),
            {
                "event_id": event["id"],
                "document_id": row["id"],
                "confidence": event["confidence"],
                "is_primary": _is_primary_source(row["metadata"]),
            },
        )
    return len(cluster_rows)


def score_news_events(db: Session) -> dict[str, int]:
    rows = db.execute(
        text(
            """
            select c.id,
                   array_remove(array_agg(distinct d.metadata->>'trust_tier'), null) as trust_tiers,
                   count(distinct ed.document_id) as source_count,
                   count(distinct ee.entity_key) as entity_count,
                   count(distinct er.region_key) as region_count,
                   count(distinct et.topic_key) as topic_count
            from news_event_cluster c
            left join news_event_document ed on ed.event_id = c.id
            left join source_document d on d.id = ed.document_id
            left join news_event_entity ee on ee.event_id = c.id
            left join news_event_region er on er.event_id = c.id
            left join news_event_topic et on et.event_id = c.id
            where c.status = 'active'
            group by c.id
            """
        )
    ).mappings().all()
    for row in rows:
        tiers = [str(value) for value in (row["trust_tiers"] or []) if value]
        score = trust_score(tiers)
        breaking = breaking_score(
            recency_score=70,
            source_trust_score=score,
            source_velocity_score=min(100, int(row["source_count"] or 0) * 20),
            novelty_score=55,
            affected_entity_importance_score=70 if int(row["entity_count"] or 0) else 35,
            topic_severity_score=70 if int(row["topic_count"] or 0) else 35,
            cross_region_impact_score=70 if int(row["region_count"] or 0) > 1 else 30,
        )
        db.execute(
            text(
                """
                update news_event_cluster
                set trust_score = :trust_score,
                    breaking_score = :breaking_score,
                    source_count = :source_count,
                    updated_at = now()
                where id = :id
                """
            ),
            {
                "id": row["id"],
                "trust_score": score,
                "breaking_score": breaking,
                "source_count": int(row["source_count"] or 0),
            },
        )
    fact_result = ensure_news_event_facts(db, limit=500)
    return {"events_scored": len(rows), **fact_result}


def auto_review_trusted_news_events(db: Session) -> dict[str, int]:
    result = db.execute(
        text(
            """
            update news_event_cluster c
            set review_state = 'auto_reviewed',
                updated_at = now()
            where c.status = 'active'
              and c.review_state = 'candidate'
              and c.trust_score >= 80
              and exists (
                select 1
                from news_event_document ed
                join source_document d on d.id = ed.document_id
                where ed.event_id = c.id
                  and d.metadata->>'trust_tier' in ('T0_OFFICIAL', 'T1_REGULATED_FILING')
                  and coalesce((d.metadata->>'discovery_only')::boolean, false) = false
              )
            """
        )
    )
    return {"events_auto_reviewed": int(result.rowcount or 0)}


def _news_documents(db: Session, *, limit: int, require_unclassified: bool) -> list[dict[str, Any]]:
    source_keys = source_registry()
    rows = db.execute(
        text(
            """
            select d.id, d.title, d.canonical_url, d.original_url, d.publisher, d.source_published_at,
                   d.fetched_at, d.language, d.status, d.metadata, ds.source_key
            from source_document d
            left join data_source ds on ds.id = d.source_id
            where coalesce(ds.source_key, d.metadata->>'source_key') in :source_keys
              and (:require_unclassified = false or not (d.metadata ? 'news_classified_at'))
            order by coalesce(d.source_published_at, d.fetched_at, d.created_at) desc
            limit :limit
            """
        ).bindparams(bindparam("source_keys", expanding=True)),
        {"source_keys": list(source_keys), "limit": limit, "require_unclassified": require_unclassified},
    ).mappings().all()
    return [dict(row) for row in rows]


def _classified_news_documents(db: Session, *, limit: int) -> list[dict[str, Any]]:
    source_keys = source_registry()
    rows = db.execute(
        text(
            """
            select d.id, d.title, d.canonical_url, d.original_url, d.publisher, d.source_published_at,
                   d.fetched_at, d.language, d.status, d.metadata, ds.source_key
            from source_document d
            left join data_source ds on ds.id = d.source_id
            where d.metadata ? 'news_classified_at'
              and coalesce(ds.source_key, d.metadata->>'source_key') in :source_keys
            order by coalesce(d.source_published_at, d.fetched_at, d.created_at) desc
            limit :limit
            """
        ).bindparams(bindparam("source_keys", expanding=True)),
        {"source_keys": list(source_keys), "limit": limit},
    ).mappings().all()
    return [dict(row) for row in rows]


def _document_payload(row: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(row["metadata"] or {})
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "url": row["canonical_url"] or row["original_url"],
        "canonical_url": row["canonical_url"] or row["original_url"],
        "snippet": metadata.get("snippet") or "",
        "summary": metadata.get("summary") or "",
        "published_at": metadata.get("published_at") or row["source_published_at"] or row["fetched_at"],
        "source_region": metadata.get("source_region"),
        "market_region": metadata.get("market_region"),
        "event_type": _event_type(metadata.get("news_topics") or []),
        "event_region": _first_region_key(metadata.get("news_regions") or []),
        "entities": metadata.get("news_entities") or [],
    }


def _update_document_metadata(db: Session, document_id: Any, metadata: dict[str, Any], *, status: str) -> None:
    db.execute(
        text(
            """
            update source_document
            set metadata = coalesce(metadata, '{}'::jsonb) || cast(:metadata as jsonb),
                status = :status
            where id = :document_id
            """
        ),
        {"document_id": document_id, "metadata": json.dumps(metadata, default=str), "status": status},
    )


def news_entity_profiles(raw_watchlist: str | None = None) -> list[EntityProfile]:
    profiles_by_symbol = {profile.symbol.upper(): profile for profile in DEFAULT_TRACKED_ENTITY_PROFILES}
    raw = raw_watchlist if raw_watchlist is not None else get_settings().news_ticker_watchlist
    symbols = _symbol_list(raw)
    if not symbols:
        return list(profiles_by_symbol.values())
    profiles: list[EntityProfile] = []
    for symbol in symbols:
        profile = profiles_by_symbol.get(symbol)
        if profile is None:
            profile = EntityProfile(symbol=symbol, legal_name=symbol)
        profiles.append(profile)
    return profiles


def _symbol_list(raw: str | None) -> list[str]:
    values: list[str] = []
    for part in (raw or "").split(","):
        symbol = part.strip().upper()
        if symbol:
            values.append(symbol)
    return list(dict.fromkeys(values))


def _dedupe_metadata_items(rows: list[dict[str, Any]], key: str, *identity_fields: str) -> list[dict[str, Any]]:
    result: dict[tuple[Any, ...], dict[str, Any]] = {}
    for metadata in rows:
        values = metadata.get(key) or []
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            identity = tuple(value.get(field) for field in identity_fields)
            if identity not in result or float(value.get("confidence") or 0) > float(result[identity].get("confidence") or 0):
                result[identity] = dict(value)
    return list(result.values())


def _upsert_event_entities(db: Session, event_id: str, entities: list[dict[str, Any]]) -> None:
    for entity in entities:
        symbol = str(entity.get("symbol") or "")
        if not symbol:
            continue
        db.execute(
            text(
                """
                insert into news_event_entity(event_id, entity_key, entity_type, relationship, confidence)
                values (:event_id, :entity_key, 'ticker', :relationship, :confidence)
                on conflict (event_id, entity_key, relationship) do update
                set confidence = excluded.confidence
                """
            ),
            {
                "event_id": event_id,
                "entity_key": symbol,
                "relationship": str(entity.get("relationship") or "affected_company"),
                "confidence": float(entity.get("confidence") or 0.5),
            },
        )


def _upsert_event_regions(db: Session, event_id: str, regions: list[dict[str, Any]]) -> None:
    for region in regions:
        key = str(region.get("key") or "")
        relation = str(region.get("relation") or "")
        if not key or not relation:
            continue
        db.execute(
            text(
                """
                insert into news_event_region(event_id, region_key, relation, confidence)
                values (:event_id, :region_key, :relation, :confidence)
                on conflict (event_id, region_key, relation) do update
                set confidence = excluded.confidence
                """
            ),
            {
                "event_id": event_id,
                "region_key": key,
                "relation": relation,
                "confidence": float(region.get("confidence") or 0.5),
            },
        )


def _upsert_event_topics(db: Session, event_id: str, topics: list[dict[str, Any]]) -> None:
    for topic in topics:
        key = str(topic.get("key") or "")
        if not key:
            continue
        db.execute(
            text(
                """
                insert into news_event_topic(event_id, topic_key, confidence)
                values (:event_id, :topic_key, :confidence)
                on conflict (event_id, topic_key) do update
                set confidence = excluded.confidence
                """
            ),
            {
                "event_id": event_id,
                "topic_key": key,
                "confidence": float(topic.get("confidence") or 0.5),
            },
        )


def _event_type(topics: Any) -> str:
    topic_keys = [str(topic.get("key")) for topic in topics if isinstance(topic, dict)]
    if "central_banks" in topic_keys or "rates" in topic_keys:
        return "central_bank"
    if "public_health" in topic_keys or "pandemic" in topic_keys:
        return "public_health"
    if "energy" in topic_keys:
        return "energy_supply"
    if "geopolitics" in topic_keys or "trade_policy" in topic_keys:
        return "geopolitical"
    if "space" in topic_keys:
        return "company_news"
    return "market_news"


def _severity(topics: list[dict[str, Any]]) -> str:
    keys = {str(topic.get("key")) for topic in topics}
    if keys & {"public_health", "geopolitics", "energy"}:
        return "high"
    if keys & {"central_banks", "semiconductors"}:
        return "medium"
    return "low"


def _first_region_key(regions: list[dict[str, Any]]) -> str | None:
    for region in regions:
        if isinstance(region, dict) and region.get("key"):
            return str(region["key"])
    return None


def _is_primary_source(metadata: Any) -> bool:
    if not isinstance(metadata, dict):
        return False
    return str(metadata.get("trust_tier") or "").startswith(("T0_", "T1_"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
