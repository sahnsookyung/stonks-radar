from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from frw_api.adapters.registry import adapter_registry
from frw_api.core.settings import get_settings
from frw_api.db.session import SessionLocal
from frw_api.services.ingestion_pipeline import persist_adapter_result
from frw_api.services.instruments import refresh_instrument_index
from frw_api.services.market_data import refresh_market_history
from frw_api.services.news.email_alerts import purge_expired_raw_email
from frw_api.services.news.ingestion import fetch_news_source
from frw_api.services.news.page_reader import read_news_pages
from frw_api.services.news.pipeline import (
    classify_news_documents,
    cluster_news_documents,
    normalize_news_documents,
    auto_review_trusted_news_events,
    score_news_events,
)
from frw_api.services.news.summaries import enqueue_news_summary_jobs, generate_news_summary
from frw_api.services.snapshot_service import build_candidate_snapshots, publish_snapshots
from frw_api.services.trump_disclosures import ingest_trump_disclosures

NEWS_FETCH_SOURCE_JOB = "news.fetch_source"
NEWS_GENERATE_SUMMARY_REQUIREMENTS = "news.generate_summary requires event_id, locale, prompt_version, and input_hash"
NEWS_JOB_TYPES = {
    NEWS_FETCH_SOURCE_JOB,
    "news.normalize_document",
    "news.extract_evidence",
    "news.read_pages",
    "news.purge_email_raw",
    "news.classify_entities",
    "news.classify_regions",
    "news.classify_topics",
    "news.cluster_events",
    "news.score_events",
    "news.generate_summary",
    "news.translate_summary",
    "news.publish_snapshots",
    "news.rebuild_search_index",
    "news.backfill_source",
}


def _snapshot_generated_by(payload: dict[str, Any]) -> str | None:
    requested_by = payload.get("requested_by")
    if not isinstance(requested_by, str) or not requested_by:
        return None
    try:
        UUID(requested_by)
    except ValueError:
        return None
    return requested_by


async def handle_job(job: dict[str, Any], heartbeat: Callable[[], Awaitable[None]]) -> dict[str, Any]:
    job_type = job["job_type"]
    payload = job["payload"] if isinstance(job["payload"], dict) else {}
    generated_by = _snapshot_generated_by(payload)
    handler = _job_handlers().get(job_type)
    if handler:
        return await handler(job, payload, generated_by, heartbeat)
    if job_type.startswith("adapter."):
        return await _handle_adapter_job(job_type, payload, heartbeat)
    if job_type in NEWS_JOB_TYPES:
        return await _handle_registered_news_job(job_type, heartbeat)
    return {"status": "ignored_unknown_job_type", "job_type": job_type}


JobHandler = Callable[
    [dict[str, Any], dict[str, Any], str | None, Callable[[], Awaitable[None]]],
    Awaitable[dict[str, Any]],
]


def _job_handlers() -> dict[str, JobHandler]:
    return {
        "snapshot_build": _handle_snapshot_build,
        "snapshot_publish": _handle_snapshot_publish,
        "snapshot_refresh": _handle_snapshot_refresh,
        "trump_disclosures_ingest": _handle_trump_disclosures_ingest,
        "instrument_search_index_update": _handle_instrument_index_update,
        "market_data.refresh_history": _handle_market_history_refresh,
        NEWS_FETCH_SOURCE_JOB: _handle_news_fetch_source,
        "news.publish_snapshots": _handle_news_publish_snapshots,
        "news.read_pages": _handle_news_read_pages,
        "news.purge_email_raw": _handle_news_purge_email_raw,
        "news.normalize_document": _handle_news_normalize_documents,
        "news.extract_evidence": _handle_news_normalize_documents,
        "news.classify_entities": _handle_news_classify_documents,
        "news.classify_regions": _handle_news_classify_documents,
        "news.classify_topics": _handle_news_classify_documents,
        "news.cluster_events": _handle_news_cluster_events,
        "news.score_events": _handle_news_score_events,
        "news.generate_summary": _handle_news_generate_summary,
    }


async def _handle_snapshot_build(
    _job: dict[str, Any],
    _payload: dict[str, Any],
    generated_by: str | None,
    _heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await _heartbeat()
    with SessionLocal() as db:
        result = build_candidate_snapshots(db, generated_by=generated_by)
        db.commit()
        return result.__dict__


async def _handle_snapshot_publish(
    _job: dict[str, Any],
    payload: dict[str, Any],
    generated_by: str | None,
    _heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await _heartbeat()
    snapshot_version = payload.get("snapshot_version")
    if not snapshot_version:
        raise ValueError("snapshot_publish requires snapshot_version")
    with SessionLocal() as db:
        result = publish_snapshots(db, snapshot_version=int(snapshot_version), generated_by=generated_by)
        db.commit()
        return result.__dict__


async def _handle_snapshot_refresh(
    _job: dict[str, Any],
    _payload: dict[str, Any],
    generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    return await _build_and_publish_snapshots(
        generated_by=generated_by,
        heartbeat=heartbeat,
        missing_version_message="snapshot_refresh did not produce a snapshot version",
    )


async def _handle_trump_disclosures_ingest(
    _job: dict[str, Any],
    payload: dict[str, Any],
    _generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await heartbeat()
    with SessionLocal() as db:
        result = await ingest_trump_disclosures(
            db,
            include_oge=bool(payload.get("include_oge", True)),
            include_sec=bool(payload.get("include_sec", True)),
        )
        db.commit()
        return result


async def _handle_instrument_index_update(
    _job: dict[str, Any],
    payload: dict[str, Any],
    _generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await heartbeat()
    return refresh_instrument_index(
        source=str(payload.get("source") or "LOCAL_STATIC_INDEX"),
        mode=str(payload.get("mode") or "INCREMENTAL"),
    )


async def _handle_market_history_refresh(
    _job: dict[str, Any],
    payload: dict[str, Any],
    _generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await heartbeat()
    symbol = _required_payload_string(payload, "symbol", "market_data.refresh_history requires symbol")
    start, end = _market_history_window(payload)
    with SessionLocal() as db:
        result = await refresh_market_history(symbols=[symbol], start=start, end=end, db=db)
        db.commit()
        return result


async def _handle_news_fetch_source(
    _job: dict[str, Any],
    payload: dict[str, Any],
    _generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await heartbeat()
    source_key = _required_payload_string(payload, "source_key", f"{NEWS_FETCH_SOURCE_JOB} requires source_key")
    max_documents = payload.get("max_documents")
    with SessionLocal() as db:
        result = await fetch_news_source(
            db,
            source_key=source_key,
            query=payload.get("query") if isinstance(payload.get("query"), str) else None,
            max_documents=int(max_documents) if max_documents is not None else None,
        )
        db.commit()
        return result


async def _handle_news_publish_snapshots(
    _job: dict[str, Any],
    _payload: dict[str, Any],
    generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    return await _build_and_publish_snapshots(
        generated_by=generated_by,
        heartbeat=heartbeat,
        missing_version_message="news.publish_snapshots did not produce a snapshot version",
    )


async def _handle_news_read_pages(
    _job: dict[str, Any],
    payload: dict[str, Any],
    _generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await heartbeat()
    with SessionLocal() as db:
        result = await read_news_pages(db, limit=int(payload.get("limit") or 50))
        db.commit()
        return {"status": "pages_read", **result}


async def _handle_news_purge_email_raw(
    _job: dict[str, Any],
    payload: dict[str, Any],
    _generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await heartbeat()
    with SessionLocal() as db:
        result = purge_expired_raw_email(db, limit=int(payload.get("limit") or 500))
        db.commit()
        return {"status": "raw_email_purged", **result}


async def _handle_news_normalize_documents(
    _job: dict[str, Any],
    payload: dict[str, Any],
    _generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await heartbeat()
    with SessionLocal() as db:
        result = normalize_news_documents(db, limit=int(payload.get("limit") or 500))
        db.commit()
        return {"status": "normalized", **result}


async def _handle_news_classify_documents(
    _job: dict[str, Any],
    payload: dict[str, Any],
    _generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await heartbeat()
    with SessionLocal() as db:
        result = classify_news_documents(db, limit=int(payload.get("limit") or 500))
        db.commit()
        return {"status": "classified", **result}


async def _handle_news_cluster_events(
    _job: dict[str, Any],
    payload: dict[str, Any],
    _generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await heartbeat()
    with SessionLocal() as db:
        result = cluster_news_documents(db, limit=int(payload.get("limit") or 500))
        db.commit()
        return {"status": "clustered", **result}


async def _handle_news_score_events(
    _job: dict[str, Any],
    _payload: dict[str, Any],
    _generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await heartbeat()
    with SessionLocal() as db:
        result = score_news_events(db)
        if get_settings().news_auto_review_trusted_events:
            result.update(auto_review_trusted_news_events(db))
        result.update(enqueue_news_summary_jobs(db))
        db.commit()
        return {"status": "scored", **result}


async def _handle_news_generate_summary(
    job: dict[str, Any],
    payload: dict[str, Any],
    _generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await heartbeat()
    event_id = _required_payload_string(payload, "event_id", NEWS_GENERATE_SUMMARY_REQUIREMENTS)
    locale = _required_payload_string(payload, "locale", NEWS_GENERATE_SUMMARY_REQUIREMENTS)
    prompt_version = _required_payload_string(payload, "prompt_version", NEWS_GENERATE_SUMMARY_REQUIREMENTS)
    input_hash = _required_payload_string(payload, "input_hash", NEWS_GENERATE_SUMMARY_REQUIREMENTS)
    with SessionLocal() as db:
        result = await generate_news_summary(
            db,
            event_id=event_id,
            locale=locale,
            prompt_version=prompt_version,
            input_hash=input_hash,
            job_id=str(job.get("id") or ""),
        )
        db.commit()
        return result


async def _handle_adapter_job(
    job_type: str,
    payload: dict[str, Any],
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await heartbeat()
    adapter_key = job_type.split(".", 1)[1]
    adapter = adapter_registry()[adapter_key]
    result = await adapter.fetch(**payload)
    with SessionLocal() as db:
        persisted = persist_adapter_result(db, result)
        db.commit()
    return {
        "source_key": result.source_key,
        "object_key": result.object_key,
        "observation_count": len(result.observations),
        "release_count": len(result.releases),
        "document_count": len(result.documents),
        "persisted": persisted,
        "unsupported": result.unsupported,
    }


async def _handle_registered_news_job(
    job_type: str,
    heartbeat: Callable[[], Awaitable[None]],
) -> dict[str, Any]:
    await heartbeat()
    return {
        "status": "news_job_registered_pending_pipeline",
        "job_type": job_type,
        "idempotent": True,
        "public_snapshot_safe": True,
        "next_step": NEWS_FETCH_SOURCE_JOB if job_type != NEWS_FETCH_SOURCE_JOB else None,
    }


async def _build_and_publish_snapshots(
    *,
    generated_by: str | None,
    heartbeat: Callable[[], Awaitable[None]],
    missing_version_message: str,
) -> dict[str, Any]:
    await heartbeat()
    with SessionLocal() as db:
        build_result = build_candidate_snapshots(db, generated_by=generated_by)
        db.commit()
        if not build_result.snapshot_version:
            raise ValueError(missing_version_message)
        await heartbeat()
        publish_result = publish_snapshots(
            db,
            snapshot_version=int(build_result.snapshot_version),
            generated_by=generated_by,
        )
        db.commit()
        return {
            "status": "published",
            "built": build_result.__dict__,
            "published": publish_result.__dict__,
        }


def _required_payload_string(payload: dict[str, Any], key: str, message: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(message)
    return value


def _market_history_window(payload: dict[str, Any]) -> tuple[date, date]:
    start_value = payload.get("start")
    end_value = payload.get("end")
    if isinstance(start_value, str) and isinstance(end_value, str):
        return date.fromisoformat(start_value[:10]), date.fromisoformat(end_value[:10])

    session_value = payload.get("market_session_date")
    end = date.fromisoformat(session_value[:10]) if isinstance(session_value, str) and session_value else datetime.now(timezone.utc).date()
    days = max(
        1,
        int(payload.get("window_days") or payload.get("days") or get_settings().market_data_snapshot_window_days),
    )
    return end - timedelta(days=days), end
