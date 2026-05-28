from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from frw_api.db.session import get_db
from frw_api.services.news.email_alerts import (
    EmailAlertError,
    ingest_email_alert,
    verify_email_webhook_signature,
)

router = APIRouter()


@router.post("/news/email-alerts")
async def receive_news_email_alert(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    body = await request.body()
    try:
        verify_email_webhook_signature(db, headers=dict(request.headers), body=body)
        try:
            payload = await request.json()
        except ValueError as exc:
            raise EmailAlertError("invalid_json") from exc
        if not isinstance(payload, dict):
            raise EmailAlertError("invalid_payload")
        result = ingest_email_alert(db, payload)
    except EmailAlertError as exc:
        db.rollback()
        raise HTTPException(status_code=_email_error_status(str(exc)), detail=str(exc)) from exc
    db.commit()
    return result


def _email_error_status(reason: str) -> int:
    if reason in {"email_webhook_disabled"}:
        return 503
    if reason in {"invalid_signature", "missing_signature_headers", "stale_signature", "replayed_signature_nonce"}:
        return 401
    if reason in {"recipient_not_allowed"}:
        return 403
    return 400
