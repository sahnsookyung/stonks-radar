from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, HttpUrl
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.auth.security import CurrentUser, require_csrf, require_role
from frw_api.core.settings import get_settings
from frw_api.db.session import get_db
from frw_api.services.audit import audit
from frw_api.services.document_summary import summarize_public_url
from frw_api.services.fact_validation import FactValidationError, validate_fact_shape
from frw_api.services.instruments import instrument_detail, refresh_instrument_index, search_instruments
from frw_api.services.job_queue import enqueue_job, replay_dead_letter
from frw_api.services.provider_budget import set_kill_switch
from frw_api.services.publication_gate import EventGateInput, can_publish_event
from frw_api.services.snapshot_service import (
    build_candidate_snapshots,
    build_local_seed_snapshots,
    list_snapshot_candidates,
    publish_snapshots,
    rollback_snapshots,
)
from frw_api.services.source_ingestion import SourceIngestionError, ingest_url

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]
ViewerUser = Annotated[CurrentUser, Depends(require_role("owner", "admin", "editor", "viewer"))]
CsrfUser = Annotated[CurrentUser, Depends(require_csrf)]
BAD_REQUEST_RESPONSE = {400: {"description": "Bad request"}}
NOT_FOUND_RESPONSE = {404: {"description": "Not found"}}
BAD_REQUEST_OR_NOT_FOUND_RESPONSES = {
    400: {"description": "Bad request"},
    404: {"description": "Not found"},
}
ADMIN_SUMMARY_RESPONSES = {
    400: {"description": "URL summary could not be generated"},
    403: {"description": "Admin URL summaries are disabled"},
    429: {"description": "Admin URL summary daily limit reached"},
}


class SourceCreate(BaseModel):
    source_key: str
    display_name: str
    source_type: str
    base_url: str | None = None


class UrlIngestRequest(BaseModel):
    url: HttpUrl
    source_key: str | None = None


class UrlSummaryRequest(BaseModel):
    url: HttpUrl
    locale: str = "en"


class ReviewRequest(BaseModel):
    decision: str
    public_allowed: bool = False


class SnapshotVersionRequest(BaseModel):
    snapshot_version: int


class CorrectionRequest(BaseModel):
    title: str
    summary: str
    status: str
    affected_object_key: str | None = None


class InstrumentReviewUpdateRequest(BaseModel):
    status: str
    admin_notes: str | None = None


class InstrumentRefreshRequest(BaseModel):
    source: str = "LOCAL_STATIC_INDEX"
    mode: str = "INCREMENTAL"
    priority: str = "HIGH"


@router.get("/dashboard")
def dashboard(
    user: ViewerUser,
    db: DbSession,
):
    metrics = {
        "queued_jobs": _count(db, "select count(*) from job_queue where status in ('queued','retry_wait')"),
        "dead_letter_jobs": _count(db, "select count(*) from job_queue where status = 'dead_letter'"),
        "pending_facts": _count(db, "select count(*) from source_fact where review_status = 'candidate'"),
        "candidate_events": _count(db, "select count(*) from geo_event where review_status = 'candidate'"),
        "stale_translations": _count(db, "select count(*) from content_translation where stale = true"),
        "published_snapshots": _count(db, "select count(*) from publication_snapshot where publication_status = 'published'"),
        "disk_watermark": "unknown_until_monitor_runs",
        "snapshot_storage_status": "local_oci",
    }
    budgets = [
        dict(row)
        for row in db.execute(
            text(
                """
                select id, provider_key, provider_type, routing_mode, kill_switch_enabled,
                       current_period_usage, hard_limit
                from provider_budget
                order by provider_key
                """
            )
        )
        .mappings()
        .all()
    ]
    dead_letters = [
        dict(row)
        for row in db.execute(
            text(
                """
                select id, job_type, last_error_message, created_at
                from job_queue
                where status = 'dead_letter'
                order by created_at desc
                limit 20
                """
            )
        )
        .mappings()
        .all()
    ]
    source_health = [
        dict(row)
        for row in db.execute(
            text(
                """
                select source_key, status, status_code, response_ms, last_checked_at, last_error
                from source_health_status
                order by source_key
                """
            )
        )
        .mappings()
        .all()
    ]
    candidate_facts = [
        dict(row)
        for row in db.execute(
            text(
                """
                select id, fact_type, predicate, confidence, extraction_source, created_at
                from source_fact
                where review_status = 'candidate'
                order by created_at desc
                limit 20
                """
            )
        )
        .mappings()
        .all()
    ]
    candidate_events = [
        dict(row)
        for row in db.execute(
            text(
                """
                select id, event_key, event_type, severity, source_strength, review_status, discovered_at
                from geo_event
                where review_status = 'candidate'
                order by discovered_at desc
                limit 20
                """
            )
        )
        .mappings()
        .all()
    ]
    candidates = list_snapshot_candidates(db)
    return {
        "user": {"email": user.email, "role": user.role},
        "metrics": metrics,
        "provider_budgets": budgets,
        "dead_letter_jobs": dead_letters,
        "source_health": source_health,
        "candidate_facts": candidate_facts,
        "candidate_events": candidate_events,
        "snapshot_candidates": candidates,
    }


@router.get("/provider-budgets")
def provider_budgets(
    _: ViewerUser,
    db: DbSession,
):
    return {
        "items": [
            dict(row)
            for row in db.execute(text("select * from provider_budget order by provider_key")).mappings().all()
        ]
    }


@router.post("/provider-budgets/{budget_id}/kill-switch")
def kill_switch(
    budget_id: str,
    payload: dict[str, bool],
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin")
    enabled = bool(payload.get("enabled", True))
    set_kill_switch(db, budget_id=budget_id, enabled=enabled)
    audit(db, user=user, action="provider_budget.kill_switch", target_table="provider_budget", target_pk=budget_id, after={"enabled": enabled})
    db.commit()
    return {"status": "ok", "enabled": enabled}


@router.get("/sources")
def sources(
    _: ViewerUser,
    db: DbSession,
):
    return {"items": [dict(row) for row in db.execute(text("select * from data_source order by source_key")).mappings().all()]}


@router.get("/instruments/search")
def admin_instrument_search(
    _: ViewerUser,
    q: Annotated[str, Query(max_length=64)] = "",
    include_advanced: Annotated[bool, Query()] = True,
    include_inactive: Annotated[bool, Query()] = True,
):
    query = q.strip() or "A"
    return search_instruments(
        query,
        limit=25,
        include_advanced=include_advanced,
        include_inactive=include_inactive,
        context="IMPORT_RECONCILIATION",
    )


@router.get("/instruments/review-requests")
def admin_instrument_review_requests(
    _: ViewerUser,
    db: DbSession,
):
    rows = db.execute(
        text(
            """
            select id, user_id, query, context_screen, optional_notes, status, admin_notes,
                   created_at, updated_at, resolved_at
            from instrument_review_request
            order by created_at desc
            limit 200
            """
        )
    ).mappings().all()
    return {"items": [dict(row) for row in rows]}


@router.post("/instruments/review-requests/{request_id}", responses=BAD_REQUEST_OR_NOT_FOUND_RESPONSES)
def admin_update_instrument_review_request(
    request_id: str,
    payload: InstrumentReviewUpdateRequest,
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin", "editor")
    if payload.status not in {"queued", "in_review", "resolved", "closed", "rejected"}:
        raise HTTPException(status_code=400, detail="Invalid review request status")
    row = db.execute(
        text(
            """
            update instrument_review_request
            set status = :status,
                admin_notes = :admin_notes,
                resolved_by = case when :status in ('resolved','closed','rejected') then :user_id::uuid else resolved_by end,
                resolved_at = case when :status in ('resolved','closed','rejected') then now() else resolved_at end,
                updated_at = now()
            where id = :request_id
            returning id
            """
        ),
        {
            "status": payload.status,
            "admin_notes": payload.admin_notes,
            "user_id": user.id,
            "request_id": request_id,
        },
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Instrument review request not found")
    audit(db, user=user, action="instrument_review_request.update", target_table="instrument_review_request", target_pk=request_id, after=payload.model_dump())
    db.commit()
    return {"status": "ok"}


@router.get("/instruments/{instrument_id}", responses=NOT_FOUND_RESPONSE)
def admin_instrument_detail(
    instrument_id: str,
    _: ViewerUser,
    listing_id: Annotated[str | None, Query(max_length=80)] = None,
):
    payload = instrument_detail(instrument_id, listing_id=listing_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    return payload


@router.post("/instruments/refresh")
def admin_refresh_instruments(
    payload: InstrumentRefreshRequest,
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin")
    refresh_result = refresh_instrument_index(source=payload.source, mode=payload.mode)
    job_id = enqueue_job(
        db,
        job_type="instrument_search_index_update",
        idempotency_key=f"{payload.source}:{payload.mode}",
        payload={"source": payload.source, "mode": payload.mode, "requested_by": user.id},
        priority=10 if payload.priority.upper() == "HIGH" else 50,
    )
    audit(db, user=user, action="instrument.refresh_queued", target_table="job_queue", target_pk=job_id, after=payload.model_dump())
    db.commit()
    return {"status": "refreshed", "job_id": job_id, "refresh": refresh_result}


@router.post("/sources")
def create_source(
    payload: SourceCreate,
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin")
    row_id = db.execute(
        text(
            """
            insert into data_source(source_key, display_name, source_type, base_url)
            values (:source_key, :display_name, :source_type, :base_url)
            returning id
            """
        ),
        payload.model_dump(),
    ).scalar_one()
    audit(db, user=user, action="source.create", target_table="data_source", target_pk=str(row_id), after=payload.model_dump())
    db.commit()
    return {"id": str(row_id)}


@router.post("/ingest/url", responses=BAD_REQUEST_RESPONSE)
async def admin_ingest_url(
    payload: UrlIngestRequest,
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin", "editor")
    try:
        document_id = await ingest_url(db, url=str(payload.url), source_key=payload.source_key)
    except SourceIngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, user=user, action="source_document.ingest_url", target_table="source_document", target_pk=document_id)
    db.commit()
    return {"id": document_id}


@router.post("/summaries/url", responses=ADMIN_SUMMARY_RESPONSES)
async def admin_summarize_url(
    payload: UrlSummaryRequest,
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin")
    _assert_admin_summary_budget(db, user)
    locale = payload.locale if payload.locale in {"en", "ko"} else "en"
    try:
        summary = await summarize_public_url(db, url=str(payload.url), locale=locale, actor_user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit(db, user=user, action="source_document.summarize_url", target_table="source_document", target_pk=str(payload.url))
    db.commit()
    return summary


@router.post("/ingest/file")
def ingest_file_stub(user: CsrfUser):
    _assert_role(user, "owner", "admin", "editor")
    return {"status": "manual_file_ingestion_requires_private_storage_policy"}


@router.get("/source-documents/{document_id}", responses=NOT_FOUND_RESPONSE)
def source_document(
    document_id: str,
    _: ViewerUser,
    db: DbSession,
):
    row = db.execute(text("select * from source_document where id = :id"), {"id": document_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return dict(row)


@router.post("/source-facts/{fact_id}/review", responses=BAD_REQUEST_OR_NOT_FOUND_RESPONSES)
def review_fact(
    fact_id: str,
    payload: ReviewRequest,
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin", "editor")
    if payload.public_allowed:
        fact = db.execute(
            text(
                """
                select fact_type, predicate, object_json
                from source_fact
                where id = :fact_id
                """
            ),
            {"fact_id": fact_id},
        ).mappings().first()
        if not fact:
            raise HTTPException(status_code=404, detail="Fact not found")
        try:
            validate_fact_shape(
                db,
                fact_type=fact["fact_type"],
                predicate=fact["predicate"],
                object_json=fact["object_json"],
            )
        except FactValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.execute(
        text(
            """
            update source_fact
            set review_status = :decision, public_allowed = :public_allowed
            where id = :fact_id
            """
        ),
        {"decision": payload.decision, "public_allowed": payload.public_allowed, "fact_id": fact_id},
    )
    audit(db, user=user, action="source_fact.review", target_table="source_fact", target_pk=fact_id, after=payload.model_dump())
    db.commit()
    return {"status": "ok"}


@router.get("/events/candidates")
def event_candidates(
    _: ViewerUser,
    db: DbSession,
):
    rows = db.execute(
        text(
            """
            select *
            from geo_event
            where review_status = 'candidate'
            order by discovered_at desc
            limit 100
            """
        )
    ).mappings().all()
    return {"items": [dict(row) for row in rows]}


@router.post("/events/{event_id}/review", responses=BAD_REQUEST_OR_NOT_FOUND_RESPONSES)
def review_event(
    event_id: str,
    payload: ReviewRequest,
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin", "editor")
    public_status = "public_candidate" if payload.public_allowed else "not_public"
    if payload.public_allowed:
        event = db.execute(
            text(
                """
                select e.severity, e.source_strength, :decision as review_status,
                       bool_or(s.locale = 'en' and s.public_allowed and not s.stale) as has_en,
                       bool_or(s.locale = 'ko' and s.public_allowed and not s.stale) as has_ko
                from geo_event e
                left join content_summary s on s.source_object_id = e.canonical_object_id
                where e.id = :event_id
                group by e.id, e.severity, e.source_strength
                """
            ),
            {"event_id": event_id, "decision": payload.decision},
        ).mappings().first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        allowed, reason = can_publish_event(
            EventGateInput(
                severity=event["severity"],
                source_strength=event["source_strength"],
                review_status=payload.decision,
                has_en_summary=bool(event["has_en"]),
                has_ko_summary=bool(event["has_ko"]),
                source_keys=["gdelt"] if event["source_strength"] in {"single_discovery", "weak"} else ["canonical"],
            )
        )
        if not allowed:
            raise HTTPException(status_code=400, detail=reason)
    db.execute(
        text(
            """
            update geo_event
            set review_status = :decision, public_status = :public_status
            where id = :event_id
            """
        ),
        {"decision": payload.decision, "public_status": public_status, "event_id": event_id},
    )
    audit(db, user=user, action="geo_event.review", target_table="geo_event", target_pk=event_id, after=payload.model_dump())
    db.commit()
    return {"status": "ok"}


@router.post("/snapshots/build")
def snapshots_build(
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin", "editor")
    job_id = enqueue_job(db, job_type="snapshot_build", idempotency_key="manual_latest", payload={"requested_by": user.id}, priority=10)
    audit(db, user=user, action="snapshot.build_queued", target_table="job_queue", target_pk=job_id)
    db.commit()
    return {"status": "queued", "job_id": job_id}


@router.get("/snapshots/candidates")
def snapshots_candidates(
    _: ViewerUser,
    db: DbSession,
):
    return {"items": list_snapshot_candidates(db)}


@router.post("/snapshots/publish")
def snapshots_publish(
    payload: SnapshotVersionRequest,
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin")
    result = publish_snapshots(db, snapshot_version=payload.snapshot_version, generated_by=user.id)
    audit(db, user=user, action="snapshot.publish", after=result.__dict__)
    db.commit()
    return result.__dict__


@router.post("/snapshots/rollback")
def snapshots_rollback(
    payload: SnapshotVersionRequest,
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin")
    result = rollback_snapshots(db, snapshot_version=payload.snapshot_version, generated_by=user.id)
    audit(db, user=user, action="snapshot.rollback", after=result.__dict__)
    db.commit()
    return result.__dict__


@router.post("/jobs/{job_id}/replay")
def replay_job(
    job_id: str,
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin")
    replay_dead_letter(db, job_id=job_id)
    audit(db, user=user, action="job.replay_dead_letter", target_table="job_queue", target_pk=job_id)
    db.commit()
    return {"status": "ok"}


@router.post("/corrections", responses=BAD_REQUEST_RESPONSE)
def create_correction(
    payload: CorrectionRequest,
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin", "editor")
    if payload.status not in {"correction", "retraction", "clarification"}:
        raise HTTPException(status_code=400, detail="Invalid correction status")
    row_id = db.execute(
        text(
            """
            insert into correction_log(title, summary, status, affected_object_key, published_by)
            values (:title, :summary, :status, :affected_object_key, :published_by)
            returning id
            """
        ),
        {**payload.model_dump(), "published_by": user.id},
    ).scalar_one()
    audit(db, user=user, action="correction.create", target_table="correction_log", target_pk=str(row_id), after=payload.model_dump())
    db.commit()
    return {"id": str(row_id)}


@router.get("/audit-log")
def audit_log(
    _: ViewerUser,
    db: DbSession,
):
    rows = db.execute(
        text(
            """
            select id, actor_role, action, target_table, target_pk, request_id, created_at
            from audit_log
            order by created_at desc
            limit 200
            """
        )
    ).mappings().all()
    return {"items": [dict(row) for row in rows]}


@router.post("/snapshots/build-now-local")
def snapshots_build_now_local(
    user: CsrfUser,
    db: DbSession,
):
    _assert_role(user, "owner", "admin", "editor")
    result = build_candidate_snapshots(db, generated_by=user.id)
    db.commit()
    return result.__dict__


@router.post("/snapshots/build-seed-local")
def snapshots_build_seed_local(
    user: CsrfUser,
):
    _assert_role(user, "owner", "admin", "editor")
    return build_local_seed_snapshots().__dict__


def _count(db: Session, sql: str) -> int:
    try:
        return int(db.execute(text(sql)).scalar_one() or 0)
    except Exception:
        return 0


def _assert_admin_summary_budget(db: Session, user: CurrentUser) -> None:
    settings = get_settings()
    if settings.admin_url_summary_daily_limit <= 0:
        raise HTTPException(status_code=403, detail="Admin URL summaries are disabled")
    used = db.execute(
        text(
            """
            select count(*)
            from llm_invocation
            where actor_user_id = :user_id
              and task_type = 'document_summary'
              and created_at >= date_trunc('day', now())
              and cache_hit = false
            """
        ),
        {"user_id": user.id},
    ).scalar_one()
    if int(used or 0) >= settings.admin_url_summary_daily_limit:
        raise HTTPException(status_code=429, detail="Admin URL summary daily limit reached")


def _assert_role(user: CurrentUser, *roles: str) -> None:
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="Insufficient role")  # NOSONAR - shared admin guard; routes define public behavior.
