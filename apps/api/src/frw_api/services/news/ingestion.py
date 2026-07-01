from __future__ import annotations

import asyncio
import email.utils
import hashlib
import io
import ipaddress
import json
import re
import time
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from xml.etree import ElementTree

import httpx
from sqlalchemy.orm import Session

from frw_api.adapters.base import AdapterResult
from frw_api.core.settings import get_settings
from frw_api.services.ingestion_pipeline import persist_adapter_result
from frw_api.services.news.document_normalizer import normalize_document
from frw_api.services.news.geopolitical_registry import match_geo_points
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
from frw_api.services.fetch_policy import is_blocked_ip
from frw_api.services.safe_fetch import SafeFetchError, safe_fetch_bytes

SHA256_PREFIX = "sha256:"
NEWS_DEDUPE_PREFIX = "news:"
GDELT_LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
GDELT_DATA_HOST_ALLOWLIST = frozenset({"data.gdeltproject.org"})
GDELT_EXPORT_SUFFIX = ".export.CSV.zip"
GDELT_GKG_SUFFIX = ".gkg.csv.zip"
ROOT = Path(__file__).resolve().parents[6]
WATCHED_REGIONS_PATH = ROOT / "packages" / "shared-config" / "watched-regions.json"
_WATCHED_REGION_REGISTRY: dict[str, Any] | None = None
GDELT_TRACKED_COUNTRY_THEME_QUERIES = (
    "(markets OR stocks OR energy OR commodities OR rates OR sanctions OR trade)",
    "(sanctions OR tariff OR \"trade war\" OR export OR controls OR supply)",
    "(oil OR gas OR lng OR shipping OR chokepoint OR refinery OR pipeline)",
)
GDELT_COUNTRY_QUERY_CHUNK_SIZE = 6


def _watched_region_registry() -> dict[str, Any]:
    global _WATCHED_REGION_REGISTRY
    if _WATCHED_REGION_REGISTRY is None:
        _WATCHED_REGION_REGISTRY = json.loads(WATCHED_REGIONS_PATH.read_text())
    return _WATCHED_REGION_REGISTRY


def _gdelt_tracked_country_query_terms() -> tuple[str, ...]:
    terms: list[str] = []
    for row in _watched_region_registry().get("regions", []):
        if not isinstance(row, dict) or not row.get("gather_news"):
            continue
        terms.extend(str(term) for term in row.get("gdelt_terms") or [] if str(term).strip())
    return tuple(dict.fromkeys(terms))


def _or_clause(terms: Iterable[str]) -> str:
    return "(" + " OR ".join(term for term in terms if term) + ")"


def _chunked_terms(terms: Iterable[str], chunk_size: int) -> tuple[tuple[str, ...], ...]:
    chunk: list[str] = []
    chunks: list[tuple[str, ...]] = []
    for term in terms:
        chunk.append(term)
        if len(chunk) >= chunk_size:
            chunks.append(tuple(chunk))
            chunk = []
    if chunk:
        chunks.append(tuple(chunk))
    return tuple(chunks)


def _gdelt_country_theme_queries(
    country_terms: Iterable[str] | None = None,
    theme_queries: Iterable[str] = GDELT_TRACKED_COUNTRY_THEME_QUERIES,
    *,
    chunk_size: int = GDELT_COUNTRY_QUERY_CHUNK_SIZE,
) -> tuple[str, ...]:
    country_terms = _gdelt_tracked_country_query_terms() if country_terms is None else country_terms
    chunks = _chunked_terms(country_terms, max(1, chunk_size))
    return tuple(f"{_or_clause(chunk)} AND {theme}" for theme in theme_queries for chunk in chunks)


def _interleave_query_groups(*groups: Iterable[str]) -> tuple[str, ...]:
    pending: list[list[str]] = []
    for group in groups:
        materialized = list(group)
        if materialized:
            pending.append(materialized)
    interleaved: list[str] = []
    while pending:
        next_pending: list[list[str]] = []
        for group in pending:
            interleaved.append(group[0])
            rest = group[1:]
            if rest:
                next_pending.append(rest)
        pending = next_pending
    return tuple(interleaved)


GDELT_DOC_QUERY_PACKS: dict[str, tuple[str, ...]] = {
    "market_watch": _interleave_query_groups(
        _gdelt_country_theme_queries(theme_queries=(GDELT_TRACKED_COUNTRY_THEME_QUERIES[0],)),
        (
            "(hormuz OR \"red sea\" OR oil OR lng OR pipeline OR refinery OR shipping)",
            "(semiconductor OR chip OR \"export control\" OR BIS OR Taiwan OR Korea OR Japan)",
            "(\"AI infrastructure\" OR datacenter OR \"data center\" OR capex OR HBM OR accelerator)",
            "(\"central bank\" OR rates OR inflation OR treasury OR yen OR dollar)",
        ),
        _gdelt_country_theme_queries(theme_queries=GDELT_TRACKED_COUNTRY_THEME_QUERIES[1:]),
        (
            "(sanctions OR tariff OR \"trade war\" OR blockade OR missile OR conflict)",
            "(outbreak OR pandemic OR WHO OR avian OR vaccine OR public health)",
            "(NVDA OR AMD OR MSFT OR AAPL OR TSMC OR Samsung OR ASML OR RKLB OR IONQ OR RGTI OR QBTS OR LUNR OR ASTS OR RDW OR DJT)",
        ),
    ),
}


class NewsIngestionError(ValueError):
    pass


@dataclass(frozen=True)
class NewsSourceRequest:
    url: str
    params: dict[str, str]
    headers: dict[str, str]


@dataclass
class GdeltDiscoveryStats:
    fetched: int = 0
    parsed: int = 0
    deduped: int = 0
    title_enriched: int = 0
    title_fallback: int = 0
    stale_dropped: int = 0
    irrelevant_dropped: int = 0
    no_geo_dropped: int = 0
    blocked_or_denied: int = 0
    published_or_projected: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "fetched": self.fetched,
            "parsed": self.parsed,
            "deduped": self.deduped,
            "title_enriched": self.title_enriched,
            "title_fallback": self.title_fallback,
            "stale_dropped": self.stale_dropped,
            "irrelevant_dropped": self.irrelevant_dropped,
            "no_geo_dropped": self.no_geo_dropped,
            "blocked_or_denied": self.blocked_or_denied,
            "published_or_projected": self.published_or_projected,
        }


@dataclass(frozen=True)
class GdeltArticleMetadata:
    title: str | None = None
    canonical_url: str | None = None
    published_at: str | None = None
    status: str = "fallback"
    source: str = "none"
    denial_reason: str | None = None


@dataclass
class GdeltTitleEnrichmentContext:
    limit: int
    timeout_seconds: int
    max_bytes: int
    per_host_interval_seconds: float
    user_agent: str
    transport: httpx.AsyncBaseTransport | None = None
    fetched: int = 0
    cache: dict[str, GdeltArticleMetadata] | None = None
    host_last_fetch: dict[str, float] | None = None

    def __post_init__(self) -> None:
        if self.cache is None:
            self.cache = {}
        if self.host_last_fetch is None:
            self.host_last_fetch = {}


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
    if profile.source_key == "gdelt" and query is None:
        return await _fetch_gdelt_doc_query_pack(
            db,
            profile=profile,
            max_documents=limit,
            transport=transport,
        )
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
    if profile.fetch_kind in {"gdelt_event_file", "gdelt_gkg_file"}:
        return await _fetch_gdelt_bulk_source(
            db,
            profile=profile,
            max_documents=limit,
            transport=transport,
        )

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
    upsert_source_health(
        db,
        source_key=profile.source_key,
        status="ready" if documents else "empty",
        details={
            "object_key": adapter_result.object_key,
            **persisted,
        },
    )
    return {
        "source_key": profile.source_key,
        "status": "ready" if documents else "empty",
        "documents": len(documents),
        "persisted": persisted,
        "trust_tier": profile.trust_tier,
        "copyright_mode": profile.copyright_mode,
    }


async def _fetch_gdelt_doc_query_pack(
    db: Session,
    *,
    profile: SourceProfile,
    max_documents: int,
    transport: httpx.AsyncBaseTransport | None,
) -> dict[str, Any]:
    settings = get_settings()
    cycle_seconds = max(300, int(settings.news_source_refresh_seconds or settings.gdelt_doc_min_interval_seconds))
    cycle_index = int(datetime.now(timezone.utc).timestamp()) // cycle_seconds
    queries = _gdelt_doc_queries(
        settings.gdelt_doc_query_pack,
        settings.gdelt_doc_cycle_budget,
        cycle_index=cycle_index,
    )
    if not queries:
        request = build_news_source_request(profile, query=profile.default_query, max_documents=max_documents)
        if request is None:
            return {
                "source_key": profile.source_key,
                "status": "unsupported",
                "documents": 0,
                "persisted": {"documents": 0, "observations": 0, "releases": 0, "source_status": "unsupported"},
            }
        queries = (request.params.get("query") or profile.default_query or "financial markets",)
    per_query_records = _gdelt_doc_records_per_query(max_documents, len(queries), settings.gdelt_doc_max_records)
    stats = GdeltDiscoveryStats()
    documents: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    headers = {
        "Accept": "application/json",
        "User-Agent": settings.sec_user_agent,
        **headers_for_fetch_profile(profile.fetch_profile, settings.sec_user_agent),
    }
    for index, query in enumerate(queries):
        if index > 0:
            await asyncio.sleep(settings.gdelt_doc_min_interval_seconds)
        request = build_news_source_request(profile, query=query, max_documents=per_query_records)
        if request is None:
            continue
        try:
            response = await _fetch_limited_provider_response(
                provider_key=profile.rate_limit_provider_key,
                endpoint_key=profile.rate_limit_endpoint_key,
                db=db,
                idempotency_key=_request_idempotency_key(profile.source_key, request),
                max_bytes=settings.source_fetch_max_bytes,
                timeout_seconds=settings.source_fetch_timeout_seconds,
                headers={**headers, **request.headers},
                url=request.url,
                params=request.params or None,
                transport=transport,
            )
        except ProviderLimitError:
            if not documents:
                raise
            break
        rows = parse_news_response(profile, response, max_documents=per_query_records)
        stats.fetched += per_query_records
        stats.parsed += len(rows)
        for document in rows:
            dedupe_key = _document_dedupe_key(document)
            if dedupe_key in seen_keys:
                stats.deduped += 1
                continue
            seen_keys.add(dedupe_key)
            document["gdelt_query_pack"] = settings.gdelt_doc_query_pack
            document["gdelt_query"] = query
            documents.append(document)
    documents = _rank_gdelt_documents(documents)[:max_documents]
    stats.published_or_projected = len(documents)
    adapter_result = AdapterResult(
        source_key=profile.source_key,
        object_key=f"news:{profile.source_key}:query-pack:{settings.gdelt_doc_query_pack}",
        observations=[],
        releases=[],
        documents=documents,
        unsupported=[] if documents else ["no_documents_parsed"],
    )
    persisted = persist_adapter_result(db, adapter_result)
    upsert_source_health(
        db,
        source_key=profile.source_key,
        status="ready" if documents else "empty",
        details={
            "object_key": adapter_result.object_key,
            "query_pack": settings.gdelt_doc_query_pack,
            "query_count": len(queries),
            "candidate_records_per_query": per_query_records,
            "discovery": stats.as_dict(),
            **persisted,
        },
    )
    return {
        "source_key": profile.source_key,
        "status": "ready" if documents else "empty",
        "documents": len(documents),
        "persisted": persisted,
        "trust_tier": profile.trust_tier,
        "copyright_mode": profile.copyright_mode,
        "query_pack": settings.gdelt_doc_query_pack,
        "discovery": stats.as_dict(),
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
    if profile.fetch_kind in {"gdelt_event_file", "gdelt_gkg_file"}:
        return NewsSourceRequest(
            url=GDELT_LASTUPDATE_URL,
            params={},
            headers={"Accept": "text/plain"},
        )
    if profile.feed_url:
        headers = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.3"} if profile.fetch_kind == "html_index" else {}
        return NewsSourceRequest(url=profile.feed_url, params={}, headers=headers)
    return None


def _gdelt_doc_queries(
    pack_name: str,
    cycle_budget: int,
    *,
    cycle_index: int = 0,
) -> tuple[str, ...]:
    pack = GDELT_DOC_QUERY_PACKS.get((pack_name or "").strip()) or GDELT_DOC_QUERY_PACKS["market_watch"]
    if cycle_budget <= 0:
        return ()
    budget = min(cycle_budget, len(pack))
    if budget == len(pack):
        return pack
    start = (max(0, cycle_index) * budget) % len(pack)
    return tuple(pack[(start + offset) % len(pack)] for offset in range(budget))


def _gdelt_doc_records_per_query(max_documents: int, query_count: int, provider_cap: int) -> int:
    if query_count <= 0:
        return max(1, min(max_documents, provider_cap))
    diversified_floor = 25
    return max(1, min(provider_cap, max(diversified_floor, (max_documents + query_count - 1) // query_count)))


def _gdelt_candidate_limit(max_documents: int, title_context: GdeltTitleEnrichmentContext | None) -> int:
    title_budget = title_context.limit if title_context is not None else 0
    return max(1, min(max_documents * 2, max_documents + title_budget))


def _document_dedupe_key(document: dict[str, Any]) -> str:
    url = str(document.get("canonical_url") or document.get("url") or "").strip().lower()
    if url:
        return url
    return str(document.get("dedupe_key") or document.get("normalized_hash") or document.get("title") or "")


def _rank_gdelt_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        documents,
        key=lambda document: (
            _trusty_title_score(str(document.get("title") or "")),
            str(document.get("published_at") or document.get("fetched_at") or ""),
            str(document.get("canonical_url") or document.get("url") or ""),
        ),
        reverse=True,
    )


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


async def _fetch_gdelt_bulk_source(
    db: Session,
    *,
    profile: SourceProfile,
    max_documents: int,
    transport: httpx.AsyncBaseTransport | None,
) -> dict[str, Any]:
    settings = get_settings()
    lastupdate = await _fetch_limited_provider_response(
        provider_key=profile.rate_limit_provider_key,
        endpoint_key=profile.rate_limit_endpoint_key,
        db=db,
        idempotency_key=f"gdelt-bulk:lastupdate:{profile.source_key}",
        max_bytes=20_000,
        timeout_seconds=settings.source_fetch_timeout_seconds,
        headers={"Accept": "text/plain", "User-Agent": settings.sec_user_agent},
        url=GDELT_LASTUPDATE_URL,
        params=None,
        transport=transport,
        allow_http_hosts=GDELT_DATA_HOST_ALLOWLIST,
    )
    suffix = GDELT_EXPORT_SUFFIX if profile.fetch_kind == "gdelt_event_file" else GDELT_GKG_SUFFIX
    selected = _select_gdelt_update_file(lastupdate.text, suffix=suffix)
    if selected is None:
        upsert_source_health(
            db,
            source_key=profile.source_key,
            status="empty",
            details={"reason": "gdelt_update_file_missing", "suffix": suffix},
        )
        return {
            "source_key": profile.source_key,
            "status": "empty",
            "documents": 0,
            "persisted": {"documents": 0, "observations": 0, "releases": 0, "source_status": "empty"},
        }
    archive = await _fetch_limited_provider_response(
        provider_key=profile.rate_limit_provider_key,
        endpoint_key=profile.rate_limit_endpoint_key,
        db=db,
        idempotency_key=f"gdelt-bulk:{profile.source_key}:{selected['url']}",
        max_bytes=min(settings.source_fetch_max_bytes, settings.gdelt_bulk_max_compressed_bytes),
        timeout_seconds=settings.source_fetch_timeout_seconds,
        headers={"Accept": "application/zip,*/*;q=0.2", "User-Agent": settings.sec_user_agent},
        url=selected["url"],
        params=None,
        transport=transport,
        allow_http_hosts=GDELT_DATA_HOST_ALLOWLIST,
    )
    stats = GdeltDiscoveryStats()
    title_context = _gdelt_title_context(settings, transport=transport)
    documents = await _parse_gdelt_bulk_file(
        profile,
        archive.content,
        selected=selected,
        max_documents=max_documents,
        max_rows=settings.gdelt_bulk_max_rows,
        max_expanded_bytes=settings.gdelt_bulk_max_expanded_bytes,
        title_context=title_context,
        stats=stats,
    )
    stats.fetched = stats.parsed
    stats.published_or_projected = len(documents)
    adapter_result = AdapterResult(
        source_key=profile.source_key,
        object_key=f"news:{profile.source_key}:{selected['timestamp']}",
        observations=[],
        releases=[],
        documents=documents,
        unsupported=[] if documents else ["no_relevant_gdelt_bulk_rows"],
    )
    persisted = persist_adapter_result(db, adapter_result)
    upsert_source_health(
        db,
        source_key=profile.source_key,
        status="ready" if documents else "empty",
        details={
            "object_key": adapter_result.object_key,
            "gdelt_file": selected,
            "discovery": stats.as_dict(),
            "title_fetch_limit": title_context.limit,
            "title_fetches_used": title_context.fetched,
            **persisted,
        },
    )
    return {
        "source_key": profile.source_key,
        "status": "ready" if documents else "empty",
        "documents": len(documents),
        "persisted": persisted,
        "trust_tier": profile.trust_tier,
        "copyright_mode": profile.copyright_mode,
        "gdelt_file": selected,
        "discovery": stats.as_dict(),
    }


def _select_gdelt_update_file(text: str, *, suffix: str) -> dict[str, str] | None:
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) != 3:
            continue
        size, md5, url = parts
        if not url.endswith(suffix) or not _is_gdelt_data_url(url):
            continue
        timestamp = url.rsplit("/", 1)[-1].split(".", 1)[0]
        return {"size": size, "md5": md5, "url": url, "timestamp": timestamp}
    return None


async def _parse_gdelt_bulk_file(
    profile: SourceProfile,
    body: bytes,
    *,
    selected: dict[str, str],
    max_documents: int,
    max_rows: int,
    max_expanded_bytes: int,
    title_context: GdeltTitleEnrichmentContext | None = None,
    stats: GdeltDiscoveryStats | None = None,
) -> list[dict[str, Any]]:
    rows = _iter_zipped_csv_rows(body, max_rows=max_rows, max_expanded_bytes=max_expanded_bytes)
    if profile.fetch_kind == "gdelt_event_file":
        return await _parse_gdelt_event_rows(
            profile,
            rows,
            selected=selected,
            max_documents=max_documents,
            title_context=title_context,
            stats=stats,
        )
    return await _parse_gdelt_gkg_rows(
        profile,
        rows,
        selected=selected,
        max_documents=max_documents,
        title_context=title_context,
        stats=stats,
    )


def _iter_zipped_csv_rows(
    body: bytes, *, max_rows: int, max_expanded_bytes: int
) -> Iterator[list[str]]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(body))
    except zipfile.BadZipFile as exc:
        raise NewsIngestionError("Malformed GDELT zip archive") from exc
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if len(infos) != 1:
        raise NewsIngestionError("GDELT zip archive must contain exactly one file")

    def line_iter() -> Iterator[str]:
        expanded = 0
        count = 0
        with archive.open(infos[0]) as stream:
            for raw_line in stream:
                expanded += len(raw_line)
                if expanded > max_expanded_bytes:
                    raise NewsIngestionError("GDELT expanded CSV exceeded configured limit")
                count += 1
                if count > max_rows:
                    break
                yield raw_line.decode("utf-8", errors="replace")

    import csv

    yield from csv.reader(line_iter(), delimiter="\t")


async def _parse_gdelt_event_rows(
    profile: SourceProfile,
    rows: Iterable[list[str]],
    *,
    selected: dict[str, str],
    max_documents: int,
    title_context: GdeltTitleEnrichmentContext | None = None,
    stats: GdeltDiscoveryStats | None = None,
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    candidate_limit = _gdelt_candidate_limit(max_documents, title_context)
    for row in rows:
        if len(documents) >= candidate_limit:
            break
        if stats:
            stats.parsed += 1
        if len(row) < 61:
            continue
        source_url = row[60].strip()
        if not _is_public_http_url(source_url):
            if stats:
                stats.blocked_or_denied += 1
            continue
        place = _first_nonempty(row[52], row[44], row[36])
        actor1 = row[6].strip()
        actor2 = row[16].strip()
        event_code = row[26].strip()
        quad_class = row[29].strip()
        goldstein = row[30].strip()
        tone = row[34].strip()
        source_country = _first_nonempty(row[53], row[45], row[37])
        text_blob = " ".join(
            part for part in (actor1, actor2, place, source_country, event_code, source_url) if part
        )
        if not _gdelt_bulk_relevant(text_blob, event_code=event_code, quad_class=quad_class):
            if stats:
                stats.irrelevant_dropped += 1
            continue
        geo_points = match_geo_points(texts=(text_blob,))
        if not geo_points:
            if stats:
                stats.no_geo_dropped += 1
            continue
        title_metadata = await _gdelt_article_metadata(source_url, context=title_context, stats=stats)
        fallback_title = _gdelt_source_report_title(source_url, actor1, actor2, place)
        title = _best_gdelt_title(title_metadata, fallback_title)
        published_at = _gdelt_file_datetime(_first_nonempty(row[59], selected["timestamp"], row[1]))
        canonical_url = title_metadata.canonical_url or source_url
        published_at = title_metadata.published_at or published_at
        documents.append(
            _normalized_document_dict(
                profile,
                {
                    "title": title,
                    "url": source_url,
                    "canonical_url": canonical_url,
                    "snippet": (
                        f"GDELT event metadata: event {event_code}, quad class {quad_class}, "
                        f"Goldstein {goldstein or 'n/a'}, tone {tone or 'n/a'}."
                    ),
                    "published_at": published_at,
                    "source_region": source_country,
                    "language": "en",
                    "gdelt_file_url": selected["url"],
                    "gdelt_file_timestamp": selected["timestamp"],
                    "gdelt_global_event_id": row[0].strip(),
                    "gdelt_event_code": event_code,
                    "gdelt_quad_class": quad_class,
                    "gdelt_title_status": title_metadata.status,
                    "gdelt_title_source": title_metadata.source,
                    "geo_points": geo_points,
                    "dedupe_key": _news_dedupe_key(profile.source_key, row[0].strip(), source_url, selected["timestamp"]),
                },
            )
        )
    return _rank_gdelt_documents(documents)[:max_documents]


async def _parse_gdelt_gkg_rows(
    profile: SourceProfile,
    rows: Iterable[list[str]],
    *,
    selected: dict[str, str],
    max_documents: int,
    title_context: GdeltTitleEnrichmentContext | None = None,
    stats: GdeltDiscoveryStats | None = None,
) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    candidate_limit = _gdelt_candidate_limit(max_documents, title_context)
    for row in rows:
        if len(documents) >= candidate_limit:
            break
        if stats:
            stats.parsed += 1
        document = await _gdelt_gkg_document(profile, row, selected=selected, title_context=title_context, stats=stats)
        if document is not None:
            documents.append(document)
    return _rank_gdelt_documents(documents)[:max_documents]


async def _gdelt_gkg_document(
    profile: SourceProfile,
    row: list[str],
    *,
    selected: dict[str, str],
    title_context: GdeltTitleEnrichmentContext | None = None,
    stats: GdeltDiscoveryStats | None = None,
) -> dict[str, Any] | None:
    if len(row) < 16:
        return None
    record_id = row[0].strip()
    source_domain = row[3].strip()
    document_url = row[4].strip()
    if not _is_public_http_url(document_url):
        if stats:
            stats.blocked_or_denied += 1
        return None
    themes = _gdelt_gkg_values(row[7] if len(row) > 7 else "")
    locations = _gdelt_gkg_locations(row[9] if len(row) > 9 else "")
    text_blob = " ".join([document_url, source_domain, " ".join(themes), " ".join(locations)])
    if not _gdelt_bulk_relevant(text_blob):
        if stats:
            stats.irrelevant_dropped += 1
        return None
    geo_points = match_geo_points(texts=(text_blob,))
    if not geo_points:
        if stats:
            stats.no_geo_dropped += 1
        return None
    title_metadata = await _gdelt_article_metadata(document_url, context=title_context, stats=stats)
    fallback_title = _gdelt_source_report_title(document_url, "", "", locations[0] if locations else "")
    title = _best_gdelt_title(title_metadata, fallback_title)
    canonical_url = title_metadata.canonical_url or document_url
    published_at = title_metadata.published_at or _gdelt_file_datetime(_first_nonempty(row[1], selected["timestamp"]))
    return _normalized_document_dict(
        profile,
        {
            "title": title,
            "url": document_url,
            "canonical_url": canonical_url,
            "snippet": _gdelt_gkg_snippet(themes, locations),
            "published_at": published_at,
            "source_region": locations[0] if locations else None,
            "language": "en",
            "gdelt_file_url": selected["url"],
            "gdelt_file_timestamp": selected["timestamp"],
            "gdelt_record_id": record_id,
            "gdelt_source_domain": source_domain,
            "gdelt_title_status": title_metadata.status,
            "gdelt_title_source": title_metadata.source,
            "geo_points": geo_points,
            "dedupe_key": _news_dedupe_key(profile.source_key, record_id, document_url),
        },
    )


def _gdelt_title_context(
    settings: Any,
    *,
    transport: httpx.AsyncBaseTransport | None,
) -> GdeltTitleEnrichmentContext:
    return GdeltTitleEnrichmentContext(
        limit=settings.gdelt_title_fetch_limit,
        timeout_seconds=settings.gdelt_title_fetch_timeout_seconds,
        max_bytes=settings.gdelt_title_fetch_max_bytes,
        per_host_interval_seconds=settings.gdelt_title_per_host_interval_seconds,
        user_agent=settings.sec_user_agent,
        transport=transport,
    )


async def _gdelt_article_metadata(
    url: str,
    *,
    context: GdeltTitleEnrichmentContext | None,
    stats: GdeltDiscoveryStats | None = None,
) -> GdeltArticleMetadata:
    if context is None:
        if stats:
            stats.title_fallback += 1
        return GdeltArticleMetadata(title=_article_title_from_url_path(url), status="fallback", source="url_slug")
    safe_url = _safe_gdelt_article_url(url)
    if not safe_url:
        if stats:
            stats.blocked_or_denied += 1
            stats.title_fallback += 1
        return GdeltArticleMetadata(title=_article_title_from_url_path(url), status="blocked", source="url_slug", denial_reason="unsafe_url")
    assert context.cache is not None
    if safe_url in context.cache:
        cached = context.cache[safe_url]
        _record_title_metadata_stats(cached, stats)
        return cached
    title_hint = _article_title_from_url_path(safe_url)
    if context.fetched >= context.limit:
        metadata = GdeltArticleMetadata(title=title_hint, status="fallback", source="url_slug", denial_reason="fetch_budget_exhausted")
        context.cache[safe_url] = metadata
        _record_title_metadata_stats(metadata, stats)
        return metadata
    context.fetched += 1
    await _gdelt_title_host_backoff(safe_url, context)
    headers = {
        "User-Agent": context.user_agent,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.5",
        "Range": f"bytes=0-{context.max_bytes - 1}",
    }
    try:
        fetched = await safe_fetch_bytes(
            safe_url,
            headers=headers,
            transport=context.transport,
            max_bytes=context.max_bytes,
            timeout_seconds=context.timeout_seconds,
            raise_for_status=False,
        )
    except (SafeFetchError, httpx.HTTPError) as exc:
        metadata = GdeltArticleMetadata(
            title=title_hint,
            status="blocked",
            source="url_slug" if title_hint else "none",
            denial_reason=exc.__class__.__name__,
        )
        context.cache[safe_url] = metadata
        _record_title_metadata_stats(metadata, stats)
        return metadata
    body = fetched.body.decode(fetched.response.encoding or "utf-8", errors="replace")
    denial_reason = detect_denial_reason(
        fetched.response.status_code,
        fetched.response.headers.get("content-type", ""),
        body,
    )
    if denial_reason:
        metadata = GdeltArticleMetadata(
            title=title_hint,
            status="blocked",
            source="url_slug" if title_hint else "none",
            denial_reason=denial_reason,
        )
        context.cache[safe_url] = metadata
        _record_title_metadata_stats(metadata, stats)
        return metadata
    title = _article_title_from_html(body) or title_hint
    canonical_url = _article_canonical_url_from_html(body, fetched.final_url or safe_url)
    published_at = _article_published_at_from_html(body)
    metadata = GdeltArticleMetadata(
        title=title,
        canonical_url=canonical_url,
        published_at=published_at,
        status="enriched" if title and title != title_hint else "fallback",
        source="html_metadata" if title and title != title_hint else "url_slug",
    )
    context.cache[safe_url] = metadata
    _record_title_metadata_stats(metadata, stats)
    return metadata


async def _gdelt_title_host_backoff(url: str, context: GdeltTitleEnrichmentContext) -> None:
    host = (urlparse(url).hostname or "").lower()
    if not host or context.per_host_interval_seconds <= 0:
        return
    assert context.host_last_fetch is not None
    last_fetch = context.host_last_fetch.get(host)
    now = time.monotonic()
    if last_fetch is not None:
        remaining = context.per_host_interval_seconds - (now - last_fetch)
        if remaining > 0:
            await asyncio.sleep(remaining)
    context.host_last_fetch[host] = time.monotonic()


def _record_title_metadata_stats(metadata: GdeltArticleMetadata, stats: GdeltDiscoveryStats | None) -> None:
    if not stats:
        return
    if metadata.status == "enriched":
        stats.title_enriched += 1
    else:
        stats.title_fallback += 1
    if metadata.status == "blocked":
        stats.blocked_or_denied += 1


def _best_gdelt_title(metadata: GdeltArticleMetadata, fallback_title: str) -> str:
    title = _clean_article_title(metadata.title or "")
    if title:
        return title
    return fallback_title


def _safe_gdelt_article_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.hostname == "data.gdeltproject.org" or parsed.path.endswith(".zip"):
        return ""
    if not _is_public_http_url(value):
        return ""
    return value.strip()


def _article_title_from_html(html: str) -> str | None:
    for pattern in (
        r"<meta[^>]+property=[\"']og:title[\"'][^>]+content=[\"']([^\"']+)[\"']",
        r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+property=[\"']og:title[\"']",
        r"<meta[^>]+name=[\"']twitter:title[\"'][^>]+content=[\"']([^\"']+)[\"']",
        r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+name=[\"']twitter:title[\"']",
        r"<title[^>]*>(.*?)</title>",
    ):
        title = _clean_article_title(_html_field(html, pattern) or "")
        if title:
            return title
    return None


def _article_canonical_url_from_html(html: str, base_url: str) -> str | None:
    href = _html_field(html, r"<link[^>]+rel=[\"']canonical[\"'][^>]+href=[\"']([^\"']+)[\"']")
    if not href:
        href = _html_field(html, r"<meta[^>]+property=[\"']og:url[\"'][^>]+content=[\"']([^\"']+)[\"']")
    if not href:
        return None
    resolved = urljoin(base_url, href)
    return resolved if _safe_gdelt_article_url(resolved) else None


def _article_published_at_from_html(html: str) -> str | None:
    for pattern in (
        r"<meta[^>]+property=[\"']article:published_time[\"'][^>]+content=[\"']([^\"']+)[\"']",
        r"<meta[^>]+name=[\"']pubdate[\"'][^>]+content=[\"']([^\"']+)[\"']",
        r"<meta[^>]+name=[\"']date[\"'][^>]+content=[\"']([^\"']+)[\"']",
    ):
        value = _html_field(html, pattern)
        if value and (parsed := _parse_metadata_datetime(value)):
            return parsed
    return None


def _html_field(html: str, pattern: str) -> str | None:
    match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return unescape(re.sub(r"\s+", " ", match.group(1)).strip())


def _parse_metadata_datetime(value: str) -> str | None:
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return _email_datetime(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _article_title_from_url_path(url: str) -> str | None:
    parsed = urlparse(url)
    candidates: list[tuple[int, str]] = []
    for raw_segment in parsed.path.split("/"):
        segment = raw_segment.strip()
        segment = re.sub(r"\.(html?|amp|php|aspx?)$", "", segment, flags=re.IGNORECASE)
        if not segment or segment.isdigit():
            continue
        words = [word for word in re.split(r"[-_\s]+", segment) if re.search(r"[A-Za-z]", word)]
        if len(words) < 3:
            continue
        candidates.append((len(words) * 10 + len(segment), segment))
    if not candidates:
        return None
    words = [word for word in re.split(r"[-_\s]+", max(candidates)[1]) if word]
    return _clean_article_title(" ".join(_title_word(word) for word in words))


def _clean_article_title(value: str) -> str | None:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(value))).strip()
    if not text:
        return None
    blocked = {
        "access denied",
        "attention required!",
        "403 forbidden",
        "404 not found",
        "just a moment...",
        "service unavailable",
    }
    lowered = text.lower()
    if lowered in blocked or lowered.startswith("gdelt event") or lowered.startswith("gdelt gkg"):
        return None
    return text[:280]


def _gdelt_source_report_title(source_url: str, actor1: str, actor2: str, place: str) -> str:
    source = _source_domain_display_name(source_url)
    actors = " / ".join(_title_phrase(value) for value in (actor1, actor2) if value.strip())
    subject = actors
    if not subject and place:
        subject = _title_phrase(place)
    if source and subject:
        return f"{source} source report: {subject}"
    if source:
        return f"{source} source report"
    if subject:
        return f"Source report: {subject}"
    return "Source-linked market report"


def _source_domain_display_name(url: str) -> str | None:
    host = urlparse(url).hostname or ""
    labels = [
        label
        for label in host.lower().split(".")
        if label and label not in {"www", "m", "mobile", "en", "eng", "news"}
    ]
    while labels and labels[-1] in {"com", "co", "net", "org", "eu", "pk", "uk", "jp", "kr", "au", "ca", "in"}:
        labels.pop()
    if not labels:
        return None
    known = {
        "aljazeera": "Al Jazeera",
        "arabnews": "Arab News",
        "hindustantimes": "Hindustan Times",
        "rferl": "Radio Free Europe",
        "radiofreeeurope": "Radio Free Europe",
        "themoscowtimes": "The Moscow Times",
        "wsj": "WSJ",
    }
    core = labels[-1]
    if core in known:
        return known[core]
    return " ".join(_title_word(word) for word in re.split(r"[-_]+", core) if word) or None


def _title_word(value: str) -> str:
    upper = value.upper()
    if upper in {"AI", "API", "BIS", "CPI", "ECB", "EU", "FOMC", "GDP", "HBM", "IEA", "IPO", "LNG", "NATO", "OPEC", "SEC", "TSMC", "UAE", "UK", "UN", "US", "USA", "WHO", "WTI"}:
        return upper
    if value.isupper() and len(value) <= 5:
        return value
    return value[:1].upper() + value[1:].lower()


def _title_phrase(value: str) -> str:
    return " ".join(_title_word(word) for word in re.split(r"\s+", value.strip().lower()) if word)


def _trusty_title_score(title: str) -> int:
    clean = _clean_article_title(title)
    if not clean:
        return 0
    return min(100, len(clean)) + (50 if not clean.lower().startswith("source report") else 0)


def _news_dedupe_key(*parts: str) -> str:
    return NEWS_DEDUPE_PREFIX + hashlib.sha256("|".join(parts).encode()).hexdigest()


def _parse_sec_submissions_json(  # NOSONAR - SEC recent-filings arrays are parsed in one aligned pass.
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


def _parse_gdelt_json(profile: SourceProfile, payload: dict[str, Any], *, max_documents: int) -> list[dict[str, Any]]:  # NOSONAR - GDELT article shape normalization stays in one parser.
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


def _parse_feed_xml(profile: SourceProfile, body: bytes, *, max_documents: int) -> list[dict[str, Any]]:  # NOSONAR - RSS/Atom variants are normalized in one parser.
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
    preserved_metadata = {
        key: value
        for key, value in payload.items()
        if key
        not in {
            "title",
            "url",
            "canonical_url",
            "snippet",
            "summary",
            "published_at",
            "fetched_at",
            "language",
            "source_region",
            "raw_hash",
            "normalized_hash",
            "dedupe_key",
        }
    }
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
        "raw_hash": SHA256_PREFIX + normalized.raw_hash,
        "normalized_hash": SHA256_PREFIX + normalized.normalized_hash,
        "trust_tier": profile.trust_tier,
        "copyright_mode": profile.copyright_mode,
        "discovery_only": profile.discovery_only,
        "retention_class": profile.retention_class,
        "source_type": profile.source_type,
        "source_name": profile.source_name,
        "symbols": list(profile.symbols),
        "entity_type": profile.entity_type,
        "fetch_profile": profile.fetch_profile,
        "dedupe_key": str(payload.get("dedupe_key") or "")
        or _news_dedupe_key(
            profile.source_key,
            normalized.canonical_url,
            normalized.title,
            normalized.published_at.isoformat() if normalized.published_at else "",
        ),
        **preserved_metadata,
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
    allow_http_hosts: frozenset[str] | set[str] | None = None,
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
            allow_http_hosts=allow_http_hosts,
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
    return SHA256_PREFIX + hashlib.sha256(encoded.encode()).hexdigest()


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


def _is_public_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    try:
        _ = parsed.port
    except ValueError:
        return False
    host = parsed.hostname.strip()
    if not host or any(char.isspace() for char in host):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not is_blocked_ip(str(ip))


def _is_gdelt_data_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return (
        parsed.scheme == "http"
        and parsed.hostname == "data.gdeltproject.org"
        and parsed.path.startswith("/gdeltv2/")
    )


def _first_nonempty(*values: Any) -> str:
    for value in values:
        clean = str(value or "").strip()
        if clean:
            return clean
    return ""


def _gdelt_file_datetime(value: str) -> str | None:
    clean = str(value or "").strip()
    if not clean:
        return None
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%dT%H%M%SZ", "%Y%m%d"):
        try:
            return datetime.strptime(clean, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def _gdelt_gkg_values(value: str, *, limit: int = 8) -> list[str]:
    result: list[str] = []
    for raw in str(value or "").split(";"):
        clean = raw.split(",", 1)[0].replace("_", " ").strip()
        if clean and clean not in result:
            result.append(clean)
        if len(result) >= limit:
            break
    return result


def _gdelt_gkg_locations(value: str, *, limit: int = 6) -> list[str]:
    result: list[str] = []
    for raw in str(value or "").split(";"):
        parts = raw.split("#")
        candidates = [part.strip() for part in parts[1:3] if part.strip()]
        for candidate in candidates:
            if candidate and candidate not in result:
                result.append(candidate)
        if len(result) >= limit:
            break
    return result


def _gdelt_gkg_snippet(themes: list[str], locations: list[str]) -> str:
    parts = []
    if themes:
        parts.append("themes: " + ", ".join(themes[:5]))
    if locations:
        parts.append("locations: " + ", ".join(locations[:5]))
    return "; ".join(parts)


def _gdelt_bulk_relevant(
    text: str, *, event_code: str = "", quad_class: str = ""
) -> bool:
    lower = text.replace("_", " ").replace("-", " ").lower()
    if any(_gdelt_relevance_term_matches(lower, term) for term in _GDELT_RELEVANCE_TERMS):
        return True
    if quad_class in {"3", "4"} and event_code[:2] in _GDELT_SEVERE_EVENT_ROOTS:
        return True
    return False


def _gdelt_relevance_term_matches(text: str, term: str) -> bool:
    if " " in term:
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


_GDELT_RELEVANCE_TERMS = (
    "attack",
    "blockade",
    "border",
    "central bank",
    "conflict",
    "coup",
    "crude",
    "energy",
    "export control",
    "gas",
    "geopolitical",
    "hormuz",
    "lng",
    "military",
    "missile",
    "nuclear",
    "oil",
    "outbreak",
    "pipeline",
    "rate decision",
    "red sea",
    "refinery",
    "sanction",
    "semiconductor",
    "shipping",
    "south china sea",
    "strait",
    "supply chain",
    "taiwan strait",
    "tariff",
    "trade war",
    "war",
)
_GDELT_SEVERE_EVENT_ROOTS = frozenset({"13", "14", "16", "17", "18", "19", "20"})


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
