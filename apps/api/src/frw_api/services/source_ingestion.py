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
from frw_api.services.fetch_policy import evaluate_url, redirect_url

MAX_REDIRECTS = 5

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
    decision = evaluate_url(url)
    if not decision.allowed:
        raise SourceIngestionError(decision.reason)
    settings = get_settings()
    current_url = url
    all_resolved_ips = set(decision.resolved_ips)
    redirects = 0
    async with httpx.AsyncClient(
        timeout=settings.source_fetch_timeout_seconds,
        follow_redirects=False,
        headers={"User-Agent": settings.sec_user_agent},
        trust_env=False,
        transport=transport,
    ) as client:
        while True:
            decision = evaluate_url(current_url)
            if not decision.allowed:
                raise SourceIngestionError(decision.reason)
            all_resolved_ips.update(decision.resolved_ips)
            async with client.stream("GET", current_url) as response:
                if response.is_redirect:
                    redirects += 1
                    if redirects > MAX_REDIRECTS:
                        raise SourceIngestionError("Too many redirects")
                    location = response.headers.get("location")
                    if not location:
                        raise SourceIngestionError("Redirect response missing Location header")
                    current_url = redirect_url(current_url, location)
                    continue
                response.raise_for_status()
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > settings.source_fetch_max_bytes:
                        raise SourceIngestionError("Response exceeded SOURCE_FETCH_MAX_BYTES")
                    chunks.append(chunk)
                body = b"".join(chunks)
                return {
                    "body": body,
                    "response": response,
                    "final_url": str(response.url),
                    "resolved_ips": sorted(all_resolved_ips),
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
