from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.adapters.base import AdapterResult
from frw_api.services.operation_status import upsert_source_health


def persist_adapter_result(db: Session, result: AdapterResult) -> dict[str, int | str]:
    source_id = _ensure_source(db, result.source_key)
    persisted = {"observations": 0, "releases": 0, "documents": 0, "source_status": "ready"}
    if result.unsupported:
        upsert_source_health(
            db,
            source_key=result.source_key,
            status="unsupported",
            error="; ".join(result.unsupported),
            details={"unsupported": result.unsupported, "object_key": result.object_key},
        )
        persisted["source_status"] = "unsupported"
    for document in result.documents:
        _persist_document(db, source_id, result.source_key, result.object_key, document)
        persisted["documents"] += 1
    for release in result.releases:
        _persist_release(db, source_id, result.source_key, release)
        persisted["releases"] += 1
    for observation in result.observations:
        _persist_observation(db, source_id, result.source_key, result.object_key, observation)
        persisted["observations"] += 1
    if not result.unsupported:
        upsert_source_health(
            db,
            source_key=result.source_key,
            status="ready",
            details={"object_key": result.object_key, **persisted},
        )
    return persisted


def _ensure_source(db: Session, source_key: str) -> str:
    source_id = db.execute(
        text("select id from data_source where source_key = :source_key"),
        {"source_key": source_key},
    ).scalar_one_or_none()
    if source_id:
        return str(source_id)
    return str(
        db.execute(
            text(
                """
                insert into data_source(source_key, display_name, source_type, raw_retention_policy)
                values (:source_key, :display_name, 'manual', 'metadata_only')
                returning id
                """
            ),
            {"source_key": source_key, "display_name": source_key},
        ).scalar_one()
    )


def _provider_object(db: Session, source_key: str) -> str:
    return _ensure_canonical(
        db,
        object_type="provider",
        object_key=f"provider:{source_key.upper()}",
        display_name_en=source_key,
        display_name_ko=None,
    )


def _ensure_canonical(
    db: Session,
    *,
    object_type: str,
    object_key: str,
    display_name_en: str,
    display_name_ko: str | None = None,
) -> str:
    row = db.execute(
        text(
            """
            insert into canonical_object(object_type, object_key, display_name_en, display_name_ko)
            values (:object_type, :object_key, :display_name_en, :display_name_ko)
            on conflict (object_type, object_key) do update set display_name_en = excluded.display_name_en
            returning id
            """
        ),
        {
            "object_type": object_type,
            "object_key": object_key,
            "display_name_en": display_name_en,
            "display_name_ko": display_name_ko,
        },
    ).scalar_one()
    return str(row)


def _persist_document(
    db: Session,
    source_id: str,
    source_key: str,
    object_key: str,
    document: dict[str, Any],
) -> None:
    title = str(document.get("title") or document.get("url") or object_key)[:500]
    url = document.get("url") or document.get("source_url")
    content_hash = _hash(document)
    db.execute(
        text(
            """
            insert into source_document(
              source_id, title, original_url, canonical_url, publisher, acquisition_mode,
              acquisition_stack, retention_class, fetched_at, content_hash,
              legal_risk_level, review_required, downstream_ai_allowed, public_allowed, status, metadata
            )
            values (
              :source_id, :title, :url, :url, :publisher, :mode,
              'adapter_metadata', 'metadata_only', now(), :content_hash,
              :risk, true, 'extract_only', false, 'discovered', cast(:metadata as jsonb)
            )
            on conflict do nothing
            """
        ),
        {
            "source_id": source_id,
            "title": title,
            "url": url,
            "publisher": source_key,
            "mode": "news_metadata" if document.get("discovery_only") else "official_api",
            "content_hash": content_hash,
            "risk": "medium" if document.get("discovery_only") else "low",
            "metadata": json.dumps(document, default=str),
        },
    )


def _persist_release(db: Session, source_id: str, source_key: str, release: dict[str, Any]) -> None:
    release_key = str(release.get("release_key") or _hash(release).replace("sha256:", "release_"))
    canonical_id = _ensure_canonical(
        db,
        object_type="economic_release",
        object_key=f"release:{release_key}",
        display_name_en=str(release.get("title") or release_key)[:500],
    )
    country_region_object_id = _provider_object(db, source_key)
    scheduled_at = _parse_timestamp(release.get("scheduled_at") or release.get("date"))
    db.execute(
        text(
            """
            insert into economic_release(
              canonical_object_id, release_key, country_region_object_id, release_type,
              scheduled_at, scheduled_local_date, time_precision, timezone, source_id, status
            )
            values (
              :canonical_object_id, :release_key, :country_region_object_id, :release_type,
              :scheduled_at, coalesce(cast(:scheduled_at as date), current_date),
              :time_precision, :timezone, :source_id, :status
            )
            on conflict (release_key) do update
            set scheduled_at = excluded.scheduled_at,
                status = excluded.status,
                source_id = excluded.source_id
            """
        ),
        {
            "canonical_object_id": canonical_id,
            "release_key": release_key,
            "country_region_object_id": country_region_object_id,
            "release_type": str(release.get("release_type") or "official_calendar"),
            "scheduled_at": scheduled_at,
            "time_precision": str(release.get("time_precision") or "date_only"),
            "timezone": str(release.get("timezone") or "UTC"),
            "source_id": source_id,
            "status": str(release.get("status") or "scheduled"),
        },
    )


def _persist_observation(
    db: Session,
    source_id: str,
    source_key: str,
    object_key: str,
    observation: dict[str, Any],
) -> None:
    series_key = str(observation.get("series_key") or object_key)
    timestamp = _observation_timestamp(observation)
    value_json = observation if isinstance(observation, dict) else {"value": observation}
    schema_key = str(observation.get("value_schema_key") or "adapter_observation_v1")
    series_id = _ensure_series(db, series_key, source_key)
    payload_hash = _hash(value_json)
    idempotency_key = str(
        observation.get("idempotency_key")
        or observation.get("provider_observation_key")
        or f"{series_key}:{timestamp.isoformat()}:{payload_hash}"
    )
    candidate_id = db.execute(
        text(
            """
            insert into observation_candidate(
              series_id, source_id, provider_observation_key, observation_timestamp,
              publication_timestamp, source_timestamp, value_json, value_schema_key,
              delay_classification, parse_confidence, idempotency_key, payload_hash
            )
            values (
              :series_id, :source_id, :provider_observation_key, :observation_timestamp,
              :publication_timestamp, :source_timestamp, cast(:value_json as jsonb), :value_schema_key,
              :delay_classification, :parse_confidence, :idempotency_key, :payload_hash
            )
            on conflict (series_id, source_id, observation_timestamp, idempotency_key) do nothing
            returning id
            """
        ),
        {
            "series_id": series_id,
            "source_id": source_id,
            "provider_observation_key": str(observation.get("provider_observation_key") or idempotency_key)[:500],
            "observation_timestamp": timestamp,
            "publication_timestamp": _parse_timestamp(observation.get("publication_timestamp")),
            "source_timestamp": _parse_timestamp(observation.get("source_timestamp")),
            "value_json": json.dumps(value_json, default=str),
            "value_schema_key": schema_key,
            "delay_classification": str(observation.get("delay_classification") or "reference_or_delayed"),
            "parse_confidence": observation.get("parse_confidence") or 0.8,
            "idempotency_key": idempotency_key,
            "payload_hash": payload_hash,
        },
    ).scalar_one_or_none()
    if not candidate_id:
        candidate_id = db.execute(
            text(
                """
                select id from observation_candidate
                where series_id = :series_id
                  and source_id = :source_id
                  and observation_timestamp = :observation_timestamp
                  and idempotency_key = :idempotency_key
                """
            ),
            {
                "series_id": series_id,
                "source_id": source_id,
                "observation_timestamp": timestamp,
                "idempotency_key": idempotency_key,
            },
        ).scalar_one()
    _accept_candidate(db, series_id, str(candidate_id), timestamp, value_json, schema_key)


def _ensure_series(db: Session, series_key: str, source_key: str) -> str:
    canonical_id = _ensure_canonical(
        db,
        object_type="series",
        object_key=f"series:{series_key.upper()}",
        display_name_en=series_key,
    )
    subject_id = _provider_object(db, source_key)
    return str(
        db.execute(
            text(
                """
                insert into series(
                  canonical_object_id, series_key, display_name_en, subject_object_id,
                  frequency, units, latency_tier, stale_after_seconds, source_priority
                )
                values (
                  :canonical_object_id, :series_key, :display_name_en, :subject_object_id,
                  'unknown', 'unknown', 'reference', 604800, cast(:source_priority as jsonb)
                )
                on conflict (series_key) do update set active = true
                returning id
                """
            ),
            {
                "canonical_object_id": canonical_id,
                "series_key": series_key,
                "display_name_en": series_key,
                "subject_object_id": subject_id,
                "source_priority": json.dumps([source_key]),
            },
        ).scalar_one()
    )


def _accept_candidate(
    db: Session,
    series_id: str,
    candidate_id: str,
    timestamp: datetime,
    value_json: dict[str, Any],
    schema_key: str,
) -> None:
    db.execute(
        text(
            """
            update canonical_observation
            set canonical_status = 'superseded'
            where series_id = :series_id
              and observation_timestamp = :observation_timestamp
              and canonical_status = 'active'
            """
        ),
        {"series_id": series_id, "observation_timestamp": timestamp},
    )
    version = int(
        db.execute(
            text(
                """
                select coalesce(max(version), 0) + 1
                from canonical_observation
                where series_id = :series_id and observation_timestamp = :observation_timestamp
                """
            ),
            {"series_id": series_id, "observation_timestamp": timestamp},
        ).scalar_one()
    )
    canonical_id = db.execute(
        text(
            """
            insert into canonical_observation(
              series_id, observation_timestamp, version, accepted_candidate_id,
              accepted_candidate_timestamp, value_json, value_schema_key, acceptance_reason,
              canonical_status, stale_status, fallback_in_use, conflict_present
            )
            values (
              :series_id, :observation_timestamp, :version, :candidate_id,
              :observation_timestamp, cast(:value_json as jsonb), :schema_key,
              'adapter_candidate_auto_accept', 'active', 'fresh', false, false
            )
            returning id
            """
        ),
        {
            "series_id": series_id,
            "observation_timestamp": timestamp,
            "version": version,
            "candidate_id": candidate_id,
            "value_json": json.dumps(value_json, default=str),
            "schema_key": schema_key,
        },
    ).scalar_one()
    db.execute(
        text(
            """
            insert into latest_series_state(
              series_id, canonical_observation_id, observation_timestamp, value_json,
              freshness_status, delay_classification, fallback_in_use, conflict_present, rebuilt_at
            )
            values (
              :series_id, :canonical_id, :observation_timestamp, cast(:value_json as jsonb),
              'fresh', 'reference_or_delayed', false, false, now()
            )
            on conflict (series_id) do update
            set canonical_observation_id = excluded.canonical_observation_id,
                observation_timestamp = excluded.observation_timestamp,
                value_json = excluded.value_json,
                freshness_status = excluded.freshness_status,
                delay_classification = excluded.delay_classification,
                fallback_in_use = excluded.fallback_in_use,
                conflict_present = excluded.conflict_present,
                rebuilt_at = now()
            """
        ),
        {
            "series_id": series_id,
            "canonical_id": canonical_id,
            "observation_timestamp": timestamp,
            "value_json": json.dumps(value_json, default=str),
        },
    )


def _observation_timestamp(observation: dict[str, Any]) -> datetime:
    for key in ("observation_timestamp", "date", "period", "time"):
        parsed = _parse_timestamp(observation.get(key))
        if parsed:
            return parsed
    year = observation.get("year")
    period = str(observation.get("period") or "")
    if year and period.startswith("M") and period[1:].isdigit():
        return datetime(int(year), int(period[1:]), 1, tzinfo=timezone.utc)
    if year:
        return datetime(int(year), 1, 1, tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text_value = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text_value)
    except ValueError:
        if len(str(value)) == 4 and str(value).isdigit():
            return datetime(int(value), 1, 1, tzinfo=timezone.utc)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
