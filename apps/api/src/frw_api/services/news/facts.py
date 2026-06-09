from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid"}
_PUBLIC_METADATA_POLICY = "news_metadata_policy_v1"


def ensure_news_event_facts(db: Session, *, limit: int = 500) -> dict[str, int]:
    rows = db.execute(
        text(
            """
            select c.id as event_id,
                   ed.document_id,
                   ed.relationship,
                   ed.confidence,
                   d.title,
                   d.canonical_url,
                   d.original_url,
                   d.source_published_at,
                   d.legal_risk_level,
                   d.metadata,
                   ed.is_primary_source,
                   c.canonical_title,
                   c.event_type,
                   c.severity,
                   c.breaking_score,
                   c.trust_score,
                   c.source_count,
                   coalesce(ds.source_key, d.metadata->>'source_key') as source_key
            from news_event_cluster c
            join news_event_document ed on ed.event_id = c.id
            join source_document d on d.id = ed.document_id
            left join data_source ds on ds.id = d.source_id
            where c.status = 'active'
            order by c.last_seen_at desc, ed.created_at desc
            limit :limit
            """
        ),
        {"limit": max(1, limit)},
    ).mappings().all()
    facts_upserted = 0
    event_links = 0
    event_ids: set[str] = set()
    for row in rows:
        event_ids.add(str(row["event_id"]))
        metadata = dict(row["metadata"] or {})
        fact_id = _upsert_document_metadata_fact(db, dict(row), metadata)
        if fact_id:
            _link_fact_to_event(db, dict(row), fact_id, "document_metadata")
            facts_upserted += 1
            event_links += 1
        link_fact_id = _upsert_event_link_fact(db, dict(row), metadata)
        if link_fact_id:
            _link_fact_to_event(db, dict(row), link_fact_id, "event_link")
            facts_upserted += 1
            event_links += 1
    entity_result = _ensure_entity_mention_facts(db, event_ids)
    market_result = _ensure_market_relevance_facts(db, event_ids)
    return {
        "facts_upserted": facts_upserted + entity_result["facts_upserted"] + market_result["facts_upserted"],
        "event_fact_links": event_links + entity_result["event_fact_links"] + market_result["event_fact_links"],
    }


def approved_news_event_facts(db: Session, event_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select f.id,
                   f.fact_type,
                   f.predicate,
                   f.object_json,
                   f.time_reference,
                   f.confidence,
                   nef.document_id
            from news_event_fact nef
            join source_fact f on f.id = nef.fact_id
            where nef.event_id = :event_id
              and f.public_allowed = true
              and f.review_status in ('approved','editor_approved','owner_approved')
            order by f.created_at asc, f.id asc
            """
        ),
        {"event_id": event_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def news_summary_input_hash(facts: list[dict[str, Any]]) -> str:
    payload = [
        {
            "id": str(fact["id"]),
            "fact_type": fact["fact_type"],
            "predicate": fact["predicate"],
            "object_json": fact["object_json"],
            "time_reference": fact["time_reference"],
        }
        for fact in sorted(facts, key=lambda item: str(item["id"]))
    ]
    return "sha256:" + hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def public_summary_cited_facts_valid(
    db: Session,
    fact_ids: list[str],
    *,
    allowed_fact_ids: set[str] | None = None,
) -> bool:
    if not fact_ids:
        return False
    unique_ids = set(fact_ids)
    if allowed_fact_ids is not None and not unique_ids.issubset(allowed_fact_ids):
        return False
    count = db.execute(
        text(
            """
            select count(*)
            from source_fact
            where id::text in :ids
              and public_allowed = true
              and review_status in ('approved','editor_approved','owner_approved')
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(dict.fromkeys(fact_ids))},
    ).scalar_one()
    return int(count or 0) == len(unique_ids)


def _upsert_document_metadata_fact(db: Session, row: dict[str, Any], metadata: dict[str, Any]) -> str | None:  # NOSONAR - metadata fact upsert must keep dedupe/publication flags consistent.
    url = sanitize_public_source_url(str(row.get("canonical_url") or row.get("original_url") or ""))
    title = str(row.get("title") or "").strip()
    source_key = str(row.get("source_key") or metadata.get("source_key") or "unknown")
    trust_tier = str(metadata.get("trust_tier") or "T5_UNREVIEWED")
    if not title or not url:
        return None
    object_json = {
        "title": title[:500],
        "snippet": str(metadata.get("snippet") or "")[:1000] or None,
        "published_at": _json_time(metadata.get("published_at") or row.get("source_published_at")),
        "source_url": url,
        "source_key": source_key,
        "trust_tier": trust_tier,
    }
    time_reference = {"published_at": object_json["published_at"]} if object_json["published_at"] else None
    public_allowed = _trusted_public_metadata(row, metadata, trust_tier)
    evidence_hash = _sha256(
        "|".join(
            [
                str(row["document_id"]),
                "news_document_metadata",
                "states",
                _canonical_json(object_json),
            ]
        )
    )
    evidence_id = db.execute(
        text(
            """
            insert into source_evidence(
              source_document_id, evidence_excerpt, evidence_hash, location_json,
              extraction_model_version, confidence, manually_confirmed, public_allowed
            )
            values (
              :document_id, :excerpt, :evidence_hash, cast(:location_json as jsonb),
              :model_version, :confidence, false, :public_allowed
            )
            on conflict (source_document_id, evidence_hash) do update
            set evidence_excerpt = excluded.evidence_excerpt,
                confidence = greatest(source_evidence.confidence, excluded.confidence),
                public_allowed = source_evidence.public_allowed or excluded.public_allowed
            returning id
            """
        ),
        {
            "document_id": row["document_id"],
            "excerpt": f"{title[:240]} {object_json['snippet'] or ''}".strip()[:1000],
            "evidence_hash": evidence_hash,
            "location_json": json.dumps({"kind": "metadata", "source_url": url}),
            "model_version": _PUBLIC_METADATA_POLICY,
            "confidence": float(row.get("confidence") or 0.7),
            "public_allowed": public_allowed,
        },
    ).scalar_one()
    dedupe_key = _sha256(
        "|".join(
            [
                str(evidence_id),
                "news_document_metadata",
                "states",
                _canonical_json(object_json),
                _canonical_json(time_reference or {}),
            ]
        )
    )
    fact_id = db.execute(
        text(
            """
            insert into source_fact(
              source_evidence_id, fact_type, predicate, object_json,
              time_reference, confidence, extraction_source, review_status,
              public_allowed, dedupe_key
            )
            values (
              :evidence_id, 'news_document_metadata', 'states', cast(:object_json as jsonb),
              cast(:time_reference as jsonb), :confidence, 'rule', :review_status,
              :public_allowed, :dedupe_key
            )
            on conflict (dedupe_key) do update
            set confidence = greatest(source_fact.confidence, excluded.confidence),
                public_allowed = source_fact.public_allowed or excluded.public_allowed,
                review_status = case
                  when source_fact.review_status = 'candidate' and excluded.public_allowed then 'approved'
                  else source_fact.review_status
                end
            returning id
            """
        ),
        {
            "evidence_id": evidence_id,
            "object_json": _canonical_json(object_json),
            "time_reference": _canonical_json(time_reference) if time_reference else None,
            "confidence": float(row.get("confidence") or 0.7),
            "review_status": "approved" if public_allowed else "candidate",
            "public_allowed": public_allowed,
            "dedupe_key": dedupe_key,
        },
    ).scalar_one()
    if public_allowed:
        db.execute(
            text(
                """
                update source_document
                set public_allowed = true,
                    review_required = false,
                    metadata = coalesce(metadata, '{}'::jsonb) || cast(:metadata as jsonb)
                where id = :document_id
                """
            ),
            {
                "document_id": row["document_id"],
                "metadata": json.dumps({"news_metadata_public_approved_at": datetime.now(timezone.utc).isoformat()}),
            },
        )
    return str(fact_id)


def _upsert_event_link_fact(db: Session, row: dict[str, Any], metadata: dict[str, Any]) -> str | None:
    title = str(row.get("title") or "").strip()
    trust_tier = str(metadata.get("trust_tier") or "T5_UNREVIEWED")
    if not title:
        return None
    object_json = {
        "event_id": str(row["event_id"]),
        "document_id": str(row["document_id"]),
        "relationship": str(row.get("relationship") or "supporting_source"),
        "confidence": float(row.get("confidence") or 0.7),
    }
    time_reference = _published_time_reference(row, metadata)
    return _upsert_rule_fact(
        db,
        row=row,
        metadata=metadata,
        fact_type="news_event_link",
        predicate="supports",
        object_json=object_json,
        time_reference=time_reference,
        excerpt=f"{title[:240]} supports {str(row.get('canonical_title') or '')[:500]}".strip(),
        public_allowed=_trusted_public_metadata(row, metadata, trust_tier),
        dedupe_scope=str(row["event_id"]),
    )


def _ensure_entity_mention_facts(db: Session, event_ids: set[str]) -> dict[str, int]:
    if not event_ids:
        return {"facts_upserted": 0, "event_fact_links": 0}
    rows = db.execute(
        text(
            """
            select ee.event_id,
                   ee.entity_key,
                   ee.entity_type,
                   ee.relationship,
                   ee.confidence,
                   ed.document_id,
                   d.title,
                   d.canonical_url,
                   d.original_url,
                   d.source_published_at,
                   d.legal_risk_level,
                   d.metadata,
                   coalesce(ds.source_key, d.metadata->>'source_key') as source_key
            from news_event_entity ee
            join lateral (
              select event_id, document_id
              from news_event_document
              where event_id = ee.event_id
              order by is_primary_source desc, confidence desc, created_at asc
              limit 1
            ) ed on true
            join source_document d on d.id = ed.document_id
            left join data_source ds on ds.id = d.source_id
            where ee.event_id in :event_ids
            """
        ).bindparams(bindparam("event_ids", expanding=True)),
        {"event_ids": sorted(event_ids)},
    ).mappings().all()
    facts_upserted = 0
    event_links = 0
    for raw in rows:
        row = dict(raw)
        metadata = dict(row["metadata"] or {})
        trust_tier = str(metadata.get("trust_tier") or "T5_UNREVIEWED")
        object_json = {
            "entity_key": str(row["entity_key"]),
            "entity_type": str(row["entity_type"]),
            "relationship": str(row["relationship"]),
            "confidence": float(row.get("confidence") or 0.5),
        }
        fact_id = _upsert_rule_fact(
            db,
            row=row,
            metadata=metadata,
            fact_type="news_entity_mention",
            predicate="mentions",
            object_json=object_json,
            time_reference=_published_time_reference(row, metadata),
            excerpt=f"{row.get('title') or 'News source'} mentions {object_json['entity_key']}",
            public_allowed=_trusted_public_metadata(row, metadata, trust_tier),
            dedupe_scope=str(row["event_id"]),
        )
        if fact_id:
            _link_fact_to_event(db, row, fact_id, "entity_mention")
            facts_upserted += 1
            event_links += 1
    return {"facts_upserted": facts_upserted, "event_fact_links": event_links}


def _ensure_market_relevance_facts(db: Session, event_ids: set[str]) -> dict[str, int]:
    if not event_ids:
        return {"facts_upserted": 0, "event_fact_links": 0}
    rows = db.execute(
        text(
            """
            select c.id as event_id,
                   c.canonical_title,
                   c.event_type,
                   c.severity,
                   c.confidence,
                   c.breaking_score,
                   c.trust_score,
                   c.source_count,
                   ed.document_id,
                   d.title,
                   d.canonical_url,
                   d.original_url,
                   d.source_published_at,
                   d.legal_risk_level,
                   d.metadata,
                   coalesce(ds.source_key, d.metadata->>'source_key') as source_key
            from news_event_cluster c
            join lateral (
              select event_id, document_id
              from news_event_document
              where event_id = c.id
              order by is_primary_source desc, confidence desc, created_at asc
              limit 1
            ) ed on true
            join source_document d on d.id = ed.document_id
            left join data_source ds on ds.id = d.source_id
            where c.id in :event_ids
            """
        ).bindparams(bindparam("event_ids", expanding=True)),
        {"event_ids": sorted(event_ids)},
    ).mappings().all()
    facts_upserted = 0
    event_links = 0
    for raw in rows:
        row = dict(raw)
        metadata = dict(row["metadata"] or {})
        trust_tier = str(metadata.get("trust_tier") or "T5_UNREVIEWED")
        object_json = {
            "direction": "unclear",
            "confidence": _market_confidence_label(row),
            "reasoning": (
                f"{row['event_type']} event with severity {row['severity']}, "
                f"{int(row.get('source_count') or 0)} source(s), "
                f"trust score {int(row.get('trust_score') or 0)}, "
                f"and breaking score {int(row.get('breaking_score') or 0)}."
            ),
        }
        fact_id = _upsert_rule_fact(
            db,
            row=row,
            metadata=metadata,
            fact_type="news_market_relevance",
            predicate="suggests",
            object_json=object_json,
            time_reference=_published_time_reference(row, metadata),
            excerpt=f"{row.get('canonical_title') or row.get('title') or 'News event'} market relevance",
            public_allowed=_trusted_public_metadata(row, metadata, trust_tier),
            dedupe_scope=str(row["event_id"]),
        )
        if fact_id:
            _link_fact_to_event(db, row, fact_id, "market_relevance")
            facts_upserted += 1
            event_links += 1
    return {"facts_upserted": facts_upserted, "event_fact_links": event_links}


def _upsert_rule_fact(
    db: Session,
    *,
    row: dict[str, Any],
    metadata: dict[str, Any],
    fact_type: str,
    predicate: str,
    object_json: dict[str, Any],
    time_reference: dict[str, Any] | None,
    excerpt: str,
    public_allowed: bool,
    dedupe_scope: str = "",
) -> str | None:
    document_id = row.get("document_id")
    if not document_id:
        return None
    evidence_hash = _sha256(
        "|".join(
            [
                str(document_id),
                fact_type,
                predicate,
                _canonical_json(object_json),
            ]
        )
    )
    evidence_id = db.execute(
        text(
            """
            insert into source_evidence(
              source_document_id, evidence_excerpt, evidence_hash, location_json,
              extraction_model_version, confidence, manually_confirmed, public_allowed
            )
            values (
              :document_id, :excerpt, :evidence_hash, cast(:location_json as jsonb),
              :model_version, :confidence, false, :public_allowed
            )
            on conflict (source_document_id, evidence_hash) do update
            set evidence_excerpt = excluded.evidence_excerpt,
                confidence = greatest(source_evidence.confidence, excluded.confidence),
                public_allowed = source_evidence.public_allowed or excluded.public_allowed
            returning id
            """
        ),
        {
            "document_id": document_id,
            "excerpt": excerpt[:1000],
            "evidence_hash": evidence_hash,
            "location_json": json.dumps(
                {
                    "kind": "rule",
                    "source_url": sanitize_public_source_url(str(row.get("canonical_url") or row.get("original_url") or "")),
                    "source_key": row.get("source_key") or metadata.get("source_key"),
                },
                default=str,
            ),
            "model_version": _PUBLIC_METADATA_POLICY,
            "confidence": float(row.get("confidence") or 0.7),
            "public_allowed": public_allowed,
        },
    ).scalar_one()
    dedupe_key = _sha256(
        "|".join(
            [
                fact_type,
                predicate,
                dedupe_scope,
                _canonical_json(object_json),
                _canonical_json(time_reference or {}),
            ]
        )
    )
    fact_id = db.execute(
        text(
            """
            insert into source_fact(
              source_evidence_id, fact_type, predicate, object_json,
              time_reference, confidence, extraction_source, review_status,
              public_allowed, dedupe_key
            )
            values (
              :evidence_id, :fact_type, :predicate, cast(:object_json as jsonb),
              cast(:time_reference as jsonb), :confidence, 'rule', :review_status,
              :public_allowed, :dedupe_key
            )
            on conflict (dedupe_key) do update
            set confidence = greatest(source_fact.confidence, excluded.confidence),
                public_allowed = source_fact.public_allowed or excluded.public_allowed,
                review_status = case
                  when source_fact.review_status = 'candidate' and excluded.public_allowed then 'approved'
                  else source_fact.review_status
                end
            returning id
            """
        ),
        {
            "evidence_id": evidence_id,
            "fact_type": fact_type,
            "predicate": predicate,
            "object_json": _canonical_json(object_json),
            "time_reference": _canonical_json(time_reference) if time_reference else None,
            "confidence": float(row.get("confidence") or 0.7),
            "review_status": "approved" if public_allowed else "candidate",
            "public_allowed": public_allowed,
            "dedupe_key": dedupe_key,
        },
    ).scalar_one()
    return str(fact_id)


def _link_fact_to_event(db: Session, row: dict[str, Any], fact_id: str, role: str) -> None:
    db.execute(
        text(
            """
            insert into news_event_fact(event_id, fact_id, document_id, role)
            values (:event_id, :fact_id, :document_id, :role)
            on conflict (event_id, fact_id) do update
            set role = excluded.role,
                document_id = excluded.document_id
            """
        ),
        {
            "event_id": row["event_id"],
            "fact_id": fact_id,
            "document_id": row["document_id"],
            "role": role,
        },
    )


def _trusted_public_metadata(row: dict[str, Any], metadata: dict[str, Any], trust_tier: str) -> bool:
    if bool(metadata.get("discovery_only")):
        return False
    if str(row.get("legal_risk_level") or "").lower() not in {"low", ""}:
        return False
    return trust_tier in {"T0_OFFICIAL", "T1_REGULATED_FILING"}


def _published_time_reference(row: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any] | None:
    value = _json_time(metadata.get("published_at") or row.get("source_published_at"))
    return {"published_at": value} if value else None


def _market_confidence_label(row: dict[str, Any]) -> str:
    score = max(float(row.get("confidence") or 0) * 100, float(row.get("trust_score") or 0))
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def sanitize_public_source_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    clean_pairs = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_QUERY_KEYS
        and not key.lower().startswith(_TRACKING_QUERY_PREFIXES)
    ]
    return urlunparse(parsed._replace(netloc=netloc, query=urlencode(clean_pairs), fragment=""))


def _json_time(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()
