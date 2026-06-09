from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from html import unescape
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx
from selectolax.parser import HTMLParser
from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.core.settings import get_settings
from frw_api.services.provider_limits import provider_request

LEGAL_USE_WARNING = (
    "OGE public financial disclosure reports may not be obtained or used for unlawful "
    "purposes, commercial purposes other than news/media dissemination to the public, "
    "credit-rating purposes, or solicitation purposes."
)

DISCLOSURE_LIMITATIONS = [
    "This is a source-linked public disclosure database, not a copy-trading signal.",
    "OGE data is delayed; Form 278-T may be filed up to 45 days after a transaction.",
    "OGE values are amount ranges, not exact trade sizes.",
    "OGE covers Donald J. Trump, spouse, and dependent-child transactions only where reportable in his filings.",
    "Adult family members are tracked only when they appear in SEC filings or issuer disclosures.",
    "SEC Form 144 is proposed sale intent, not proof the sale occurred.",
    "Schedule 13D/G is large beneficial ownership disclosure, not every trade.",
    "Ticker extraction from PDFs can be wrong; every row links back to the source filing.",
]

SEC_TARGET_FORMS = {"3", "4", "5", "144", "SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"}
OWNERSHIP_FORMS = {"3", "4", "5"}
DEFAULT_SEC_TARGETS = {"DJT": "0001849635"}
DONALD_TRUMP_OGE_NAME = "Trump, Donald J"
DEFAULT_OGE_NAMES = {"Trump, Donald J.", DONALD_TRUMP_OGE_NAME}
PUBLIC_TRANSACTION_MIN_CONFIDENCE = Decimal("0.90")
OGE_API_HOST = "https://extapps2.oge.gov"
SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
JSON_MIME = "application/json"
SHA256_PREFIX = "sha256:"

FORM4_TRANSACTION_CODES = {
    "P": "purchase",
    "S": "sale",
    "A": "issuer grant/acquisition",
    "D": "issuer disposition",
    "M": "option exercise/conversion",
    "F": "tax withholding/payment",
    "G": "gift",
    "J": "other",
    "V": "voluntarily reported earlier transaction",
}


async def ingest_trump_disclosures(
    db: Session,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    include_oge: bool = True,
    include_sec: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    ticker_map = await fetch_sec_ticker_map(transport=transport)
    filings: list[dict[str, Any]] = []
    warnings: list[str] = []

    if include_sec:
        sec_targets = _sec_targets_from_watchlist(db)
        sec_filings, sec_warnings = await fetch_sec_disclosure_filings(
            sec_targets,
            max_filings=settings.trump_disclosure_sec_filing_limit,
            transport=transport,
        )
        filings.extend(sec_filings)
        warnings.extend(sec_warnings)

    if include_oge:
        oge_names = _oge_names_from_watchlist(db)
        oge_filings, oge_warnings = await fetch_oge_disclosure_filings(
            oge_names,
            ticker_map=ticker_map,
            pdf_limit=settings.trump_disclosure_oge_pdf_limit,
            transport=transport,
        )
        filings.extend(oge_filings)
        warnings.extend(oge_warnings)

    counts = persist_disclosure_filings(db, filings)
    return {
        **counts,
        "warnings": warnings,
        "limitations": DISCLOSURE_LIMITATIONS,
    }


async def fetch_sec_ticker_map(
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, dict[str, str]]:
    settings = get_settings()
    headers = {
        "Accept": JSON_MIME,
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": settings.sec_user_agent,
    }
    async with httpx.AsyncClient(timeout=20, headers=headers, transport=transport) as client:
        try:
            response = await provider_request(
                client,
                "GET",
                SEC_TICKER_MAP_URL,
                provider_key="sec_edgar",
                endpoint_key="ticker_map",
            )
        except Exception:
            return {}
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for row in payload.values():
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        cik = str(row.get("cik_str") or "").zfill(10)
        title = str(row.get("title") or "")
        if ticker:
            result[ticker] = {"cik": cik, "title": title}
    return result


async def fetch_sec_disclosure_filings(
    targets: dict[str, str],
    *,
    max_filings: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    settings = get_settings()
    headers = {
        "Accept": JSON_MIME,
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": settings.sec_user_agent,
    }
    filings: list[dict[str, Any]] = []
    warnings: list[str] = []
    async with httpx.AsyncClient(timeout=25, headers=headers, transport=transport) as client:
        for label, cik in targets.items():
            padded = str(cik).zfill(10)
            try:
                response = await provider_request(
                    client,
                    "GET",
                    f"https://data.sec.gov/submissions/CIK{padded}.json",
                    provider_key="sec_edgar",
                    endpoint_key="submissions",
                    idempotency_key=f"submissions:{padded}",
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"SEC submissions unavailable for {label}: {exc}")
                continue
            payload = response.json()
            candidates = _extract_recent_sec_filings(label, padded, payload, max_filings=max_filings)
            for filing in candidates:
                if filing["form_type"] in OWNERSHIP_FORMS and filing.get("primary_document"):
                    try:
                        document_response = await provider_request(
                            client,
                            "GET",
                            filing["source_url"],
                            provider_key="sec_edgar",
                            endpoint_key="filing_document",
                            idempotency_key=f"filing:{filing['accession_number']}",
                        )
                    except Exception as exc:  # noqa: BLE001
                        filing["parse_status"] = "review_required"
                        filing["review_issues"].append(
                            {
                                "issue_type": "sec_document_download_failed",
                                "raw_excerpt": str(exc)[:1000],
                            }
                        )
                    else:
                        body = document_response.content
                        filing["sha256"] = _sha256_bytes(body)
                        _parse_sec_ownership_xml(filing, body)
                filings.append(filing)
    return filings, warnings


async def fetch_oge_disclosure_filings(
    oge_names: set[str],
    *,
    ticker_map: dict[str, dict[str, str]],
    pdf_limit: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    settings = get_settings()
    warnings: list[str] = []
    records = await _fetch_oge_records(transport=transport)
    if not records:
        warnings.append("OGE API returned no records; attempting static search-page fallback.")
        records = await _fetch_oge_records_from_search_page(transport=transport)
    filings: list[dict[str, Any]] = []
    transaction_records = [
        record
        for record in records
        if _is_oge_name(record, oge_names) and _is_oge_trade_report(record)
    ][:pdf_limit]
    headers = {"User-Agent": settings.sec_user_agent, "Accept": "application/pdf,*/*"}
    async with httpx.AsyncClient(timeout=30, headers=headers, transport=transport) as client:
        for record in transaction_records:
            pdf_url = _extract_pdf_url(str(record.get("type") or ""))
            if not pdf_url:
                warnings.append(f"OGE record missing PDF URL for {record.get('name')}")
                continue
            filing = _oge_filing_shell(record, pdf_url)
            try:
                response = await provider_request(
                    client,
                    "GET",
                    pdf_url,
                    provider_key="oge_disclosures",
                    endpoint_key="document_pdf",
                    idempotency_key=f"oge-pdf:{pdf_url}",
                )
            except Exception as exc:  # noqa: BLE001
                filing["parse_status"] = "review_required"
                filing["review_issues"].append(
                    {
                        "issue_type": "oge_pdf_download_failed",
                        "raw_excerpt": str(exc)[:1000],
                    }
                )
            else:
                body = response.content
                filing["sha256"] = _sha256_bytes(body)
                _parse_oge_pdf(filing, body, ticker_map=ticker_map)
            filings.append(filing)
    return filings, warnings


def persist_disclosure_filings(db: Session, filings: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"filings": 0, "transactions": 0, "review_items": 0}
    for filing in filings:
        filing_id = _upsert_source_filing(db, filing)
        counts["filings"] += 1
        for transaction in filing.get("transactions", []):
            _upsert_security_transaction(db, filing_id, transaction)
            counts["transactions"] += 1
        for issue in filing.get("review_issues", []):
            if _insert_review_issue(db, filing_id, issue):
                counts["review_items"] += 1
    return counts


def filings_response(
    db: Session,
    *,
    person: str | None = None,
    ticker: str | None = None,
    source: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    conditions = ["true"]
    params: dict[str, Any] = {"limit": min(max(limit, 1), 250)}
    if source:
        conditions.append("sf.source = :source")
        params["source"] = source.upper()
    if ticker:
        conditions.append("upper(sf.ticker) = :ticker")
        params["ticker"] = ticker.upper()
    if person:
        conditions.append(
            """
            (
              sf.filer_name ilike :person_like
              or exists (
                select 1 from security_transactions st
                where st.filing_id = sf.id
                  and (st.person_name ilike :person_like or st.owner_name ilike :person_like)
              )
            )
            """
        )
        params["person_like"] = f"%{person}%"
    rows = (
        db.execute(
            text(
                f"""
                select sf.*,
                       (select count(*) from security_transactions st where st.filing_id = sf.id) as transaction_count
                from source_filings sf
                where {' and '.join(conditions)}
                order by coalesce(sf.doc_date, cast(sf.created_at as date)) desc, sf.id desc
                limit :limit
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    return {"filings": [_jsonable(dict(row)) for row in rows], "limitations": DISCLOSURE_LIMITATIONS}


def transactions_response(
    db: Session,
    *,
    person: str | None = None,
    ticker: str | None = None,
    source: str | None = None,
    min_confidence: Decimal | None = PUBLIC_TRANSACTION_MIN_CONFIDENCE,
    limit: int = 100,
) -> dict[str, Any]:
    conditions = ["true"]
    params: dict[str, Any] = {"limit": min(max(limit, 1), 500)}
    if min_confidence is not None:
        conditions.append("coalesce(st.confidence, 0) >= :min_confidence")
        conditions.append("(st.source <> 'OGE' or st.ticker is not null)")
        params["min_confidence"] = float(min_confidence)
    if source:
        conditions.append("st.source = :source")
        params["source"] = source.upper()
    if ticker:
        conditions.append("upper(st.ticker) = :ticker")
        params["ticker"] = ticker.upper()
    if person:
        conditions.append("(st.person_name ilike :person_like or st.owner_name ilike :person_like)")
        params["person_like"] = f"%{person}%"
    rows = (
        db.execute(
            text(
                f"""
                select st.*, sf.source_url, sf.form_type, sf.filed_at, sf.doc_date
                from security_transactions st
                join source_filings sf on sf.id = st.filing_id
                where {' and '.join(conditions)}
                order by st.transaction_date desc nulls last, sf.doc_date desc nulls last, st.id desc
                limit :limit
                """
            ),
            params,
        )
        .mappings()
        .all()
    )
    return {
        "transactions": [_jsonable(dict(row)) for row in rows],
        "limitations": DISCLOSURE_LIMITATIONS,
        "min_confidence": _jsonable(min_confidence),
    }


def entity_insiders_response(db: Session, *, ticker: str, limit: int = 100) -> dict[str, Any]:
    payload = transactions_response(db, ticker=ticker, source="SEC", limit=limit)
    owners: dict[str, dict[str, Any]] = {}
    for row in payload["transactions"]:
        owner = row.get("owner_name") or row.get("person_name") or "Unknown owner"
        owners.setdefault(owner, {"owner_name": owner, "transactions": 0, "latest_transaction_date": None})
        owners[owner]["transactions"] += 1
        date_value = row.get("transaction_date")
        if date_value and (owners[owner]["latest_transaction_date"] is None or date_value > owners[owner]["latest_transaction_date"]):
            owners[owner]["latest_transaction_date"] = date_value
    return {
        "ticker": ticker.upper(),
        "insiders": sorted(owners.values(), key=lambda item: item["latest_transaction_date"] or "", reverse=True),
        **payload,
    }


def disclosure_summary_response(db: Session, *, limit: int = 50) -> dict[str, Any]:
    filings = filings_response(db, limit=limit)["filings"]
    transactions = transactions_response(db, limit=limit)["transactions"]
    watched_people = [
        _jsonable(dict(row))
        for row in db.execute(
            text(
                """
                select canonical_name, category, aliases, tickers, sec_ciks, oge_names, notes
                from watched_people
                order by
                  case category
                    when 'donald_trump' then 1
                    when 'spouse' then 2
                    when 'dependent_child' then 3
                    when 'adult_family' then 4
                    else 5
                  end,
                  canonical_name
                """
            )
        )
        .mappings()
        .all()
    ]
    review_count = int(
        db.execute(text("select count(*) from parse_review_queue where status = 'open'")).scalar_one()
    )
    return {
        "legal_use_warning": LEGAL_USE_WARNING,
        "limitations": DISCLOSURE_LIMITATIONS,
        "filings": filings,
        "transactions": transactions,
        "watched_people": watched_people,
        "open_review_items": review_count,
    }


def _sec_targets_from_watchlist(db: Session) -> dict[str, str]:
    rows = (
        db.execute(
            text(
                """
                select canonical_name, tickers, sec_ciks
                from watched_people
                where cardinality(sec_ciks) > 0
                order by canonical_name
                """
            )
        )
        .mappings()
        .all()
    )
    targets: dict[str, str] = {}
    for row in rows:
        label = str((row["tickers"] or [row["canonical_name"]])[0])
        for cik in row["sec_ciks"] or []:
            targets[label] = str(cik).zfill(10)
    return targets or DEFAULT_SEC_TARGETS.copy()


def _oge_names_from_watchlist(db: Session) -> set[str]:
    rows = db.execute(text("select oge_names from watched_people where cardinality(oge_names) > 0")).all()
    names = {str(name) for row in rows for name in (row[0] or []) if name}
    return names or DEFAULT_OGE_NAMES.copy()


async def _fetch_oge_records(*, transport: httpx.AsyncBaseTransport | None) -> list[dict[str, Any]]:
    settings = get_settings()
    page_size = settings.oge_disclosure_page_size
    max_records = settings.oge_disclosure_max_index_records
    records: list[dict[str, Any]] = []
    headers = {"Accept": JSON_MIME, "User-Agent": settings.sec_user_agent}
    async with httpx.AsyncClient(timeout=25, headers=headers, transport=transport) as client:
        start = 0
        while start < max_records:
            try:
                response = await provider_request(
                    client,
                    "GET",
                    f"{settings.oge_disclosure_api_base_url}?start={start}&length={page_size}",
                    provider_key="oge_disclosures",
                    endpoint_key="index",
                    idempotency_key=f"oge-index:{start}:{page_size}",
                )
            except Exception:
                return records
            payload = response.json()
            page = payload.get("data") if isinstance(payload, dict) else []
            if not isinstance(page, list) or not page:
                break
            records.extend(row for row in page if isinstance(row, dict))
            total = int(payload.get("recordsTotal") or len(records)) if isinstance(payload, dict) else len(records)
            start += page_size
            if start >= total:
                break
    return records


async def _fetch_oge_records_from_search_page(*, transport: httpx.AsyncBaseTransport | None) -> list[dict[str, Any]]:
    settings = get_settings()
    headers = {"Accept": "text/html", "User-Agent": settings.sec_user_agent}
    async with httpx.AsyncClient(timeout=20, headers=headers, transport=transport) as client:
        try:
            response = await provider_request(
                client,
                "GET",
                settings.oge_disclosure_search_url,
                provider_key="oge_disclosures",
                endpoint_key="index",
                idempotency_key="oge-search-page",
            )
        except Exception:
            return []
    html = response.text
    records = []
    for match in re.finditer(r"href=['\"]([^'\"]+\.pdf)['\"][^>]*>([^<]+)</a>", html, flags=re.I):
        url = urljoin(settings.oge_disclosure_search_url, unescape(match.group(1)))
        label = unescape(match.group(2))
        if "Trump" not in label or "278" not in label:
            continue
        records.append(
            {
                "type": f"<a href='{url}'>278 Transaction</a>",
                "name": DONALD_TRUMP_OGE_NAME,
                "agency": "White House Office",
                "title": "President",
                "level": "n/a",
                "docDate": "",
                "amended": "",
                "fallback_source": "static_search_page",
            }
        )
    return records


def _extract_recent_sec_filings(
    label: str,
    cik: str,
    payload: dict[str, Any],
    *,
    max_filings: int,
) -> list[dict[str, Any]]:
    filings = payload.get("filings", {}).get("recent", {}) if isinstance(payload, dict) else {}
    accessions = filings.get("accessionNumber", [])
    forms = filings.get("form", [])
    filing_dates = filings.get("filingDate", [])
    report_dates = filings.get("reportDate", [])
    acceptance_times = filings.get("acceptanceDateTime", [])
    primary_documents = filings.get("primaryDocument", [])
    issuer_name = str(payload.get("name") or label)
    ticker = _sec_payload_ticker(label, payload)
    rows: list[dict[str, Any]] = []
    for idx, accession in enumerate(accessions):
        form = str(_list_item(forms, idx) or "").upper()
        if form not in SEC_TARGET_FORMS:
            continue
        filing = _recent_sec_filing_row(
            label,
            cik,
            issuer_name,
            ticker,
            form=form,
            accession=str(accession),
            primary_document=str(_list_item(primary_documents, idx) or ""),
            filing_date=_list_item(filing_dates, idx),
            report_date=_list_item(report_dates, idx),
            acceptance_time=_list_item(acceptance_times, idx),
        )
        rows.append(filing)
        if len(rows) >= max_filings:
            break
    return rows


def _sec_payload_ticker(label: str, payload: dict[str, Any]) -> str | None:
    issuer_tickers = payload.get("tickers") or []
    if issuer_tickers:
        return str(issuer_tickers[0]).upper()
    if re.fullmatch(r"[A-Z.]{1,8}", label.upper()):
        return label.upper()
    return None


def _recent_sec_filing_row(
    label: str,
    cik: str,
    issuer_name: str,
    ticker: str | None,
    *,
    form: str,
    accession: str,
    primary_document: str,
    filing_date: Any,
    report_date: Any,
    acceptance_time: Any,
) -> dict[str, Any]:
    source_url = _sec_filing_url(cik, accession, primary_document)
    filed_at = _sec_acceptance_datetime(acceptance_time, filing_date)
    filing = {
        "source": "SEC",
        "form_type": form,
        "filer_name": issuer_name,
        "issuer_name": issuer_name,
        "ticker": ticker,
        "cik": str(cik).zfill(10),
        "accession_number": accession,
        "doc_date": _date_or_none(report_date) or _date_or_none(filing_date),
        "filed_at": filed_at.isoformat() if filed_at else None,
        "source_url": source_url,
        "primary_document": primary_document,
        "sha256": _sha256_text("SEC", accession, source_url),
        "raw_metadata": {
            "label": label,
            "form": form,
            "filing_date": filing_date,
            "report_date": report_date,
            "primary_document": primary_document,
        },
        "parse_status": "pending" if form not in OWNERSHIP_FORMS else "pending_xml",
        "transactions": [],
        "review_issues": [],
    }
    if form not in OWNERSHIP_FORMS:
        filing["review_issues"].append(
            {
                "issue_type": "sec_form_requires_manual_transaction_review",
                "raw_excerpt": f"{form} filings are source-linked but not reduced to trade rows automatically yet.",
            }
        )
    return filing


def _parse_sec_ownership_xml(filing: dict[str, Any], body: bytes) -> None:
    root = _sec_ownership_xml_root(filing, body)
    if root is None:
        return
    _strip_xml_namespaces(root)
    issuer_name = _xml_text(root, ".//issuer/issuerName") or filing.get("issuer_name")
    ticker = (_xml_text(root, ".//issuer/issuerTradingSymbol") or filing.get("ticker") or "").upper() or None
    issuer_cik = _xml_text(root, ".//issuer/issuerCik") or filing.get("cik")
    owner_names = _sec_xml_owner_names(root)
    owner_name = owner_names[0] if owner_names else filing.get("filer_name")
    transactions = _sec_xml_transactions(filing, root, owner_name, issuer_name, ticker, issuer_cik)
    _finish_sec_ownership_parse(
        filing,
        issuer_name=issuer_name,
        ticker=ticker,
        cik=issuer_cik,
        owner_names=owner_names,
        transactions=transactions,
        missing_issue_type="sec_ownership_xml_no_transactions",
        missing_excerpt="No derivative or non-derivative transaction rows were found.",
    )


def _sec_ownership_xml_root(
    filing: dict[str, Any], body: bytes
) -> ElementTree.Element | None:
    try:
        return ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        if body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
            _parse_sec_ownership_html(filing, body)
            return None
        filing["parse_status"] = "review_required"
        filing["review_issues"].append(
            {"issue_type": "sec_ownership_xml_parse_failed", "raw_excerpt": str(exc)}
        )
        return None


def _sec_xml_owner_names(root: ElementTree.Element) -> list[str]:
    return [
        name
        for name in (
            _xml_text(owner, "./reportingOwnerId/rptOwnerName")
            for owner in root.findall(".//reportingOwner")
        )
        if name
    ]


def _sec_xml_transactions(
    filing: dict[str, Any],
    root: ElementTree.Element,
    owner_name: str | None,
    issuer_name: str | None,
    ticker: str | None,
    issuer_cik: str | None,
) -> list[dict[str, Any]]:
    transactions: list[dict[str, Any]] = []
    for table_name, path in (
        ("non_derivative", ".//nonDerivativeTransaction"),
        ("derivative", ".//derivativeTransaction"),
    ):
        transactions.extend(
            transaction
            for row in root.findall(path)
            if (
                transaction := _sec_transaction_from_xml_row(
                    filing,
                    row,
                    table_name=table_name,
                    owner_name=owner_name,
                    issuer_name=issuer_name,
                    ticker=ticker,
                    cik=issuer_cik,
                )
            )
        )
    return transactions


def _parse_sec_ownership_html(filing: dict[str, Any], body: bytes) -> None:
    html = body.decode("utf-8", errors="ignore")
    parser = HTMLParser(html)
    owner_name, issuer_name = _sec_html_owner_and_issuer(parser, filing)
    ticker = _sec_html_ticker(html, filing)
    transactions = _sec_html_transactions(filing, parser, owner_name, issuer_name, ticker)
    raw_excerpt = parser.body.text(separator=" ", strip=True)[:1000] if parser.body else html[:1000]
    _finish_sec_ownership_parse(
        filing,
        issuer_name=issuer_name,
        ticker=ticker,
        cik=filing.get("cik"),
        owner_names=[owner_name] if owner_name else [],
        transactions=transactions,
        missing_issue_type="sec_ownership_html_no_transactions",
        missing_excerpt=raw_excerpt,
    )
    filing["raw_metadata"] = {
        **filing.get("raw_metadata", {}),
        "reporting_owners": [owner_name] if owner_name else [],
        "sec_document_format": "html_transform",
    }


def _sec_html_owner_and_issuer(
    parser: HTMLParser, filing: dict[str, Any]
) -> tuple[str | None, str | None]:
    cik_links = [link.text(strip=True) for link in parser.css("a[href*='CIK=']") if link.text(strip=True)]
    owner_name = cik_links[0] if cik_links else filing.get("filer_name")
    issuer_name = cik_links[1] if len(cik_links) > 1 else filing.get("issuer_name")
    return owner_name, issuer_name


def _sec_html_ticker(html: str, filing: dict[str, Any]) -> str | None:
    ticker_match = re.search(
        r"\[\s*<span[^>]*>\s*([A-Z0-9.\-]{1,10})\s*</span>\s*\]",
        html,
        flags=re.I,
    )
    return (ticker_match.group(1).upper() if ticker_match else filing.get("ticker")) or None


def _sec_html_transactions(
    filing: dict[str, Any],
    parser: HTMLParser,
    owner_name: str | None,
    issuer_name: str | None,
    ticker: str | None,
) -> list[dict[str, Any]]:
    transactions: list[dict[str, Any]] = []
    for table in parser.css("table"):
        table_name = _sec_html_table_name(table.text(separator=" ", strip=True))
        if table_name is None:
            continue
        transactions.extend(
            transaction
            for row in table.css("tbody tr")
            if (
                transaction := _sec_transaction_from_html_cells(
                    filing,
                    [_clean_html_cell(cell.text(separator=" ", strip=True)) for cell in row.css("td")],
                    table_name=table_name,
                    owner_name=owner_name,
                    issuer_name=issuer_name,
                    ticker=ticker,
                )
            )
        )
    return transactions


def _sec_html_table_name(table_text: str) -> str | None:
    if "Table II - Derivative" in table_text:
        return "derivative"
    if "Table I - Non-Derivative" in table_text:
        return "non_derivative"
    return None


def _finish_sec_ownership_parse(
    filing: dict[str, Any],
    *,
    issuer_name: str | None,
    ticker: str | None,
    cik: str | None,
    owner_names: list[str],
    transactions: list[dict[str, Any]],
    missing_issue_type: str,
    missing_excerpt: str,
) -> None:
    filing["issuer_name"] = issuer_name
    filing["ticker"] = ticker
    filing["cik"] = cik
    filing["raw_metadata"] = {
        **filing.get("raw_metadata", {}),
        "reporting_owners": owner_names,
    }
    filing["transactions"] = transactions
    filing["parse_status"] = "parsed" if transactions else "review_required"
    if not transactions:
        filing["review_issues"].append(
            {
                "issue_type": missing_issue_type,
                "raw_excerpt": missing_excerpt,
            }
        )


def _sec_transaction_from_html_cells(
    filing: dict[str, Any],
    cells: list[str],
    *,
    table_name: str,
    owner_name: str | None,
    issuer_name: str | None,
    ticker: str | None,
) -> dict[str, Any] | None:
    parsed_cells = _sec_html_transaction_cells(table_name, cells)
    if parsed_cells is None:
        return None
    asset, transaction_date_raw, code_raw, shares_raw, price_raw, post_raw, direct_indirect = parsed_cells
    transaction_date = _date_or_none(transaction_date_raw) or _us_date(transaction_date_raw)
    code_match = re.search(r"\b([A-Z])\b", code_raw or "")
    code = code_match.group(1) if code_match else ""
    if not transaction_date or not code:
        return None
    shares = _decimal_or_none(shares_raw)
    price = _decimal_or_none((price_raw or "").replace("$", ""))
    transaction_type = FORM4_TRANSACTION_CODES.get(code, "unknown")
    return {
        "source": "SEC",
        "person_name": owner_name,
        "owner_name": owner_name,
        "issuer_name": issuer_name,
        "ticker": ticker,
        "cik": filing.get("cik"),
        "asset_description": asset,
        "transaction_type": transaction_type,
        "transaction_code": code,
        "transaction_date": transaction_date.isoformat(),
        "amount_min": None,
        "amount_max": None,
        "shares": shares,
        "price": price,
        "direct_or_indirect": direct_indirect or None,
        "ownership_nature": cells[10] if table_name == "non_derivative" and len(cells) > 10 else None,
        "post_transaction_shares": _decimal_or_none(post_raw),
        "is_late": _is_late_sec_form4(filing.get("filed_at"), transaction_date),
        "source_page": None,
        "confidence": 0.93 if code in FORM4_TRANSACTION_CODES else 0.80,
        "raw_row": {"table": table_name, "cells": cells},
        "dedupe_key": _sha256_text(
            "SEC",
            filing.get("accession_number"),
            owner_name,
            asset,
            transaction_date.isoformat(),
            code,
            shares,
            price,
        ),
    }


def _sec_html_transaction_cells(
    table_name: str, cells: list[str]
) -> tuple[str, str, str, str, str | None, str | None, str | None] | None:
    if table_name == "non_derivative":
        if len(cells) < 10:
            return None
        asset, transaction_date_raw, _deemed, code_raw, _v, shares_raw, _acquired, price_raw, post_raw, direct_indirect = cells[:10]
        return asset, transaction_date_raw, code_raw, shares_raw, price_raw, post_raw, direct_indirect
    if len(cells) < 14:
        return None
    asset, _conversion_price, transaction_date_raw, _deemed, code_raw, _v, shares_raw, _acquired = cells[:8]
    post_raw = cells[13]
    direct_indirect = cells[14] if len(cells) > 14 else None
    return asset, transaction_date_raw, code_raw, shares_raw, None, post_raw, direct_indirect


def _sec_transaction_from_xml_row(
    filing: dict[str, Any],
    row: ElementTree.Element,
    *,
    table_name: str,
    owner_name: str | None,
    issuer_name: str | None,
    ticker: str | None,
    cik: str | None,
) -> dict[str, Any] | None:
    transaction_date = _date_or_none(_xml_text(row, "./transactionDate/value"))
    code = (_xml_text(row, "./transactionCoding/transactionCode") or "").upper()
    if not transaction_date or not code:
        return None
    shares = _decimal_or_none(_xml_text(row, "./transactionAmounts/transactionShares/value"))
    price = _decimal_or_none(_xml_text(row, "./transactionAmounts/transactionPricePerShare/value"))
    acquired_disposed = _xml_text(row, "./transactionAmounts/transactionAcquiredDisposedCode/value")
    transaction_type = FORM4_TRANSACTION_CODES.get(code, "unknown")
    if acquired_disposed == "D" and transaction_type == "unknown":
        transaction_type = "disposition"
    if acquired_disposed == "A" and transaction_type == "unknown":
        transaction_type = "acquisition"
    asset = _xml_text(row, "./securityTitle/value")
    raw_row = _xml_to_dict(row)
    return {
        "source": "SEC",
        "person_name": owner_name,
        "owner_name": owner_name,
        "issuer_name": issuer_name,
        "ticker": ticker,
        "cik": cik,
        "asset_description": asset,
        "transaction_type": transaction_type,
        "transaction_code": code,
        "transaction_date": transaction_date.isoformat(),
        "amount_min": None,
        "amount_max": None,
        "shares": shares,
        "price": price,
        "direct_or_indirect": _xml_text(row, "./ownershipNature/directOrIndirectOwnership/value"),
        "ownership_nature": _xml_text(row, "./ownershipNature/natureOfOwnership/value"),
        "post_transaction_shares": _decimal_or_none(_xml_text(row, "./postTransactionAmounts/sharesOwnedFollowingTransaction/value")),
        "is_late": _is_late_sec_form4(filing.get("filed_at"), transaction_date),
        "source_page": None,
        "confidence": 0.98 if code in FORM4_TRANSACTION_CODES else 0.82,
        "raw_row": {"table": table_name, **raw_row},
        "dedupe_key": _sha256_text(
            "SEC",
            filing.get("accession_number"),
            owner_name,
            asset,
            transaction_date.isoformat(),
            code,
            shares,
            price,
        ),
    }


def _oge_filing_shell(record: dict[str, Any], pdf_url: str) -> dict[str, Any]:
    doc_date = _date_or_none(str(record.get("docDate") or "")[:10])
    return {
        "source": "OGE",
        "form_type": "278-T",
        "filer_name": str(record.get("name") or DONALD_TRUMP_OGE_NAME),
        "issuer_name": None,
        "ticker": None,
        "cik": None,
        "accession_number": None,
        "doc_date": doc_date.isoformat() if doc_date else None,
        "filed_at": None,
        "source_url": pdf_url,
        "sha256": _sha256_text("OGE", pdf_url, record.get("docDate")),
        "raw_metadata": {"oge_record": record},
        "parse_status": "pending_pdf",
        "transactions": [],
        "review_issues": [],
    }


def _parse_oge_pdf(
    filing: dict[str, Any],
    body: bytes,
    *,
    ticker_map: dict[str, dict[str, str]],
) -> None:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # noqa: BLE001
        filing["parse_status"] = "review_required"
        filing["review_issues"].append(
            {
                "issue_type": "oge_pdf_parser_missing",
                "raw_excerpt": f"pypdf is not installed: {exc}",
            }
        )
        return
    try:
        reader = PdfReader(io.BytesIO(body))
        page_texts = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
    except Exception as exc:  # noqa: BLE001
        filing["parse_status"] = "review_required"
        filing["review_issues"].append({"issue_type": "oge_pdf_text_extraction_failed", "raw_excerpt": str(exc)})
        return
    transactions: list[dict[str, Any]] = []
    for page_number, page_text in enumerate(page_texts, start=1):
        transactions.extend(_parse_oge_text_page(filing, page_text, page_number=page_number, ticker_map=ticker_map))
    filing["transactions"] = transactions
    filing["parse_status"] = "parsed" if transactions else "review_required"
    if not transactions:
        filing["review_issues"].append(
            {
                "issue_type": "oge_pdf_no_transaction_rows",
                "raw_excerpt": "\n".join(page_texts)[:1000],
            }
        )
    low_confidence = [row for row in transactions if Decimal(str(row["confidence"])) < Decimal("0.90")]
    for row in low_confidence[:10]:
        filing["review_issues"].append(
            {
                "issue_type": "oge_low_confidence_parse",
                "raw_excerpt": str(row.get("asset_description") or "")[:1000],
                "suggested_fix": row,
            }
        )


def _parse_oge_text_page(
    filing: dict[str, Any],
    page_text: str,
    *,
    page_number: int,
    ticker_map: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    text_value = _normalize_pdf_text(page_text)
    rows: list[dict[str, Any]] = []
    for line in text_value.splitlines():
        numbered_line = _split_numbered_oge_line(line)
        if numbered_line is None:
            continue
        row_number, line_text = numbered_line
        row_text = " ".join(line_text.split())
        parsed = _oge_transaction_from_text(
            filing,
            row_text,
            page_number=page_number,
            row_number=row_number,
            ticker_map=ticker_map,
        )
        if parsed:
            rows.append(parsed)
    if rows:
        return rows
    for row_number, block_text in _oge_numbered_blocks(text_value):
        row_text = re.sub(r"\s+", " ", block_text).strip()
        parsed = _oge_transaction_from_text(
            filing,
            row_text,
            page_number=page_number,
            row_number=row_number,
            ticker_map=ticker_map,
        )
        if parsed:
            rows.append(parsed)
    return rows


def _oge_numbered_blocks(text_value: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    current_number: str | None = None
    current_lines: list[str] = []
    for line in text_value.splitlines():
        numbered_line = _split_numbered_oge_line(line)
        if numbered_line is not None:
            if current_number is not None:
                blocks.append((current_number, " ".join(current_lines)))
            current_number, line_text = numbered_line
            current_lines = [line_text]
        elif current_number is not None:
            current_lines.append(line)
    if current_number is not None:
        blocks.append((current_number, " ".join(current_lines)))
    return blocks


def _split_numbered_oge_line(line: str) -> tuple[str, str] | None:
    stripped = line.lstrip()
    digits = ""
    for char in stripped[:3]:
        if not char.isdigit():
            break
        digits += char
    if not digits:
        return None
    rest = stripped[len(digits) :]
    if not rest or not rest[0].isspace():
        return None
    text_value = rest.strip()
    return (digits, text_value) if text_value else None


def _oge_transaction_from_text(
    filing: dict[str, Any],
    row_text: str,
    *,
    page_number: int,
    row_number: str,
    ticker_map: dict[str, dict[str, str]],
) -> dict[str, Any] | None:
    parsed_date = _oge_row_transaction_date(row_text)
    if parsed_date is None:
        return None
    date_match, transaction_date = parsed_date
    amount_range = _parse_oge_amount_range(row_text)
    transaction_type, asset_description = _oge_row_transaction_type_and_asset(row_text, date_match)
    if not asset_description or len(asset_description) < 3:
        return None
    ticker = _extract_ticker(asset_description)
    ticker_valid = ticker is not None and ticker in ticker_map
    transaction_type = _normalize_oge_transaction_type(transaction_type)
    confidence = _oge_transaction_confidence(amount_range, transaction_type, ticker, ticker_valid)
    amount_min, amount_max = amount_range or (None, None)
    return {
        "source": "OGE",
        "person_name": "Donald J. Trump",
        "owner_name": filing.get("filer_name") or DONALD_TRUMP_OGE_NAME,
        "issuer_name": ticker_map.get(ticker or "", {}).get("title") if ticker_valid else None,
        "ticker": ticker if ticker_valid else None,
        "cik": ticker_map.get(ticker or "", {}).get("cik") if ticker_valid else None,
        "asset_description": asset_description[:1000],
        "transaction_type": transaction_type,
        "transaction_code": None,
        "transaction_date": transaction_date.isoformat(),
        "amount_min": amount_min,
        "amount_max": amount_max,
        "shares": None,
        "price": None,
        "direct_or_indirect": None,
        "ownership_nature": None,
        "post_transaction_shares": None,
        "is_late": " yes " in f" {row_text.lower()} ",
        "source_page": page_number,
        "confidence": confidence,
        "raw_row": {"row_number": row_number, "text": row_text, "ticker_candidate": ticker, "ticker_valid": ticker_valid},
        "dedupe_key": _sha256_text(
            "OGE",
            filing.get("sha256"),
            "Donald J. Trump",
            asset_description,
            transaction_type,
            transaction_date.isoformat(),
            amount_min,
            amount_max,
        ),
    }


def _oge_row_transaction_date(row_text: str) -> tuple[re.Match[str], date] | None:
    date_match = re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", row_text)
    if not date_match:
        return None
    transaction_date = _us_date(date_match.group(0))
    if not transaction_date:
        return None
    return date_match, transaction_date


def _oge_row_transaction_type_and_asset(row_text: str, date_match: re.Match[str]) -> tuple[str, str]:
    window_start = max(0, date_match.start() - 260)
    pre_date_window = row_text[window_start : date_match.start()]
    transaction_match = re.search(
        r"\b(purch[a-z0-9]*|sale|sold|exchange)\b",
        pre_date_window,
        flags=re.I,
    )
    if transaction_match:
        return (
            transaction_match.group(1).lower(),
            row_text[: window_start + transaction_match.start()].strip(" -"),
        )
    return "reported", row_text[: date_match.start()].strip(" -")


def _normalize_oge_transaction_type(transaction_type: str) -> str:
    if transaction_type.startswith("purch"):
        return "purchase"
    if transaction_type == "sold":
        return "sale"
    return transaction_type


def _oge_transaction_confidence(
    amount_range: tuple[Decimal | None, Decimal | None] | None,
    transaction_type: str,
    ticker: str | None,
    ticker_valid: bool,
) -> Decimal:
    if ticker and not ticker_valid:
        return Decimal("0.70")
    if amount_range and transaction_type != "reported" and ticker_valid:
        return Decimal("0.90")
    return Decimal("0.72")


def _upsert_source_filing(db: Session, filing: dict[str, Any]) -> int:
    return int(
        db.execute(
            text(
                """
                insert into source_filings(
                  source, form_type, filer_name, issuer_name, ticker, cik, accession_number,
                  doc_date, filed_at, source_url, local_path, sha256, raw_metadata, parse_status
                )
                values (
                  :source, :form_type, :filer_name, :issuer_name, :ticker, :cik, :accession_number,
                  cast(:doc_date as date), cast(:filed_at as timestamptz), :source_url, :local_path,
                  :sha256, cast(:raw_metadata as jsonb), :parse_status
                )
                on conflict (source, sha256) do update
                set form_type = excluded.form_type,
                    filer_name = excluded.filer_name,
                    issuer_name = excluded.issuer_name,
                    ticker = excluded.ticker,
                    cik = excluded.cik,
                    accession_number = excluded.accession_number,
                    doc_date = excluded.doc_date,
                    filed_at = excluded.filed_at,
                    source_url = excluded.source_url,
                    raw_metadata = excluded.raw_metadata,
                    parse_status = excluded.parse_status
                returning id
                """
            ),
            {
                "source": filing["source"],
                "form_type": filing["form_type"],
                "filer_name": filing.get("filer_name"),
                "issuer_name": filing.get("issuer_name"),
                "ticker": filing.get("ticker"),
                "cik": filing.get("cik"),
                "accession_number": filing.get("accession_number"),
                "doc_date": filing.get("doc_date"),
                "filed_at": filing.get("filed_at"),
                "source_url": filing["source_url"],
                "local_path": filing.get("local_path"),
                "sha256": filing["sha256"],
                "raw_metadata": json.dumps(filing.get("raw_metadata") or {}, default=str),
                "parse_status": filing.get("parse_status") or "pending",
            },
        ).scalar_one()
    )


def _upsert_security_transaction(db: Session, filing_id: int, transaction: dict[str, Any]) -> None:
    db.execute(
        text(
            """
            insert into security_transactions(
              filing_id, source, person_name, owner_name, issuer_name, ticker, cik,
              asset_description, transaction_type, transaction_code, transaction_date,
              amount_min, amount_max, shares, price, direct_or_indirect, ownership_nature,
              post_transaction_shares, is_late, source_page, confidence, raw_row, dedupe_key
            )
            values (
              :filing_id, :source, :person_name, :owner_name, :issuer_name, :ticker, :cik,
              :asset_description, :transaction_type, :transaction_code, cast(:transaction_date as date),
              :amount_min, :amount_max, :shares, :price, :direct_or_indirect, :ownership_nature,
              :post_transaction_shares, :is_late, :source_page, :confidence, cast(:raw_row as jsonb), :dedupe_key
            )
            on conflict (dedupe_key) do update
            set filing_id = excluded.filing_id,
                confidence = excluded.confidence,
                raw_row = excluded.raw_row
            """
        ),
        {
            **transaction,
            "filing_id": filing_id,
            "raw_row": json.dumps(transaction.get("raw_row") or {}, default=str),
        },
    )


def _insert_review_issue(db: Session, filing_id: int, issue: dict[str, Any]) -> bool:
    row_id = db.execute(
        text(
            """
            insert into parse_review_queue(filing_id, issue_type, raw_excerpt, suggested_fix)
            select :filing_id, :issue_type, :raw_excerpt, cast(:suggested_fix as jsonb)
            where not exists (
              select 1 from parse_review_queue
              where filing_id = :filing_id
                and issue_type = :issue_type
                and coalesce(raw_excerpt, '') = coalesce(:raw_excerpt, '')
                and status = 'open'
            )
            returning id
            """
        ),
        {
            "filing_id": filing_id,
            "issue_type": issue.get("issue_type") or "manual_review",
            "raw_excerpt": issue.get("raw_excerpt"),
            "suggested_fix": json.dumps(issue.get("suggested_fix") or {}, default=str),
        },
    ).scalar_one_or_none()
    return row_id is not None


def _is_oge_name(record: dict[str, Any], names: set[str]) -> bool:
    return str(record.get("name") or "").strip() in names


def _is_oge_trade_report(record: dict[str, Any]) -> bool:
    value = str(record.get("type") or "").lower()
    return "278 transaction" in value or "278t" in value or "278-t" in value


def _extract_pdf_url(type_field: str) -> str | None:
    match = re.search(r"href=['\"]([^'\"]+\.pdf)['\"]", type_field, flags=re.I)
    if not match:
        return None
    return urljoin(OGE_API_HOST, unescape(match.group(1).replace("\\/", "/")))


def _sec_filing_url(cik10: str, accession: str, primary_document: str) -> str:
    cik_no_zeroes = str(int(str(cik10).zfill(10)))
    accession_no_dashes = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_no_zeroes}/{accession_no_dashes}/"
    return f"{base}{primary_document}" if primary_document else base


def _normalize_pdf_text(value: str) -> str:
    normalized = value.replace("\u00a0", " ")
    return normalized.replace("•", " ").replace("·", " ")


def _clean_html_cell(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _parse_oge_amount_range(value: str) -> tuple[int | None, int | None] | None:
    text_value = value.replace("O", "0").replace("o", "0")
    over_index = text_value.casefold().find("over")
    if over_index >= 0:
        amount = _digits_to_int(text_value[over_index + len("over") :])
        return (amount, None) if amount is not None else None
    left, separator, right = text_value.replace("–", "-").rpartition("-")
    if not separator:
        return None
    low = _digits_to_int(_trailing_currency_fragment(left))
    high = _digits_to_int(_leading_currency_fragment(right))
    if low is None or high is None:
        return None
    return (low, high)


def _trailing_currency_fragment(value: str) -> str:
    dollar_index = value.rfind("$")
    ocr_dollar_index = value.rfind("S")
    start = max(dollar_index, ocr_dollar_index)
    return value[start + 1 :] if start >= 0 else value


def _leading_currency_fragment(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith(("$", "S")):
        stripped = stripped[1:]
    chars: list[str] = []
    for char in stripped:
        if char.isdigit() or char in {",", ".", " ", "S", "s", "O", "o"}:
            chars.append(char)
        elif chars:
            break
    return "".join(chars)


def _digits_to_int(value: str) -> int | None:
    clean = value.replace("S", "5").replace("s", "5").replace("O", "0").replace("o", "0")
    digits = re.sub(r"\D", "", clean)
    return int(digits) if digits else None


def _extract_ticker(asset_description: str) -> str | None:
    match = re.search(r"\(([A-Z][A-Z0-9.\-]{0,9})\)", asset_description)
    return match.group(1).upper() if match else None


def _is_late_sec_form4(filed_at: Any, transaction_date: date) -> bool | None:
    filed_date = _date_or_none(str(filed_at or "")[:10])
    if not filed_date:
        return None
    # A conservative calendar-day approximation for the two-business-day Form 4 rule.
    return filed_date > transaction_date + timedelta(days=4)


def _xml_text(root: ElementTree.Element, path: str) -> str | None:
    node = root.find(path)
    if node is None or node.text is None:
        return None
    text_value = node.text.strip()
    return text_value or None


def _xml_to_dict(root: ElementTree.Element) -> dict[str, Any]:
    children = list(root)
    if not children:
        return {root.tag: root.text.strip() if root.text else None}
    result: dict[str, Any] = {}
    for child in children:
        child_value = _xml_to_dict(child)
        key, value = next(iter(child_value.items()))
        if key in result:
            if not isinstance(result[key], list):
                result[key] = [result[key]]
            result[key].append(value)
        else:
            result[key] = value
    return {root.tag: result}


def _strip_xml_namespaces(root: ElementTree.Element) -> None:
    for element in root.iter():
        if "}" in element.tag:
            element.tag = element.tag.split("}", 1)[1]


def _list_item(values: Any, idx: int) -> Any:
    return values[idx] if isinstance(values, list) and idx < len(values) else None


def _date_or_none(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text_value = str(value or "")
    if not text_value:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text_value[:10], fmt).date()
        except ValueError:
            continue
    return None


def _us_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%m/%d/%Y").date()
    except ValueError:
        return None


def _sec_acceptance_datetime(value: Any, filing_date: Any) -> datetime | None:
    text_value = str(value or "")
    if re.fullmatch(r"\d{14}", text_value):
        return datetime.strptime(text_value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    parsed_date = _date_or_none(filing_date)
    return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc) if parsed_date else None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    match = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(value))
    if not match:
        return None
    try:
        return Decimal(match.group(0).replace(",", ""))
    except Exception:
        return None


def _sha256_bytes(value: bytes) -> str:
    return SHA256_PREFIX + hashlib.sha256(value).hexdigest()


def _sha256_text(*parts: Any) -> str:
    payload = "|".join("" if part is None else str(part) for part in parts)
    return SHA256_PREFIX + hashlib.sha256(payload.encode()).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
