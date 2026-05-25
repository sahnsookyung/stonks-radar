from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from frw_api.adapters.registry import adapter_registry
from frw_api.db.session import SessionLocal
from frw_api.services.ingestion_pipeline import persist_adapter_result
from frw_api.services.snapshot_service import build_candidate_snapshots, publish_snapshots
from frw_api.services.trump_disclosures import ingest_trump_disclosures


async def handle_job(job: dict[str, Any], heartbeat: Callable[[], Awaitable[None]]) -> dict[str, Any]:
    job_type = job["job_type"]
    payload = job["payload"] if isinstance(job["payload"], dict) else {}
    if job_type == "snapshot_build":
        with SessionLocal() as db:
            result = build_candidate_snapshots(db, generated_by=payload.get("requested_by"))
            db.commit()
            return result.__dict__
    if job_type == "snapshot_publish":
        snapshot_version = payload.get("snapshot_version")
        if not snapshot_version:
            raise ValueError("snapshot_publish requires snapshot_version")
        with SessionLocal() as db:
            result = publish_snapshots(db, snapshot_version=int(snapshot_version), generated_by=payload.get("requested_by"))
            db.commit()
            return result.__dict__
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
    return {"status": "ignored_unknown_job_type", "job_type": job_type}
