from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx
from selectolax.parser import HTMLParser
from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.core.settings import get_settings
from frw_api.services.news.source_registry import source_registry
from frw_api.services.provider_limits import (
    ERROR_SCHEMA_CHANGED,
    ERROR_TIMEOUT,
    ERROR_UPSTREAM_5XX,
    ProviderLimitError,
    ProviderQuotaGuard,
    provider_error_from_response,
)
from frw_api.services.safe_fetch import SafeFetchError, safe_fetch_bytes

_SAFARI_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
)
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid"}
_DENIAL_SIGNATURES = (
    ("cloudflare_challenge", "cf-chl-"),
    ("cloudflare_challenge", "checking if the site connection is secure"),
    ("access_denied", "access denied"),
    ("access_denied", "request blocked"),
    ("access_denied", "temporarily unavailable"),
    ("captcha", "verify you are human"),
    ("akamai_challenge", "reference #"),
    ("forbidden", "403 forbidden"),
    ("bot_detection", "unusual traffic"),
)
_LINK_KEYWORDS = (
    "announce",
    "announces",
    "award",
    "awarded",
    "contract",
    "earnings",
    "financial",
    "launch",
    "mission",
    "news",
    "press",
    "release",
    "reports",
    "results",
    "updates",
)
_GENERIC_LINK_TITLES = {
    "blog",
    "events",
    "news",
    "newsroom",
    "press releases",
    "professional services",
}


@dataclass(frozen=True)
class PageReadOutcome:
    read: int = 0
    denied: int = 0


def headers_for_fetch_profile(profile_name: str, default_user_agent: str) -> dict[str, str]:
    user_agent = default_user_agent
    if profile_name == "safari":
        user_agent = _SAFARI_UA
    elif profile_name == "ir_vendor":
        user_agent = _CHROME_UA
    return {
        "User-Agent": user_agent,
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }


def detect_denial_reason(status_code: int, content_type: str, body_text: str) -> str | None:
    if status_code in {401, 403, 451}:
        return f"http_{status_code}"
    if status_code == 429:
        return "rate_limited"
    if "text/html" not in content_type.lower() and status_code < 400:
        return None
    lowered = body_text[:20_000].lower()
    for reason, signature in _DENIAL_SIGNATURES:
        if signature in lowered:
            return reason
    return None


def extract_html_documents(
    profile: Any,
    *,
    url: str,
    html: str,
    max_documents: int,
) -> list[dict[str, Any]]:
    parser = HTMLParser(html)
    documents: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    page_title = _node_text(parser.css_first("title")) or _node_text(parser.css_first("h1"))
    host = urlparse(url).netloc.lower()

    for node in parser.css("a"):
        if len(documents) >= max_documents:
            break
        document = _document_from_anchor(
            profile,
            node,
            page_url=url,
            page_host=host,
            page_title=page_title,
            seen_urls=seen_urls,
        )
        if document is not None:
            documents.append(document)

    if (
        not documents
        and page_title
        and profile.fetch_kind == "html_article"
        and not _looks_like_error_page(page_title)
    ):
        excerpt = _first_paragraph(parser)
        documents.append(
            {
                "title": page_title[:500],
                "url": _clean_url(url),
                "canonical_url": _clean_url(url),
                "snippet": excerpt,
                "published_at": None,
                "source_region": profile.region_coverage[0] if profile.region_coverage else None,
            }
        )
    return documents[:max_documents]


def _document_from_anchor(
    profile: Any,
    node: Any,
    *,
    page_url: str,
    page_host: str,
    page_title: str,
    seen_urls: set[str],
) -> dict[str, Any] | None:
    title = _clean_anchor_text(_node_text(node))
    href = str(node.attributes.get("href") or "").strip()
    if len(title) < 8 or _generic_anchor_title(title) or not href:
        return None
    resolved = _clean_url(urljoin(page_url, href))
    if not _anchor_url_allowed(profile, page_url, page_host, resolved, seen_urls):
        return None
    if title.lower().startswith("read our announcement"):
        title = _title_from_url(resolved)
        if len(title) < 8:
            return None
    if not _looks_like_news_link(title, resolved):
        return None
    seen_urls.add(resolved)
    return {
        "title": title[:500],
        "url": resolved,
        "canonical_url": resolved,
        "snippet": page_title or title,
        "published_at": None,
        "source_region": profile.region_coverage[0] if profile.region_coverage else None,
    }


def _anchor_url_allowed(
    profile: Any, page_url: str, page_host: str, resolved: str, seen_urls: set[str]
) -> bool:
    if not _is_safe_http_url(resolved) or resolved in seen_urls:
        return False
    if urlparse(resolved).path.rstrip("/") == urlparse(page_url).path.rstrip("/"):
        return False
    parsed = urlparse(resolved)
    if parsed.netloc.lower() != page_host and not _official_domain_match(
        parsed.netloc, profile.official_domains
    ):
        return False
    return _link_scope_matches(page_url, resolved)


async def read_news_pages(
    db: Session,
    *,
    limit: int = 50,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, int]:
    settings = get_settings()
    rows = db.execute(
        text(
            """
            select d.id, d.canonical_url, d.original_url, d.metadata, ds.source_key
            from source_document d
            left join data_source ds on ds.id = d.source_id
            where d.canonical_url is not null
              and status in ('discovered', 'normalized', 'classified')
              and coalesce((d.metadata->>'discovery_only')::boolean, false) = false
              and d.metadata->>'page_read_at' is null
            order by d.fetched_at desc
            limit :limit
            """
        ),
        {"limit": max(1, min(limit, settings.news_page_read_batch_limit))},
    ).mappings().all()
    documents_seen = 0
    documents_read = 0
    documents_denied = 0
    for row in rows:
        documents_seen += 1
        outcome = await _read_news_page_row(db, row, settings, transport)
        documents_read += outcome.read
        documents_denied += outcome.denied
    return {
        "documents_seen": documents_seen,
        "documents_read": documents_read,
        "documents_denied": documents_denied,
    }


async def _read_news_page_row(
    db: Session,
    row: Any,
    settings: Any,
    transport: httpx.AsyncBaseTransport | None,
) -> PageReadOutcome:
    url = str(row["canonical_url"] or row["original_url"] or "")
    metadata = dict(row["metadata"] or {})
    source_key = str(row["source_key"] or metadata.get("source_key") or "")
    if not _is_safe_http_url(url):
        return PageReadOutcome()
    if _mark_page_read_skip_if_needed(db, row, url, metadata, source_key):
        return PageReadOutcome()
    provider_key, endpoint_key = _provider_for_document(source_key, metadata, url)
    guard = ProviderQuotaGuard.default()
    reservation = _reserve_page_read(db, row, metadata, guard, provider_key, endpoint_key)
    try:
        response, body = await _fetch_page_body(
            url,
            metadata,
            settings,
            transport,
        )
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
            return _handle_provider_page_error(db, row, metadata, response, body, provider_error)
    except ProviderLimitError:
        raise
    except SafeFetchError as exc:
        guard.finalize(
            reservation,
            status="failed",
            db=db,
            error_class=ERROR_SCHEMA_CHANGED,
            details={"reason": str(exc)},
        )
        _mark_page_read_failed(db, row, metadata, str(exc))
        return PageReadOutcome()
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
        guard.finalize(
            reservation,
            status="failed",
            db=db,
            error_class=ERROR_UPSTREAM_5XX,
            retry_after_seconds=60,
        )
        raise ProviderLimitError(
            f"{provider_key}/{endpoint_key} transport error",
            error_class=ERROR_UPSTREAM_5XX,
            provider_key=provider_key,
            endpoint_key=endpoint_key,
            retry_after_seconds=60,
        ) from exc
    guard.finalize(reservation, status="succeeded", db=db, status_code=response.status_code)
    return _mark_page_read_result(db, row, metadata, response, body)


def _mark_page_read_skip_if_needed(
    db: Session, row: Any, url: str, metadata: dict[str, Any], source_key: str
) -> bool:
    if _is_google_news_wrapper(url) or _is_discovery_metadata(metadata):
        _mark_page_read_skipped(db, row, metadata, "discovery_metadata")
        return True
    if not _url_authorized_for_source(url, source_key, metadata):
        _mark_page_read_skipped(db, row, metadata, "host_not_allowlisted")
        return True
    return False


def _reserve_page_read(
    db: Session,
    row: Any,
    metadata: dict[str, Any],
    guard: ProviderQuotaGuard,
    provider_key: str,
    endpoint_key: str,
) -> Any:
    try:
        return guard.reserve(
            provider_key=provider_key,
            endpoint_key=endpoint_key,
            db=db,
            partition_key="news_page_reader",
            idempotency_key=f"news-page-read:{row['id']}",
        )
    except ProviderLimitError as exc:
        _merge_document_metadata(
            db,
            str(row["id"]),
            metadata,
            {
                "page_read_status": "quota_wait",
                "page_retry_after_seconds": exc.retry_after_seconds,
            },
        )
        _commit_progress(db)
        raise


async def _fetch_page_body(
    url: str,
    metadata: dict[str, Any],
    settings: Any,
    transport: httpx.AsyncBaseTransport | None,
) -> tuple[httpx.Response, str]:
    fetched = await safe_fetch_bytes(
        url,
        headers=_headers_for_document(url, metadata, settings.sec_user_agent),
        transport=transport,
        max_bytes=settings.source_fetch_max_bytes,
        timeout_seconds=settings.source_fetch_timeout_seconds,
        raise_for_status=False,
    )
    response = fetched.response
    body = fetched.body.decode(response.encoding or "utf-8", errors="replace")[
        : settings.news_summary_input_max_chars
    ]
    return response, body


def _handle_provider_page_error(
    db: Session,
    row: Any,
    metadata: dict[str, Any],
    response: httpx.Response,
    body: str,
    provider_error: ProviderLimitError,
) -> PageReadOutcome:
    if provider_error.quota_related:
        _merge_document_metadata(
            db,
            str(row["id"]),
            metadata,
            {
                "page_read_status": "quota_wait",
                "page_status_code": response.status_code,
                "page_retry_after_seconds": provider_error.retry_after_seconds,
            },
        )
        _commit_progress(db)
        raise provider_error
    if provider_error.retryable:
        _merge_document_metadata(
            db,
            str(row["id"]),
            metadata,
            {
                "page_read_status": "retry_wait",
                "page_status_code": response.status_code,
                "page_retry_after_seconds": provider_error.retry_after_seconds,
                "page_error_class": provider_error.error_class,
            },
        )
        _commit_progress(db)
        raise provider_error
    denial_reason = detect_denial_reason(
        response.status_code,
        response.headers.get("content-type", ""),
        body,
    )
    _merge_document_metadata(
        db,
        str(row["id"]),
        metadata,
        {
            "page_read_at": _now(),
            "page_read_status": "denied" if denial_reason else "failed",
            "page_denial_reason": denial_reason,
            "page_status_code": response.status_code,
            "page_error_class": provider_error.error_class,
        },
    )
    _commit_progress(db)
    return PageReadOutcome(denied=1)


def _mark_page_read_result(
    db: Session,
    row: Any,
    metadata: dict[str, Any],
    response: httpx.Response,
    body: str,
) -> PageReadOutcome:
    try:
        denial_reason = detect_denial_reason(
            response.status_code,
            response.headers.get("content-type", ""),
            body,
        )
        if denial_reason:
            _mark_page_read_denied(db, row, metadata, response, denial_reason)
            return PageReadOutcome(denied=1)
        _mark_page_read_success(db, row, metadata, response, body)
        return PageReadOutcome(read=1)
    except Exception:
        _commit_progress(db)
        raise


def _mark_page_read_skipped(
    db: Session, row: Any, metadata: dict[str, Any], reason: str
) -> None:
    _merge_document_metadata(
        db,
        str(row["id"]),
        metadata,
        {
            "page_read_at": _now(),
            "page_read_status": "skipped",
            "page_skip_reason": reason,
        },
    )
    _commit_progress(db)


def _mark_page_read_failed(db: Session, row: Any, metadata: dict[str, Any], error: str) -> None:
    _merge_document_metadata(
        db,
        str(row["id"]),
        metadata,
        {
            "page_read_at": _now(),
            "page_read_status": "failed",
            "page_read_error": error[:240],
        },
    )
    _commit_progress(db)


def _mark_page_read_denied(
    db: Session, row: Any, metadata: dict[str, Any], response: httpx.Response, denial_reason: str
) -> None:
    _merge_document_metadata(
        db,
        str(row["id"]),
        metadata,
        {
            "page_read_at": _now(),
            "page_read_status": "denied",
            "page_denial_reason": denial_reason,
            "page_status_code": response.status_code,
        },
    )
    _commit_progress(db)


def _mark_page_read_success(
    db: Session, row: Any, metadata: dict[str, Any], response: httpx.Response, body: str
) -> None:
    parser = HTMLParser(body)
    _merge_document_metadata(
        db,
        str(row["id"]),
        metadata,
        {
            "page_read_at": _now(),
            "page_read_status": "read",
            "page_title": _node_text(parser.css_first("title"))[:500],
            "page_excerpt": _first_paragraph(parser)[:1000],
            "page_status_code": response.status_code,
        },
    )
    _commit_progress(db)


def _merge_document_metadata(db: Session, document_id: str, metadata: dict[str, Any], patch: dict[str, Any]) -> None:
    metadata.update(patch)
    db.execute(
        text(
            """
            update source_document
            set metadata = cast(:metadata as jsonb), updated_at = now()
            where id = :id
            """
        ),
        {"id": document_id, "metadata": json.dumps(metadata, default=str)},
    )


def _first_paragraph(parser: HTMLParser) -> str:
    for selector in ("article p", "main p", "p"):
        for node in parser.css(selector):
            value = _node_text(node)
            if len(value) >= 40:
                return value
    return ""


def _node_text(node: Any | None) -> str:
    if node is None:
        return ""
    return " ".join(node.text(separator=" ").split())


def _clean_anchor_text(value: str) -> str:
    clean = value
    if "{" in clean:
        clean = clean.split("{", 1)[0].strip()
    if ".textlink" in clean:
        clean = clean.split(".textlink", 1)[0].strip()
    return clean


def _generic_anchor_title(value: str) -> bool:
    clean = value.lower().strip()
    if clean in _GENERIC_LINK_TITLES:
        return True
    return any(clean.startswith(f"{title} ") for title in _GENERIC_LINK_TITLES)


def _title_from_url(value: str) -> str:
    slug = urlparse(value).path.rstrip("/").rsplit("/", 1)[-1]
    return " ".join(part.capitalize() for part in slug.replace("-", " ").split())


def _looks_like_news_link(title: str, url: str) -> bool:
    haystack = f"{title} {url}".lower()
    if any(keyword in haystack for keyword in _LINK_KEYWORDS):
        return True
    return any(str(year) in haystack for year in range(2024, datetime.now(timezone.utc).year + 2))


def _looks_like_error_page(title: str) -> bool:
    lowered = title.lower()
    return any(
        marker in lowered
        for marker in (
            "page not found",
            "cannot be found",
            "access denied",
            "forbidden",
            "error",
        )
    )


def _headers_for_document(url: str, metadata: dict[str, Any], default_user_agent: str) -> dict[str, str]:
    host = (urlparse(url).hostname or "").lower()
    profile = str(metadata.get("fetch_profile") or "").strip()
    if not profile:
        profile = "default" if _host_matches_domain(host, "sec.gov") else "ir_vendor"
    return headers_for_fetch_profile(profile, default_user_agent)


def _provider_for_document(source_key: str, metadata: dict[str, Any], url: str) -> tuple[str, str]:
    profile = source_registry().get(source_key)
    if profile:
        if profile.rate_limit_provider_key == "sec_edgar":
            return "sec_edgar", "filing_document"
        if profile.rate_limit_provider_key == "company_ir":
            return "company_ir", "html"
        return profile.rate_limit_provider_key, profile.rate_limit_endpoint_key
    host = (urlparse(url).hostname or "").lower()
    if _host_matches_domain(host, "sec.gov"):
        return "sec_edgar", "filing_document"
    return str(metadata.get("rate_limit_provider_key") or "company_ir"), str(metadata.get("rate_limit_endpoint_key") or "html")


def _host_matches_domain(host: str, domain: str) -> bool:
    clean_host = host.rstrip(".").lower()
    clean_domain = domain.rstrip(".").lower()
    return clean_host == clean_domain or clean_host.endswith(f".{clean_domain}")


def _url_authorized_for_source(url: str, source_key: str, metadata: dict[str, Any]) -> bool:
    if source_key == "company_email_alert" and not metadata.get("manual_page_read_allowed"):
        return False
    host = _url_host(url)
    if not host:
        return False
    allowed_domains = _source_allowed_domains(source_key)
    allowed_domains.update(_metadata_allowed_domains(metadata))
    if not allowed_domains:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains if domain)


def _url_host(url: str) -> str:
    return urlparse(url).netloc.lower().split(":", 1)[0]


def _source_allowed_domains(source_key: str) -> set[str]:
    profile = source_registry().get(source_key)
    if not profile:
        return set()
    allowed_domains = {domain.lower() for domain in profile.official_domains}
    for raw_url in (profile.base_url, profile.feed_url or ""):
        if host := _url_host(raw_url):
            allowed_domains.add(host)
    return allowed_domains


def _metadata_allowed_domains(metadata: dict[str, Any]) -> set[str]:
    raw_allowed = metadata.get("page_read_allowed_domains") or []
    if isinstance(raw_allowed, str):
        raw_allowed = [part.strip() for part in raw_allowed.split(",")]
    return {str(value).lower() for value in raw_allowed}


def _is_discovery_metadata(metadata: dict[str, Any]) -> bool:
    return bool(metadata.get("discovery_only")) or str(metadata.get("copyright_mode") or "") == "metadata_only"


def _commit_progress(db: Session) -> None:
    commit = getattr(db, "commit", None)
    if callable(commit):
        commit()


def _is_google_news_wrapper(url: str) -> bool:
    return urlparse(url).netloc.lower().endswith("news.google.com")


def _link_scope_matches(page_url: str, resolved_url: str) -> bool:
    page_path = urlparse(page_url).path.lower()
    link_path = urlparse(resolved_url).path.lower()
    news_scope = ("news", "press", "release", "investor", "event")
    if any(part in page_path for part in news_scope):
        return any(part in link_path for part in news_scope)
    return True


def _official_domain_match(netloc: str, domains: tuple[str, ...]) -> bool:
    host = netloc.lower().split(":", 1)[0]
    for domain in domains:
        clean = domain.lower()
        if host == clean or host.endswith(f".{clean}"):
            return True
    return False


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
