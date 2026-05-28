from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from selectolax.parser import HTMLParser
from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.core.settings import get_settings
from frw_api.services.safe_fetch import SafeFetchError, safe_fetch_bytes

ALLOWED_RETENTION = {
    "official_api": "structured_fact_only",
    "official_page": "full_text_open",
    "company_ir": "excerpt_only",
    "filing": "full_text_open",
    "rss_metadata": "metadata_only",
    "public_web_fetch": "metadata_only",
    "metadata_only": "metadata_only",
}


class SourceIngestionError(ValueError):
    pass


async def ingest_url(db: Session, *, url: str, source_key: str | None = None) -> str:
    fetched = await fetch_source_bytes(url)
    body = fetched["body"]
    response = fetched["response"]
    decision_ips = fetched["resolved_ips"]
    final_url = fetched["final_url"]
    content_hash = "sha256:" + hashlib.sha256(body).hexdigest()
    content_type = response.headers.get("content-type", "")
    title = _extract_title(body, content_type) or urlparse(url).netloc
    mode = _mode_for_url(final_url, content_type)
    retention = ALLOWED_RETENTION[mode]
    source_id = _resolve_source(db, source_key, final_url)
    row_id = db.execute(
        text(
            """
            insert into source_document(
              source_id, title, original_url, canonical_url, publisher, acquisition_mode,
              acquisition_stack, retention_class, fetched_at, language, content_hash,
              parse_quality, completeness_score, legal_risk_level, review_required,
              downstream_ai_allowed, public_allowed, status, metadata
            )
            values (
              :source_id, :title, :original_url, :canonical_url, :publisher, :acquisition_mode,
              'httpx+controlled_redirects+selectolax', :retention_class, :fetched_at, :language, :content_hash,
              :parse_quality, :completeness_score, :legal_risk_level, true,
              :downstream_ai_allowed, false, 'fetched', cast(:metadata as jsonb)
            )
            returning id
            """
        ),
        {
            "source_id": source_id,
            "title": title,
            "original_url": url,
            "canonical_url": final_url,
            "publisher": urlparse(final_url).netloc,
            "acquisition_mode": mode,
            "retention_class": retention,
            "fetched_at": datetime.now(timezone.utc),
            "language": None,
            "content_hash": content_hash,
            "parse_quality": 0.7 if "html" in content_type else 0.5,
            "completeness_score": 1.0,
            "legal_risk_level": "low" if mode in ("official_api", "official_page", "filing") else "unknown",
            "downstream_ai_allowed": "extract_only",
            "metadata": json.dumps({
                "content_type": content_type,
                "resolved_ips": decision_ips,
                "bytes": len(body),
                "raw_retained": False,
            }),
        },
    ).scalar_one()
    return str(row_id)


async def fetch_source_bytes(url: str, *, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, object]:
    settings = get_settings()
    try:
        fetched = await safe_fetch_bytes(
            url,
            headers={"User-Agent": settings.sec_user_agent},
            transport=transport,
            max_bytes=settings.source_fetch_max_bytes,
            timeout_seconds=settings.source_fetch_timeout_seconds,
            raise_for_status=True,
        )
    except (SafeFetchError, httpx.HTTPError) as exc:
        raise SourceIngestionError(str(exc)) from exc
    return {
        "body": fetched.body,
        "response": fetched.response,
        "final_url": fetched.final_url,
        "resolved_ips": fetched.resolved_ips,
    }


def _extract_title(body: bytes, content_type: str) -> str | None:
    if "html" not in content_type:
        return None
    parser = HTMLParser(body)
    title = parser.css_first("title")
    if title:
        return title.text(strip=True)[:500]
    h1 = parser.css_first("h1")
    return h1.text(strip=True)[:500] if h1 else None


def _mode_for_url(url: str, content_type: str) -> str:
    host = urlparse(url).netloc.lower()
    if "sec.gov" in host:
        return "filing"
    if any(host.endswith(domain) for domain in (".gov", ".gov.kr", ".go.jp", ".europa.eu")):
        return "official_page" if "html" in content_type else "official_api"
    if "rss" in url.lower() or "xml" in content_type:
        return "rss_metadata"
    return "public_web_fetch"


def _resolve_source(db: Session, source_key: str | None, url: str) -> str | None:
    if source_key:
        return db.execute(
            text("select id from data_source where source_key = :source_key"),
            {"source_key": source_key},
        ).scalar_one_or_none()
    host = urlparse(url).netloc.lower()
    return db.execute(
        text("select id from data_source where base_url ilike :host order by created_at limit 1"),
        {"host": f"%{host}%"},
    ).scalar_one_or_none()
