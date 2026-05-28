from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from frw_api.adapters.registry import adapter_registry
from frw_api.core.settings import get_settings
from frw_api.db.session import SessionLocal
from frw_api.services.ingestion_pipeline import persist_adapter_result
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

NEWS_JOB_TYPES = {
    "news.fetch_source",
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
    if job_type == "snapshot_build":
        with SessionLocal() as db:
            result = build_candidate_snapshots(db, generated_by=generated_by)
            db.commit()
            return result.__dict__
    if job_type == "snapshot_publish":
        snapshot_version = payload.get("snapshot_version")
        if not snapshot_version:
            raise ValueError("snapshot_publish requires snapshot_version")
        with SessionLocal() as db:
            result = publish_snapshots(db, snapshot_version=int(snapshot_version), generated_by=generated_by)
            db.commit()
            return result.__dict__
    if job_type == "snapshot_refresh":
        await heartbeat()
        with SessionLocal() as db:
            build_result = build_candidate_snapshots(db, generated_by=generated_by)
            db.commit()
            if not build_result.snapshot_version:
                raise ValueError("snapshot_refresh did not produce a snapshot version")
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
    if job_type == "trump_disclosures_ingest":
        await heartbeat()
        with SessionLocal() as db:
            result = await ingest_trump_disclosures(
                db,
                include_oge=bool(payload.get("include_oge", True)),
                include_sec=bool(payload.get("include_sec", True)),
            )
            db.commit()
            return result
    if job_type == "news.fetch_source":
        await heartbeat()
        source_key = payload.get("source_key")
        if not isinstance(source_key, str) or not source_key:
            raise ValueError("news.fetch_source requires source_key")
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
    if job_type == "news.publish_snapshots":
        await heartbeat()
        with SessionLocal() as db:
            build_result = build_candidate_snapshots(db, generated_by=generated_by)
            db.commit()
            if not build_result.snapshot_version:
                raise ValueError("news.publish_snapshots did not produce a snapshot version")
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
    if job_type == "news.read_pages":
        await heartbeat()
        with SessionLocal() as db:
            result = await read_news_pages(db, limit=int(payload.get("limit") or 50))
            db.commit()
            return {"status": "pages_read", **result}
    if job_type == "news.purge_email_raw":
        await heartbeat()
        with SessionLocal() as db:
            result = purge_expired_raw_email(db, limit=int(payload.get("limit") or 500))
            db.commit()
            return {"status": "raw_email_purged", **result}
    if job_type in {"news.normalize_document", "news.extract_evidence"}:
        await heartbeat()
        with SessionLocal() as db:
            result = normalize_news_documents(db, limit=int(payload.get("limit") or 500))
            db.commit()
            return {"status": "normalized", **result}
    if job_type in {"news.classify_entities", "news.classify_regions", "news.classify_topics"}:
        await heartbeat()
        with SessionLocal() as db:
            result = classify_news_documents(db, limit=int(payload.get("limit") or 500))
            db.commit()
            return {"status": "classified", **result}
    if job_type == "news.cluster_events":
        await heartbeat()
        with SessionLocal() as db:
            result = cluster_news_documents(db, limit=int(payload.get("limit") or 500))
            db.commit()
            return {"status": "clustered", **result}
    if job_type == "news.score_events":
        await heartbeat()
        with SessionLocal() as db:
            result = score_news_events(db)
            if get_settings().news_auto_review_trusted_events:
                result.update(auto_review_trusted_news_events(db))
            result.update(enqueue_news_summary_jobs(db))
            db.commit()
            return {"status": "scored", **result}
    if job_type == "news.generate_summary":
        await heartbeat()
        event_id = payload.get("event_id")
        locale = payload.get("locale")
        prompt_version = payload.get("prompt_version")
        input_hash = payload.get("input_hash")
        if not all(isinstance(value, str) and value for value in (event_id, locale, prompt_version, input_hash)):
            raise ValueError("news.generate_summary requires event_id, locale, prompt_version, and input_hash")
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
    if job_type.startswith("adapter."):
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
    if job_type in NEWS_JOB_TYPES:
        await heartbeat()
        return {
            "status": "news_job_registered_pending_pipeline",
            "job_type": job_type,
            "idempotent": True,
            "public_snapshot_safe": True,
            "next_step": "news.fetch_source" if job_type != "news.fetch_source" else None,
        }
    return {"status": "ignored_unknown_job_type", "job_type": job_type}
