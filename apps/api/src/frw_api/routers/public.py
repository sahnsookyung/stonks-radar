from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path as ApiPath, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.db.session import get_db
from frw_api.services.provider_limits import provider_limits_snapshot
from frw_api.services.market_data import (
    MarketDataInputError,
    MarketDataUnavailable,
    fetch_market_history,
)
from frw_api.services.trump_disclosures import (
    disclosure_summary_response,
    entity_insiders_response,
    filings_response,
    transactions_response,
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
        "quota_wait_jobs": _scalar(db, "select count(*) from job_queue where status = 'quota_wait'", 0),
        "open_provider_circuits": _scalar(
            db,
            "select count(*) from provider_runtime_state where circuit_state = 'open'",
            0,
        ),
        "stale_series_count": _scalar(db, "select count(*) from latest_series_state where freshness_status = 'stale'", 0),
        "conflict_count": _scalar(db, "select count(*) from latest_series_state where conflict_present = true", 0),
    }
    return {
        "status": "ok",
        "public_pages_depend_on_backend": False,
        "snapshot_storage": "local_oci",
        "metrics": metrics,
    }


@router.get("/provider-status")
def provider_status():
    providers = provider_limits_snapshot()
    market_data_provider_keys = {"twelve_data", "alpha_vantage", "fmp", "finnhub", "marketdata_app"}
    return {
        "status": "ok",
        "market_data_providers": [
            _public_provider_status(item)
            for item in providers
            if item["provider_key"] in market_data_provider_keys
        ],
    }


@router.get("/snapshot-manifest-proxy")
def snapshot_manifest_proxy():
    return {"manifest_url": "/public/latest/manifest.json", "mode": "local_oci"}


@router.get("/trump-disclosures/summary")
def trump_disclosures_summary(
    limit: int = Query(default=50, ge=1, le=250),
    db: Session = Depends(get_db),
):
    return disclosure_summary_response(db, limit=limit)


@router.get("/filings")
def filings(
    person: str | None = Query(default=None, min_length=2, max_length=120),
    ticker: str | None = Query(default=None, min_length=1, max_length=16),
    source: str | None = Query(default=None, pattern="^(OGE|SEC|oge|sec)$"),
    limit: int = Query(default=100, ge=1, le=250),
    db: Session = Depends(get_db),
):
    return filings_response(db, person=person, ticker=ticker, source=source, limit=limit)


@router.get("/transactions")
def transactions(
    person: str | None = Query(default=None, min_length=2, max_length=120),
    ticker: str | None = Query(default=None, min_length=1, max_length=16),
    source: str | None = Query(default=None, pattern="^(OGE|SEC|oge|sec)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return transactions_response(db, person=person, ticker=ticker, source=source, limit=limit)


@router.get("/entities/{ticker}/insiders")
def entity_insiders(
    ticker: str = ApiPath(pattern=r"^[A-Za-z0-9.\-]{1,16}$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return entity_insiders_response(db, ticker=ticker, limit=limit)


@router.get("/market/history")
async def market_history(
    symbols: str = Query(min_length=1, max_length=240),
    start: date = Query(),
    end: date = Query(),
    db: Session = Depends(get_db),
):
    try:
        payload = await fetch_market_history(symbols=[symbols], start=start, end=end, db=db)
        db.commit()
        return payload
    except MarketDataInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MarketDataUnavailable as exc:
        db.commit()
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


def _public_provider_status(item: dict) -> dict:
    return {
        "provider_key": item["provider_key"],
        "endpoint_key": item["endpoint_key"],
        "public_display_allowed": item["public_display_allowed"],
        "attribution_required": item["attribution_required"],
        "refresh_interval": _coarsest_refresh_interval(item.get("rules", [])),
        "source_checked_at": item["source_checked_at"],
    }


def _coarsest_refresh_interval(rules: list[dict]) -> str:
    request_rules = [
        rule for rule in rules if rule.get("unit") == "request" and rule.get("window_seconds")
    ]
    if not request_rules:
        return "policy-defined"
    rule = max(request_rules, key=lambda item: int(item.get("window_seconds") or 0))
    window_seconds = int(rule.get("window_seconds") or 0)
    limit = float(rule.get("limit") or 0)
    if window_seconds <= 0 or limit <= 0:
        return "policy-defined"
    seconds_per_request = max(1, round(window_seconds / limit))
    if seconds_per_request < 60:
        return f"at most every {seconds_per_request}s"
    minutes = round(seconds_per_request / 60)
    if minutes < 60:
        return f"at most every {minutes}m"
    hours = round(minutes / 60)
    return f"at most every {hours}h"


def _scalar(db: Session, sql: str, default):
    try:
        value = db.execute(text(sql)).scalar_one_or_none()
        return default if value is None else value
    except Exception:
        return default
