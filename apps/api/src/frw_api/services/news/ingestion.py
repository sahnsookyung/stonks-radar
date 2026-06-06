from __future__ import annotations

import email.utils
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from xml.etree import ElementTree

import httpx
from sqlalchemy.orm import Session

from frw_api.adapters.base import AdapterResult
from frw_api.core.settings import get_settings
from frw_api.services.ingestion_pipeline import persist_adapter_result
from frw_api.services.news.document_normalizer import normalize_document
from frw_api.services.news.page_reader import (
    detect_denial_reason,
    extract_html_documents,
    headers_for_fetch_profile,
)
from frw_api.services.news.source_registry import SourceProfile, source_enabled, source_registry
from frw_api.services.operation_status import upsert_source_health
from frw_api.services.provider_limits import (
    ERROR_AUTH_INVALID,
    ERROR_FORBIDDEN_SCOPE,
    ERROR_SCHEMA_CHANGED,
    ERROR_TIMEOUT,
    ERROR_UPSTREAM_5XX,
    ProviderLimitError,
    ProviderQuotaGuard,
    provider_error_from_response,
)
from frw_api.services.safe_fetch import SafeFetchError, safe_fetch_bytes


class NewsIngestionError(ValueError):
    pass


@dataclass(frozen=True)
class NewsSourceRequest:
    url: str
    params: dict[str, str]
    headers: dict[str, str]


_SEC_NEWS_FORMS = {
    "8-K",
    "8-K/A",
    "6-K",
    "10-K",
    "10-K/A",
    "10-Q",
    "10-Q/A",
    "20-F",
    "20-F/A",
    "4",
    "4/A",
    "144",
    "SC 13D",
    "SC 13D/A",
    "SC 13G",
    "SC 13G/A",
    "S-1",
    "S-1/A",
    "S-3",
    "S-3/A",
    "424B2",
    "424B3",
    "424B5",
}


async def fetch_news_source(
    db: Session,
    *,
    source_key: str,
    query: str | None = None,
    max_documents: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    profile = source_registry().get(source_key)
    if profile is None:
        raise NewsIngestionError(f"Unknown news source: {source_key}")
    if not source_enabled(profile, settings):
        upsert_source_health(
            db,
            source_key=source_key,
            status="disabled",
            details={"reason": "source_disabled_by_settings"},
        )
        return {
            "source_key": source_key,
            "status": "disabled",
            "documents": 0,
            "persisted": {"documents": 0, "observations": 0, "releases": 0, "source_status": "disabled"},
        }

    limit = max(1, min(max_documents or settings.news_max_documents_per_source_per_run, settings.news_max_documents_per_source_per_run))
    request = build_news_source_request(profile, query=query, max_documents=limit)
    if request is None:
        upsert_source_health(
            db,
            source_key=source_key,
            status="unsupported",
            details={"reason": "no_supported_fetch_request", "source_type": profile.source_type},
        )
        return {
            "source_key": source_key,
            "status": "unsupported",
            "documents": 0,
            "persisted": {"documents": 0, "observations": 0, "releases": 0, "source_status": "unsupported"},
        }

    headers = {
        "Accept": "application/rss+xml, application/atom+xml, application/json;q=0.9, */*;q=0.2",
        "User-Agent": settings.sec_user_agent,
        **headers_for_fetch_profile(profile.fetch_profile, settings.sec_user_agent),
        **request.headers,
    }
    try:
        response = await _fetch_limited_provider_response(
            provider_key=profile.rate_limit_provider_key,
            endpoint_key=profile.rate_limit_endpoint_key,
            db=db,
            idempotency_key=_request_idempotency_key(source_key, request),
            max_bytes=settings.source_fetch_max_bytes,
            timeout_seconds=settings.source_fetch_timeout_seconds,
            headers=headers,
            url=request.url,
            params=request.params or None,
            transport=transport,
        )
    except ProviderLimitError as exc:
        if exc.error_class in {ERROR_AUTH_INVALID, ERROR_FORBIDDEN_SCOPE} and profile.rate_limit_provider_key == "company_ir":
            upsert_source_health(
                db,
                source_key=source_key,
                status="denied",
                error=exc.error_class,
                details={
                    "reason": exc.error_class,
                    "fetch_kind": profile.fetch_kind,
                    "status_code": exc.status_code,
                    "source_type": profile.source_type,
                },
            )
            return {
                "source_key": source_key,
                "status": "denied",
                "documents": 0,
                "persisted": {"documents": 0, "observations": 0, "releases": 0, "source_status": "denied"},
                "denial_reason": exc.error_class,
            }
        raise

    response_text = response.content.decode(response.encoding or "utf-8", errors="replace")
    denial_reason = detect_denial_reason(
        response.status_code,
        response.headers.get("content-type", ""),
        response_text,
    )
    if denial_reason:
        upsert_source_health(
            db,
            source_key=source_key,
            status="denied",
            error=denial_reason,
            details={
                "reason": denial_reason,
                "source_type": profile.source_type,
                "fetch_kind": profile.fetch_kind,
                "status_code": response.status_code,
            },
        )
        return {
            "source_key": source_key,
            "status": "denied",
            "documents": 0,
            "persisted": {"documents": 0, "observations": 0, "releases": 0, "source_status": "denied"},
            "denial_reason": denial_reason,
        }

    documents = parse_news_response(profile, response, max_documents=limit)
    adapter_result = AdapterResult(
        source_key=profile.source_key,
        object_key=f"news:{profile.source_key}",
        observations=[],
        releases=[],
        documents=documents,
        unsupported=[] if documents else ["no_documents_parsed"],
    )
    persisted = persist_adapter_result(db, adapter_result)
    return {
        "source_key": profile.source_key,
        "status": "ready" if documents else "empty",
        "documents": len(documents),
        "persisted": persisted,
        "trust_tier": profile.trust_tier,
        "copyright_mode": profile.copyright_mode,
    }


def build_news_source_request(
    profile: SourceProfile,
    *,
    query: str | None = None,
    max_documents: int = 100,
) -> NewsSourceRequest | None:
    if profile.source_key == "google_news_rss" or profile.fetch_kind == "google_news_search":
        return NewsSourceRequest(
            url="https://news.google.com/rss/search",
            params={
                "q": query or profile.default_query or "financial markets",
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            },
            headers={},
        )
    if profile.fetch_kind == "sec_submissions" and profile.feed_url:
        return NewsSourceRequest(
            url=profile.feed_url,
            params={},
            headers={"Accept": "application/json"},
        )
    if profile.source_key == "gdelt":
        return NewsSourceRequest(
            url="https://api.gdeltproject.org/api/v2/doc/doc",
            params={
                "query": query or profile.default_query or "financial markets",
                "mode": "ArtList",
                "format": "json",
                "maxrecords": str(min(max_documents, 250)),
                "sort": "DateDesc",
            },
            headers={"Accept": "application/json"},
        )
    if profile.feed_url:
        headers = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.3"} if profile.fetch_kind == "html_index" else {}
        return NewsSourceRequest(url=profile.feed_url, params={}, headers=headers)
    return None


def parse_news_response(
    profile: SourceProfile,
    response: httpx.Response,
    *,
    max_documents: int,
) -> list[dict[str, Any]]:
    content_type = response.headers.get("content-type", "")
    body = response.content
    if len(body) > get_settings().source_fetch_max_bytes:
        raise NewsIngestionError("News response exceeded SOURCE_FETCH_MAX_BYTES")
    text = body.decode(response.encoding or "utf-8", errors="replace")
    if profile.fetch_kind == "sec_submissions":
        try:
            payload = response.json()
        except ValueError:
            return []
        return _parse_sec_submissions_json(profile, payload, max_documents=max_documents)
    if "json" in content_type or text.lstrip().startswith("{"):
        try:
            payload = response.json()
        except ValueError:
            return []
        return _parse_gdelt_json(profile, payload, max_documents=max_documents)
    if profile.fetch_kind == "html_index" or "html" in content_type:
        return [
            _normalized_document_dict(profile, row)
            for row in extract_html_documents(
                profile,
                url=_response_url(response, profile),
                html=text,
                max_documents=max_documents,
            )
        ]
    return _parse_feed_xml(profile, body, max_documents=max_documents)


def _parse_sec_submissions_json(
    profile: SourceProfile,
    payload: dict[str, Any],
    *,
    max_documents: int,
) -> list[dict[str, Any]]:
    recent = payload.get("filings", {}).get("recent") if isinstance(payload, dict) else None
    if not isinstance(recent, dict):
        return []
    accessions = _sec_array(recent, "accessionNumber")
    forms = _sec_array(recent, "form")
    filing_dates = _sec_array(recent, "filingDate")
    report_dates = _sec_array(recent, "reportDate")
    primary_documents = _sec_array(recent, "primaryDocument")
    descriptions = _sec_array(recent, "primaryDocDescription")
    cik = str(payload.get("cik") or "").strip()
    entity_name = str(payload.get("name") or "").strip()
    symbol = profile.symbols[0] if profile.symbols else entity_name
    documents: list[dict[str, Any]] = []
    for idx, accession in enumerate(accessions):
        if len(documents) >= max_documents:
            break
        form = _sec_value(forms, idx).upper()
        if form not in _SEC_NEWS_FORMS:
            continue
        primary_document = _sec_value(primary_documents, idx)
        url = _sec_filing_url(cik, accession, primary_document)
        if not url:
            continue
        filing_date = _sec_value(filing_dates, idx)
        report_date = _sec_value(report_dates, idx)
        description = _sec_value(descriptions, idx) or primary_document
        title = f"{symbol} {form}: {description}".strip()
        documents.append(
            _normalized_document_dict(
                profile,
                {
                    "title": title,
                    "url": url,
                    "canonical_url": url,
                    "snippet": "; ".join(
                        part
                        for part in (
                            f"SEC {form} filing",
                            f"filed {filing_date}" if filing_date else "",
                            f"report date {report_date}" if report_date else "",
                            entity_name,
                        )
                        if part
                    ),
                    "published_at": filing_date,
                    "source_region": profile.region_coverage[0] if profile.region_coverage else "USA",
                    "language": "en",
                },
            )
        )
    return documents


def _parse_gdelt_json(profile: SourceProfile, payload: dict[str, Any], *, max_documents: int) -> list[dict[str, Any]]:
    rows = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    documents: list[dict[str, Any]] = []
    for row in rows[:max_documents]:
        if not isinstance(row, dict):
            continue
        language = str(row.get("language") or "").strip().lower()
        if language and language not in {"english", "en"}:
            continue
        title = str(row.get("title") or "").strip()
        url = str(row.get("url") or "").strip()
        if not title or not _is_safe_http_url(url):
            continue
        documents.append(
            _normalized_document_dict(
                profile,
                {
                    "title": title,
                    "url": url,
                    "canonical_url": url,
                    "snippet": row.get("seendate") or row.get("domain") or "",
                    "published_at": _gdelt_datetime(str(row.get("seendate") or "")),
                    "source_region": row.get("sourcecountry"),
                    "language": row.get("language"),
                },
            )
        )
    return documents


def _parse_feed_xml(profile: SourceProfile, body: bytes, *, max_documents: int) -> list[dict[str, Any]]:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return []
    documents: list[dict[str, Any]] = []
    items = root.findall(".//item")
    if items:
        for item in items[:max_documents]:
            title = _xml_text(item, "title")
            url = _xml_text(item, "link")
            if not title or not _is_safe_http_url(url):
                continue
            documents.append(
                _normalized_document_dict(
                    profile,
                    {
                        "title": title,
                        "url": url,
                        "canonical_url": url,
                        "snippet": _xml_text(item, "description"),
                        "published_at": _email_datetime(_xml_text(item, "pubDate")),
                        "source_region": profile.region_coverage[0] if profile.region_coverage else None,
                    },
                )
            )
        return documents

    atom_entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for entry in atom_entries[:max_documents]:
        title = _xml_text(entry, "{http://www.w3.org/2005/Atom}title")
        url = _atom_link(entry)
        if not title or not _is_safe_http_url(url):
            continue
        documents.append(
            _normalized_document_dict(
                profile,
                {
                    "title": title,
                    "url": url,
                    "canonical_url": url,
                    "snippet": _xml_text(entry, "{http://www.w3.org/2005/Atom}summary"),
                    "published_at": _xml_text(entry, "{http://www.w3.org/2005/Atom}updated"),
                    "source_region": profile.region_coverage[0] if profile.region_coverage else None,
                },
            )
        )
    return documents


def _normalized_document_dict(profile: SourceProfile, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_document(
        {
            **payload,
            "source_key": profile.source_key,
            "source_region": payload.get("source_region") or (profile.region_coverage[0] if profile.region_coverage else None),
        }
    )
    return {
        "title": normalized.title,
        "url": normalized.url,
        "canonical_url": normalized.canonical_url,
        "source_key": normalized.source_key,
        "published_at": normalized.published_at.isoformat() if normalized.published_at else None,
        "fetched_at": normalized.fetched_at.isoformat(),
        "language": normalized.language,
        "snippet": normalized.snippet,
        "source_region": normalized.source_region,
        "raw_hash": "sha256:" + normalized.raw_hash,
        "normalized_hash": "sha256:" + normalized.normalized_hash,
        "trust_tier": profile.trust_tier,
        "copyright_mode": profile.copyright_mode,
        "discovery_only": profile.discovery_only,
        "retention_class": profile.retention_class,
        "source_type": profile.source_type,
        "source_name": profile.source_name,
        "symbols": list(profile.symbols),
        "entity_type": profile.entity_type,
        "fetch_profile": profile.fetch_profile,
        "dedupe_key": "news:"
        + hashlib.sha256(
            "|".join(
                [
                    profile.source_key,
                    normalized.canonical_url,
                    normalized.title,
                    normalized.published_at.isoformat() if normalized.published_at else "",
                ]
            ).encode()
        ).hexdigest(),
    }


async def _fetch_limited_provider_response(
    *,
    provider_key: str,
    endpoint_key: str,
    db: Session | None,
    idempotency_key: str,
    max_bytes: int,
    timeout_seconds: int,
    headers: dict[str, str],
    url: str,
    params: dict[str, str] | None,
    transport: httpx.AsyncBaseTransport | None,
) -> httpx.Response:
    guard = ProviderQuotaGuard.default()
    reservation = guard.reserve(
        provider_key=provider_key,
        endpoint_key=endpoint_key,
        units=None,
        partition_key="scheduled_public",
        idempotency_key=idempotency_key,
        db=db,
    )
    try:
        fetched = await safe_fetch_bytes(
            _url_with_params(url, params),
            headers=headers,
            transport=transport,
            max_bytes=max_bytes,
            timeout_seconds=timeout_seconds,
            raise_for_status=False,
        )
        response = fetched.response
        provider_error = provider_error_from_response(response, provider_key, endpoint_key)
        if provider_error is not None:
            guard.finalize(
                reservation,
                status="failed",
                db=db,
                error_class=provider_error.error_class,
                status_code=response.status_code,
                retry_after_seconds=provider_error.retry_after_seconds,
            )
            raise provider_error
        guard.finalize(reservation, status="succeeded", db=db, status_code=response.status_code)
        return response
    except SafeFetchError as exc:
        details = {"reason": "safe_fetch_rejected", "message": str(exc)}
        if "exceeded" in str(exc).lower():
            details = {"reason": "response_too_large", "max_bytes": max_bytes}
        guard.finalize(
            reservation,
            status="failed",
            db=db,
            error_class=ERROR_SCHEMA_CHANGED,
            details=details,
        )
        raise ProviderLimitError(
            f"{provider_key}/{endpoint_key} safe fetch rejected: {exc}",
            error_class=ERROR_SCHEMA_CHANGED,
            provider_key=provider_key,
            endpoint_key=endpoint_key,
        ) from exc
    except httpx.TimeoutException as exc:
        guard.finalize(reservation, status="failed", db=db, error_class=ERROR_TIMEOUT, retry_after_seconds=30)
        raise ProviderLimitError(
            f"{provider_key}/{endpoint_key} timed out",
            error_class=ERROR_TIMEOUT,
            provider_key=provider_key,
            endpoint_key=endpoint_key,
            retry_after_seconds=30,
        ) from exc
    except httpx.TransportError as exc:
        guard.finalize(reservation, status="failed", db=db, error_class=ERROR_UPSTREAM_5XX, retry_after_seconds=60)
        raise ProviderLimitError(
            f"{provider_key}/{endpoint_key} transport error",
            error_class=ERROR_UPSTREAM_5XX,
            provider_key=provider_key,
            endpoint_key=endpoint_key,
            retry_after_seconds=60,
        ) from exc


def _request_idempotency_key(source_key: str, request: NewsSourceRequest) -> str:
    encoded = f"{source_key}|{request.url}|{urlencode(sorted(request.params.items()))}"
    return "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()


def _url_with_params(url: str, params: dict[str, str] | None) -> str:
    if not params:
        return url
    parsed = urlparse(url)
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    query_items.extend(sorted(params.items()))
    return urlunparse(parsed._replace(query=urlencode(query_items)))


def _response_url(response: httpx.Response, profile: SourceProfile) -> str:
    try:
        url = str(response.url)
    except RuntimeError:
        url = profile.feed_url or profile.base_url
    return url or profile.feed_url or profile.base_url


def _is_safe_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _xml_text(element: ElementTree.Element, tag: str) -> str:
    child = element.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _atom_link(element: ElementTree.Element) -> str:
    for link in element.findall("{http://www.w3.org/2005/Atom}link"):
        href = link.attrib.get("href")
        if href:
            return href.strip()
    return ""


def _sec_array(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    return value if isinstance(value, list) else []


def _sec_value(values: list[Any], index: int) -> str:
    if index >= len(values):
        return ""
    return str(values[index] or "").strip()


def _sec_filing_url(cik: str, accession: str, primary_document: str) -> str:
    if not cik or not accession or not primary_document:
        return ""
    try:
        cik_no_leading = str(int(cik))
    except ValueError:
        return ""
    accession_clean = accession.replace("-", "")
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik_no_leading}/{accession_clean}/{primary_document}"
    )


def _email_datetime(value: str) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _gdelt_datetime(value: str) -> str | None:
    if not value:
        return None
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return None
