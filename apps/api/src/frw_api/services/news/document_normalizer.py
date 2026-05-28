from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class SourceDocument:
    title: str
    url: str
    canonical_url: str
    source_key: str
    published_at: datetime | None
    fetched_at: datetime
    language: str | None
    snippet: str
    source_region: str | None
    raw_hash: str
    normalized_hash: str


def normalize_document(payload: dict[str, Any], *, fetched_at: datetime | None = None) -> SourceDocument:
    fetched = fetched_at or datetime.now(timezone.utc)
    title = _clean_text(str(payload.get("title") or ""))
    snippet = _clean_text(str(payload.get("snippet") or payload.get("summary") or ""))
    url = str(payload.get("url") or payload.get("link") or "").strip()
    canonical_url = str(payload.get("canonical_url") or url).strip()
    source_key = str(payload.get("source_key") or "unknown").strip()
    language = str(payload.get("language") or "").strip() or None
    source_region = str(payload.get("source_region") or "").strip() or None
    published_at = _parse_datetime(payload.get("published_at"))
    raw_fingerprint = f"{title}|{url}|{payload.get('raw_hash') or ''}"
    normalized_fingerprint = f"{title.lower()}|{canonical_url.lower()}|{source_key}"
    return SourceDocument(
        title=title[:280],
        url=url,
        canonical_url=canonical_url,
        source_key=source_key,
        published_at=published_at,
        fetched_at=fetched,
        language=language,
        snippet=snippet[:500],
        source_region=source_region,
        raw_hash=_sha256(raw_fingerprint),
        normalized_hash=_sha256(normalized_fingerprint),
    )


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()
