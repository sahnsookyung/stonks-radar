from __future__ import annotations

import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.db.session import get_db
from frw_api.services.instruments import instrument_detail, resolve_instrument, search_instruments
from frw_api.services.rate_limit import _client_identity

router = APIRouter()


class InstrumentResolveRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=64)
    name: str | None = Field(default=None, max_length=160)
    exchange: str | None = Field(default=None, max_length=32)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    isin: str | None = Field(default=None, max_length=32)
    context: Literal["HOLDING_ENTRY", "TAX_LOT", "BUILDER", "IMPORT_RECONCILIATION", "CSV_IMPORT"] = "CSV_IMPORT"


class InstrumentReviewCreateRequest(BaseModel):
    query: str = Field(min_length=1, max_length=64)
    context_screen: Literal["HOLDING_ENTRY", "TAX_LOT", "BUILDER", "IMPORT_RECONCILIATION", "CSV_IMPORT"] = "HOLDING_ENTRY"
    optional_notes: str | None = Field(default=None, max_length=500)


@router.get("/search")
def search(
    q: str = Query(min_length=1, max_length=64),
    limit: int = Query(default=10, ge=1, le=25),
    country: str | None = Query(default=None, min_length=2, max_length=64),
    exchange: str | None = Query(default=None, min_length=2, max_length=32),
    asset_class: str | None = Query(default=None, max_length=64),
    instrument_type: str | None = Query(default=None, max_length=64),
    include_advanced: bool = Query(default=False),
    include_inactive: bool = Query(default=False),
    context: Literal["HOLDING_ENTRY", "TAX_LOT", "BUILDER", "IMPORT_RECONCILIATION", "CSV_IMPORT"] = "HOLDING_ENTRY",
):
    try:
        return search_instruments(
            q,
            limit=limit,
            include_advanced=include_advanced,
            include_inactive=include_inactive,
            country=country,
            exchange=exchange,
            asset_class=asset_class,
            instrument_type=instrument_type,
            context=context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/resolve")
def resolve(payload: InstrumentResolveRequest):
    return resolve_instrument(
        symbol=payload.symbol,
        name=payload.name,
        exchange=payload.exchange,
        currency=payload.currency,
        isin=payload.isin,
        context=payload.context,
    )


@router.get("/{instrument_id}")
def detail(instrument_id: str, listing_id: str | None = Query(default=None, max_length=80)):
    payload = instrument_detail(instrument_id, listing_id=listing_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Instrument not found")
    return payload


@router.post("/review-requests")
def create_review_request(
    payload: InstrumentReviewCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    peer = _client_identity(request)
    ip_hash = hashlib.sha256(peer.encode()).hexdigest()
    query = payload.query.strip()
    optional_notes = payload.optional_notes.strip() if payload.optional_notes else None
    existing = db.execute(
        text(
            """
            select id, status
            from instrument_review_request
            where request_ip_hash = :request_ip_hash
              and lower(query) = lower(:query)
              and context_screen = :context_screen
              and status in ('queued', 'in_review')
              and created_at >= now() - interval '1 day'
            order by created_at desc
            limit 1
            """
        ),
        {
            "query": query,
            "context_screen": payload.context_screen,
            "request_ip_hash": ip_hash,
        },
    ).mappings().first()
    if existing is not None:
        return {"id": str(existing["id"]), "status": existing["status"], "deduped": True}

    row_id = db.execute(
        text(
            """
            insert into instrument_review_request(query, context_screen, optional_notes, request_ip_hash)
            values (:query, :context_screen, :optional_notes, :request_ip_hash)
            returning id
            """
        ),
        {
            "query": query,
            "context_screen": payload.context_screen,
            "optional_notes": optional_notes,
            "request_ip_hash": ip_hash,
        },
    ).scalar_one()
    db.commit()
    return {"id": str(row_id), "status": "queued"}
