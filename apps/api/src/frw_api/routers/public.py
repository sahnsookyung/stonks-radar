from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.db.session import get_db
from frw_api.services.market_data import (
    MarketDataInputError,
    MarketDataUnavailable,
    fetch_market_history,
)

router = APIRouter()


@router.get("/health")
def health():
    return {
        "status": "ok",
        "service": "stonks-radar-api",
        "public_read_path": "snapshot-first",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/status")
def status(db: Session = Depends(get_db)):
    metrics = {
        "snapshot_age_minutes": _scalar(db, "select extract(epoch from now() - max(generated_at))/60 from publication_snapshot", 0),
        "dead_letter_jobs": _scalar(db, "select count(*) from job_queue where status = 'dead_letter'", 0),
        "stale_series_count": _scalar(db, "select count(*) from latest_series_state where freshness_status = 'stale'", 0),
        "conflict_count": _scalar(db, "select count(*) from latest_series_state where conflict_present = true", 0),
    }
    return {
        "status": "ok",
        "public_pages_depend_on_backend": False,
        "snapshot_storage": "local_oci",
        "metrics": metrics,
    }


@router.get("/snapshot-manifest-proxy")
def snapshot_manifest_proxy():
    return {"manifest_url": "/public/latest/manifest.json", "mode": "local_oci"}


@router.get("/market/history")
async def market_history(
    symbols: str = Query(min_length=1, max_length=240),
    start: date = Query(),
    end: date = Query(),
):
    try:
        return await fetch_market_history(symbols=[symbols], start=start, end=end)
    except MarketDataInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MarketDataUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"message": str(exc), "providers": exc.provider_status},
        ) from exc


@router.get("/search")
def search(q: str = Query(min_length=2, max_length=80), db: Session = Depends(get_db)):
    rows = (
        db.execute(
            text(
                """
                select object_type, object_key, display_name_en, display_name_ko
                from canonical_object
                where active = true
                  and (
                    display_name_en ilike :needle
                    or display_name_ko ilike :needle
                    or object_key ilike :needle
                  )
                order by object_type, display_name_en
                limit 20
                """
            ),
            {"needle": f"%{q}%"},
        )
        .mappings()
        .all()
    )
    return {"results": [dict(row) for row in rows]}


def _scalar(db: Session, sql: str, default):
    try:
        value = db.execute(text(sql)).scalar_one_or_none()
        return default if value is None else value
    except Exception:
        return default
