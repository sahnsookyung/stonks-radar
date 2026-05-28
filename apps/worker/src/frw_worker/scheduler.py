from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from frw_api.core.settings import Settings, get_settings
from frw_api.services.job_queue import enqueue_job


def trump_disclosure_job_specs(
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    if not settings.worker_scheduler_enabled:
        return []
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    timestamp = int(now.timestamp())
    specs: list[dict[str, Any]] = []
    if settings.trump_disclosure_sec_poll_seconds > 0:
        window = timestamp // settings.trump_disclosure_sec_poll_seconds
        specs.append(
            {
                "job_type": "trump_disclosures_ingest",
                "idempotency_key": f"trump-disclosures:sec:{window}",
                "payload": {"include_sec": True, "include_oge": False},
                "job_group": "disclosures",
                "priority": 40,
                "provider_key": "sec_edgar",
            }
        )
    if settings.trump_disclosure_oge_poll_seconds > 0 and settings.trump_disclosure_oge_pdf_limit > 0:
        window = timestamp // settings.trump_disclosure_oge_poll_seconds
        specs.append(
            {
                "job_type": "trump_disclosures_ingest",
                "idempotency_key": f"trump-disclosures:oge:{window}",
                "payload": {"include_sec": False, "include_oge": True},
                "job_group": "disclosures",
                "priority": 80,
                "provider_key": "oge_disclosures",
            }
        )
    return specs


def snapshot_refresh_job_specs(
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    if not settings.worker_scheduler_enabled or settings.snapshot_refresh_seconds <= 0:
        return []
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    window = int(now.timestamp()) // settings.snapshot_refresh_seconds
    return [
        {
            "job_type": "snapshot_refresh",
            "idempotency_key": f"snapshot-refresh:{window}",
            "payload": {},
            "job_group": "snapshots",
            "priority": 60,
            "provider_key": "snapshot_refresh",
        }
    ]


def schedule_due_jobs(db: Session, *, now: datetime | None = None, settings: Settings | None = None) -> list[str]:
    job_ids: list[str] = []
    for spec in snapshot_refresh_job_specs(now=now, settings=settings):
        job_ids.append(enqueue_job(db, **spec))
    for spec in trump_disclosure_job_specs(now=now, settings=settings):
        job_ids.append(enqueue_job(db, **spec))
    return job_ids
