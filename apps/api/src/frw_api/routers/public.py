from __future__ import annotations

import json
import os
import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path as ApiPath, Query
from fastapi.responses import JSONResponse
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
ROOT = Path(__file__).resolve().parents[5]
DEFAULT_PUBLISHED_ROOT = ROOT / "apps" / "web" / "public" / "public"
DbSession = Annotated[Session, Depends(get_db)]
MARKET_HISTORY_RESPONSES = {
    400: {"description": "Invalid market-history request"},
    503: {"description": "Approved historical market data is unavailable"},
}


@router.get("/health")
def health():
    return {
        "status": "ok",
        "service": "stonks-radar-api",
        "public_read_path": "snapshot-first",
        "time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/status")
def status(db: DbSession):
    published_manifest = _published_manifest_status()
    db_snapshot_age = _scalar(
        db, "select extract(epoch from now() - max(generated_at))/60 from publication_snapshot", 0
    )
    metrics = {
        "snapshot_age_minutes": published_manifest["age_minutes"]
        if published_manifest
        else db_snapshot_age,
        "published_file_snapshot_age_minutes": published_manifest["age_minutes"]
        if published_manifest
        else None,
        "published_file_generated_at": published_manifest["generated_at"]
        if published_manifest
        else None,
        "db_snapshot_age_minutes": db_snapshot_age,
        "dead_letter_jobs": _scalar(
            db, "select count(*) from job_queue where status = 'dead_letter'", 0
        ),
        "quota_wait_jobs": _scalar(
            db, "select count(*) from job_queue where status = 'quota_wait'", 0
        ),
        "open_provider_circuits": _scalar(
            db,
            "select count(*) from provider_runtime_state where circuit_state = 'open'",
            0,
        ),
        "stale_series_count": _scalar(
            db, "select count(*) from latest_series_state where freshness_status = 'stale'", 0
        ),
        "conflict_count": _scalar(
            db, "select count(*) from latest_series_state where conflict_present = true", 0
        ),
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
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=250)] = 50,
):
    return disclosure_summary_response(db, limit=limit)


@router.get("/filings")
def filings(
    db: DbSession,
    person: Annotated[str | None, Query(min_length=2, max_length=120)] = None,
    ticker: Annotated[str | None, Query(min_length=1, max_length=16)] = None,
    source: Annotated[str | None, Query(pattern="^(OGE|SEC|oge|sec)$")] = None,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
):
    return filings_response(db, person=person, ticker=ticker, source=source, limit=limit)


@router.get("/transactions")
def transactions(
    db: DbSession,
    person: Annotated[str | None, Query(min_length=2, max_length=120)] = None,
    ticker: Annotated[str | None, Query(min_length=1, max_length=16)] = None,
    source: Annotated[str | None, Query(pattern="^(OGE|SEC|oge|sec)$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    return transactions_response(db, person=person, ticker=ticker, source=source, limit=limit)


@router.get("/entities/{ticker}/insiders")
def entity_insiders(
    db: DbSession,
    ticker: Annotated[str, ApiPath(pattern=r"^[A-Za-z0-9.\-]{1,16}$")],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    return entity_insiders_response(db, ticker=ticker, limit=limit)


@router.get("/market/history", responses=MARKET_HISTORY_RESPONSES)
async def market_history(
    db: DbSession,
    symbols: Annotated[str, Query(min_length=1, max_length=240)],
    start: Annotated[date, Query()],
    end: Annotated[date, Query()],
):
    try:
        payload = await fetch_market_history(
            symbols=[symbols], start=start, end=end, db=db, public_only=True
        )
        db.commit()
        return JSONResponse(payload, headers=_market_history_cache_headers(payload))
    except MarketDataInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MarketDataUnavailable as exc:
        db.commit()
        raise HTTPException(
            status_code=503,
            detail={"message": str(exc), "providers": exc.provider_status},
        ) from exc


@router.get("/search")
def search(db: DbSession, q: Annotated[str, Query(min_length=2, max_length=80)]):
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


def _market_history_cache_headers(payload: dict) -> dict[str, str]:
    if payload.get("display_mode") != "public":
        return {"Cache-Control": "no-store"}
    if payload.get("status") == "license_limited":
        return {
            "Cache-Control": "no-store",
            "X-Market-Data-Source": "license-limited",
        }
    if payload.get("status") != "ok":
        return {"Cache-Control": "no-store"}
    cache_key = {
        "status": payload.get("status"),
        "symbols": payload.get("symbols"),
        "start": payload.get("start"),
        "end": payload.get("end"),
        "version": payload.get("market_data_version"),
        "snapshot_id": payload.get("market_data_snapshot_id"),
        "provider": payload.get("provider"),
    }
    digest = hashlib.sha256(
        json.dumps(cache_key, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {
        "Cache-Control": "public, max-age=300, s-maxage=900, stale-while-revalidate=300",
        "ETag": f'"market-history-{digest[:24]}"',
        "Vary": "Accept-Encoding",
        "X-Market-Data-Source": "stored-snapshot",
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


def _published_manifest_status() -> dict | None:
    root = Path(os.getenv("PUBLISHED_SNAPSHOT_DIR", str(DEFAULT_PUBLISHED_ROOT)))
    manifest_path = root / "latest" / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text())
        generated_at = _parse_datetime(str(manifest.get("generated_at", "")))
    except (OSError, ValueError, TypeError):
        return None
    if generated_at is None:
        return None
    age_minutes = max(0.0, (datetime.now(timezone.utc) - generated_at).total_seconds() / 60)
    return {
        "age_minutes": age_minutes,
        "generated_at": generated_at.isoformat(),
        "path": str(manifest_path),
    }


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _scalar(db: Session, sql: str, default):
    try:
        value = db.execute(text(sql)).scalar_one_or_none()
        return default if value is None else value
    except Exception:
        return default
