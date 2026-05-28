from __future__ import annotations

import base64
import email
import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import zstandard as zstd
from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.core.settings import Settings, get_settings

_LINK_RE = re.compile(r"https?://[^\s<>'\"\\)]+", re.IGNORECASE)
_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid"}


class EmailAlertError(ValueError):
    pass


def email_webhook_signature(secret: str, timestamp: str, nonce: str, body: bytes) -> str:
    payload = timestamp.encode() + b"." + nonce.encode() + b"." + body
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def verify_email_webhook_signature(
    db: Session,
    *,
    headers: dict[str, str],
    body: bytes,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> None:
    settings = settings or get_settings()
    secret = settings.news_email_webhook_secret
    if not secret:
        raise EmailAlertError("email_webhook_disabled")
    lower_headers = {key.lower(): value for key, value in headers.items()}
    timestamp = lower_headers.get("x-stonks-timestamp", "")
    nonce = lower_headers.get("x-stonks-nonce", "")
    signature = lower_headers.get("x-stonks-email-signature", "")
    if not timestamp or not nonce or not signature:
        raise EmailAlertError("missing_signature_headers")
    try:
        timestamp_value = int(timestamp)
    except ValueError as exc:
        raise EmailAlertError("invalid_timestamp") from exc
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if abs(int(current.timestamp()) - timestamp_value) > settings.news_email_signature_max_skew_seconds:
        raise EmailAlertError("stale_signature")
    expected = email_webhook_signature(secret, timestamp, nonce, body)
    received = signature.removeprefix("sha256=")
    if not hmac.compare_digest(expected, received):
        raise EmailAlertError("invalid_signature")
    _reserve_nonce(db, nonce)


def ingest_email_alert(
    db: Session,
    payload: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    recipient = _clean_email(payload.get("to"))
    allowed = settings.news_email_allowed_recipient_list
    if allowed and recipient not in allowed:
        raise EmailAlertError("recipient_not_allowed")

    raw_bytes = _decode_raw_email(payload, settings)
    raw_hash = "sha256:" + hashlib.sha256(raw_bytes or json.dumps(payload, sort_keys=True).encode()).hexdigest()
    message_id = str(payload.get("message_id") or payload.get("messageId") or "").strip()
    duplicate_id = _existing_email_alert_id(db, raw_hash=raw_hash, message_id=message_id)
    if duplicate_id:
        return {"status": "duplicate", "email_alert_id": str(duplicate_id), "raw_hash": raw_hash}

    now = datetime.now(timezone.utc)
    raw_expires_at = now + timedelta(days=settings.news_email_raw_retention_days)
    raw_object_key = _write_raw_archive(raw_bytes, raw_hash, now, settings) if raw_bytes else None
    links = _extract_links(payload, raw_bytes=raw_bytes)
    subject = str(payload.get("subject") or "")[:1000]
    sender = str(payload.get("from") or payload.get("sender") or "")[:1000]
    envelope_from = str(payload.get("envelope_from") or payload.get("envelopeFrom") or sender)[:1000]
    auth_results = payload.get("auth_results") or payload.get("authResults") or {}
    source_document_id = _persist_email_document(
        db,
        recipient=recipient,
        sender=sender,
        subject=subject,
        links=links,
        raw_hash=raw_hash,
        raw_object_key=raw_object_key,
        raw_expires_at=raw_expires_at,
        payload=payload,
    )
    email_alert_id = db.execute(
        text(
            """
            insert into news_email_alert(
              source_document_id, recipient, sender, envelope_from, subject, message_id,
              received_at, raw_hash, raw_object_key, raw_size, raw_expires_at,
              auth_results, links, status, metadata
            )
            values (
              :source_document_id, :recipient, :sender, :envelope_from, :subject, nullif(:message_id, ''),
              :received_at, :raw_hash, :raw_object_key, :raw_size, :raw_expires_at,
              cast(:auth_results as jsonb), cast(:links as jsonb), 'accepted', cast(:metadata as jsonb)
            )
            on conflict do nothing
            returning id
            """
        ),
        {
            "source_document_id": source_document_id,
            "recipient": recipient,
            "sender": sender,
            "envelope_from": envelope_from,
            "subject": subject,
            "message_id": message_id,
            "received_at": _parse_timestamp(payload.get("received_at") or payload.get("receivedAt")) or now,
            "raw_hash": raw_hash,
            "raw_object_key": raw_object_key,
            "raw_size": len(raw_bytes),
            "raw_expires_at": raw_expires_at,
            "auth_results": json.dumps(auth_results if isinstance(auth_results, dict) else {"raw": str(auth_results)}),
            "links": json.dumps(links),
            "metadata": json.dumps(_safe_payload_metadata(payload), default=str),
        },
    ).scalar_one_or_none()
    if not email_alert_id:
        duplicate_id = _existing_email_alert_id(db, raw_hash=raw_hash, message_id=message_id)
        return {"status": "duplicate", "email_alert_id": str(duplicate_id), "raw_hash": raw_hash}
    return {
        "status": "accepted",
        "email_alert_id": str(email_alert_id),
        "source_document_id": str(source_document_id),
        "raw_hash": raw_hash,
        "links": len(links),
        "raw_retention_days": settings.news_email_raw_retention_days,
    }


def purge_expired_raw_email(
    db: Session,
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
    limit: int = 500,
) -> dict[str, int]:
    settings = settings or get_settings()
    now = now or datetime.now(timezone.utc)
    rows = db.execute(
        text(
            """
            select id, source_document_id, raw_object_key
            from news_email_alert
            where raw_object_key is not null
              and raw_expires_at is not null
              and raw_expires_at <= :now
            order by raw_expires_at asc
            limit :limit
            """
        ),
        {"now": now, "limit": max(1, min(limit, 2000))},
    ).mappings()
    purged = 0
    missing = 0
    for row in rows:
        object_key = str(row["raw_object_key"])
        path = Path(settings.news_email_archive_dir) / object_key
        if path.exists():
            path.unlink()
        else:
            missing += 1
        db.execute(
            text(
                """
                update news_email_alert
                set raw_object_key = null, status = 'raw_purged', updated_at = now()
                where id = :id
                """
            ),
            {"id": row["id"]},
        )
        db.execute(
            text(
                """
                update source_document
                set raw_object_key = null, updated_at = now()
                where id = :source_document_id
                """
            ),
            {"source_document_id": row["source_document_id"]},
        )
        purged += 1
    return {"raw_email_purged": purged, "archive_files_missing": missing}


def _reserve_nonce(db: Session, nonce: str) -> None:
    db.execute(
        text("delete from news_email_webhook_nonce where received_at < now() - interval '1 hour'")
    )
    inserted = db.execute(
        text(
            """
            insert into news_email_webhook_nonce(nonce)
            values (:nonce)
            on conflict do nothing
            returning nonce
            """
        ),
        {"nonce": nonce},
    ).scalar_one_or_none()
    if not inserted:
        raise EmailAlertError("replayed_signature_nonce")


def _persist_email_document(
    db: Session,
    *,
    recipient: str,
    sender: str,
    subject: str,
    links: list[str],
    raw_hash: str,
    raw_object_key: str | None,
    raw_expires_at: datetime,
    payload: dict[str, Any],
) -> str:
    source_id = _ensure_email_source(db)
    metadata = {
        "source_key": "company_email_alert",
        "source_type": "company_email",
        "source_name": "Company email alert",
        "retention_class": "raw_email_30d",
        "discovery_only": False,
        "recipient": recipient,
        "sender": sender,
        "links": links,
        "raw_hash": raw_hash,
        "message_id": payload.get("message_id") or payload.get("messageId"),
    }
    document_id = db.execute(
        text(
            """
            insert into source_document(
              source_id, title, original_url, canonical_url, publisher, acquisition_mode,
              acquisition_stack, retention_class, fetched_at, content_hash, dedupe_key,
              raw_object_key, raw_expires_at, legal_risk_level, review_required,
              downstream_ai_allowed, public_allowed, status, metadata
            )
            values (
              :source_id, :title, :url, :url, :publisher, 'company_email_alert',
              'email_router', 'raw_email_30d', now(), :content_hash, :dedupe_key,
              :raw_object_key, :raw_expires_at, 'low', true,
              'extract_only', false, 'discovered', cast(:metadata as jsonb)
            )
            on conflict do nothing
            returning id
            """
        ),
        {
            "source_id": source_id,
            "title": subject or f"Email alert from {sender}",
            "url": links[0] if links else None,
            "publisher": sender or "company_email_alert",
            "content_hash": raw_hash,
            "dedupe_key": f"email:{raw_hash}",
            "raw_object_key": raw_object_key,
            "raw_expires_at": raw_expires_at,
            "metadata": json.dumps(metadata, default=str),
        },
    ).scalar_one_or_none()
    if document_id:
        return str(document_id)
    return str(
        db.execute(
            text("select id from source_document where dedupe_key = :dedupe_key"),
            {"dedupe_key": f"email:{raw_hash}"},
        ).scalar_one()
    )


def _ensure_email_source(db: Session) -> str:
    source_id = db.execute(
        text("select id from data_source where source_key = 'company_email_alert'")
    ).scalar_one_or_none()
    if source_id:
        return str(source_id)
    return str(
        db.execute(
            text(
                """
                insert into data_source(source_key, display_name, source_type, raw_retention_policy)
                values ('company_email_alert', 'Company email alerts', 'company_email', 'raw_email_30d')
                returning id
                """
            )
        ).scalar_one()
    )


def _existing_email_alert_id(db: Session, *, raw_hash: str, message_id: str) -> str | None:
    if message_id:
        row = db.execute(
            text("select id from news_email_alert where raw_hash = :raw_hash or message_id = :message_id"),
            {"raw_hash": raw_hash, "message_id": message_id},
        ).scalar_one_or_none()
    else:
        row = db.execute(
            text("select id from news_email_alert where raw_hash = :raw_hash"),
            {"raw_hash": raw_hash},
        ).scalar_one_or_none()
    return str(row) if row else None


def _decode_raw_email(payload: dict[str, Any], settings: Settings) -> bytes:
    raw_base64 = payload.get("raw_base64") or payload.get("rawBase64") or ""
    if not raw_base64:
        return b""
    try:
        raw_bytes = base64.b64decode(str(raw_base64), validate=True)
    except ValueError as exc:
        raise EmailAlertError("invalid_raw_base64") from exc
    if len(raw_bytes) > settings.news_email_max_raw_bytes:
        raise EmailAlertError("raw_email_too_large")
    return raw_bytes


def _write_raw_archive(raw_bytes: bytes, raw_hash: str, now: datetime, settings: Settings) -> str:
    digest = raw_hash.removeprefix("sha256:")
    object_key = f"{now:%Y/%m/%d}/{digest}.eml.zst"
    path = Path(settings.news_email_archive_dir) / object_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zstd.ZstdCompressor(level=3).compress(raw_bytes))
    return object_key


def _extract_links(payload: dict[str, Any], *, raw_bytes: bytes = b"") -> list[str]:
    parts = [
        str(payload.get("text") or ""),
        str(payload.get("html") or ""),
        " ".join(str(item) for item in payload.get("links") or [] if item),
    ]
    if raw_bytes:
        parts.extend(_raw_email_text_parts(raw_bytes))
    seen: set[str] = set()
    links: list[str] = []
    for match in _LINK_RE.finditer("\n".join(parts)):
        url = _clean_url(match.group(0).rstrip(".,;"))
        if _is_safe_http_url(url) and url not in seen:
            seen.add(url)
            links.append(url)
        if len(links) >= 20:
            break
    return links


def _raw_email_text_parts(raw_bytes: bytes) -> list[str]:
    try:
        message = email.message_from_bytes(raw_bytes)
    except (TypeError, ValueError):
        return []
    parts: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_maintype() != "text":
                continue
            parts.append(_message_part_payload(part))
    elif message.get_content_maintype() == "text":
        parts.append(_message_part_payload(message))
    return [part for part in parts if part]


def _message_part_payload(message: Any) -> str:
    try:
        payload = message.get_payload(decode=True)
    except Exception:
        return ""
    if not isinstance(payload, bytes):
        return ""
    charset = message.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _safe_payload_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"raw_base64", "rawBase64", "html", "text"}
    }


def _clean_email(value: Any) -> str:
    email = str(value or "").strip().lower()
    if "@" not in email:
        raise EmailAlertError("invalid_recipient")
    return email


def _clean_url(value: str) -> str:
    parsed = urlparse(value.strip())
    clean_pairs = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_QUERY_KEYS
        and not key.lower().startswith(_TRACKING_QUERY_PREFIXES)
    ]
    return urlunparse(parsed._replace(query=urlencode(clean_pairs), fragment=""))


def _is_safe_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text_value = str(value).strip()
    if not text_value:
        return None
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
