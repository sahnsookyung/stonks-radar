from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from frw_api.core.settings import Settings, get_settings
from frw_api.services.job_queue import enqueue_job
from frw_api.services.market_history_store import expected_market_sessions
from frw_api.services.news.source_registry import SourceProfile
from frw_api.services.news.source_registry import enabled_news_sources


def trump_disclosure_job_specs(
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    if not settings.worker_scheduler_enabled:
        return []
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    timestamp = int(now.timestamp())
    specs: list[dict[str, Any]] = []
    if settings.trump_disclosure_sec_poll_seconds > 0:
        window = timestamp // settings.trump_disclosure_sec_poll_seconds
        specs.append(
            {
                "job_type": "trump_disclosures_ingest",
                "idempotency_key": f"trump-disclosures:sec:{window}",
                "payload": {"include_sec": True, "include_oge": False},
                "job_group": "disclosures",
                "priority": 40,
                "provider_key": "sec_edgar",
            }
        )
    if (
        settings.trump_disclosure_oge_poll_seconds > 0
        and settings.trump_disclosure_oge_pdf_limit > 0
    ):
        window = timestamp // settings.trump_disclosure_oge_poll_seconds
        specs.append(
            {
                "job_type": "trump_disclosures_ingest",
                "idempotency_key": f"trump-disclosures:oge:{window}",
                "payload": {"include_sec": False, "include_oge": True},
                "job_group": "disclosures",
                "priority": 80,
                "provider_key": "oge_disclosures",
            }
        )
    return specs


def snapshot_refresh_job_specs(
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    if not settings.worker_scheduler_enabled or settings.snapshot_refresh_seconds <= 0:
        return []
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    window = int(now.timestamp()) // settings.snapshot_refresh_seconds
    return [
        {
            "job_type": "snapshot_refresh",
            "idempotency_key": f"snapshot-refresh:{window}",
            "payload": {},
            "job_group": "snapshots",
            "priority": 60,
            "provider_key": "snapshot_refresh",
        }
    ]


def news_fetch_job_specs(
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    if (
        not settings.worker_scheduler_enabled
        or settings.news_source_refresh_seconds <= 0
    ):
        return []
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    specs: list[dict[str, Any]] = []
    sources = list(enabled_news_sources(settings=settings))
    offsets = _source_offsets(sources, settings=settings)
    timestamp = int(now.timestamp())
    for source in sources:
        poll_seconds = source_poll_seconds(source, settings)
        window = timestamp // poll_seconds
        window_start = datetime.fromtimestamp(window * poll_seconds, tz=timezone.utc)
        run_after = window_start + timedelta(seconds=offsets.get(source.source_key, 0))
        specs.append(
            {
                "job_type": "news.fetch_source",
                "idempotency_key": f"news-fetch:{source.source_key}:{window}",
                "payload": {
                    "source_key": source.source_key,
                    "query": source.default_query,
                    "max_documents": source_max_documents(source, settings),
                },
                "job_group": "news",
                "priority": 70,
                "provider_key": source.rate_limit_provider_key,
                "run_after": run_after,
            }
        )
    return specs


def source_poll_seconds(source: SourceProfile, settings: Settings) -> int:
    configured = source.poll_seconds or 0
    if configured > 0:
        return max(300, configured)
    if source.source_key == "who" or source.rate_limit_provider_key == "who":
        return 3600
    if (
        source.fetch_kind in {"html_index", "html_article"}
        or source.rate_limit_endpoint_key == "html"
    ):
        return 1800
    if source.rate_limit_provider_key in {
        "google_news_rss",
        "yahoo_finance_rss",
        "sec_edgar",
        "federal_reserve",
        "gdelt",
    }:
        return max(300, settings.news_source_refresh_seconds)
    return max(300, settings.news_source_refresh_seconds)


def source_max_documents(source: SourceProfile, settings: Settings) -> int:
    cap = settings.news_max_documents_per_source_per_run
    if source.rate_limit_provider_key in {
        "google_news_rss",
        "yahoo_finance_rss",
        "sec_edgar",
        "who",
        "federal_reserve",
    }:
        cap = min(cap, 20)
    elif source.rate_limit_provider_key == "company_ir" or source.fetch_kind in {
        "html_index",
        "html_article",
    }:
        cap = min(cap, 10)
    elif source.rate_limit_provider_key == "gdelt":
        cap = min(cap, 50)
    return max(1, cap)


def _source_offsets(
    sources: list[SourceProfile], *, settings: Settings
) -> dict[str, int]:
    grouped: dict[tuple[str, str, int], list[SourceProfile]] = {}
    for source in sources:
        key = (
            source.rate_limit_provider_key,
            source.rate_limit_endpoint_key,
            source_poll_seconds(source, settings),
        )
        grouped.setdefault(key, []).append(source)
    offsets: dict[str, int] = {}
    for (_provider, _endpoint, poll_seconds), group in grouped.items():
        ordered = sorted(group, key=lambda item: item.source_key)
        size = max(1, len(ordered))
        for index, source in enumerate(ordered):
            offsets[source.source_key] = int(index * poll_seconds / size)
    return offsets


def news_pipeline_job_specs(
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    if (
        not settings.worker_scheduler_enabled
        or settings.news_publication_interval_seconds <= 0
    ):
        return []
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    window = int(now.timestamp()) // settings.news_publication_interval_seconds
    purge_window = int(now.timestamp()) // 86_400
    return [
        {
            "job_type": "news.read_pages",
            "idempotency_key": f"news-read-pages:{window}",
            "payload": {"limit": settings.news_page_read_batch_limit},
            "job_group": "news",
            "priority": 68,
            "provider_key": "company_ir",
        },
        {
            "job_type": "news.normalize_document",
            "idempotency_key": f"news-normalize:{window}",
            "payload": {"limit": settings.news_processing_batch_limit},
            "job_group": "news",
            "priority": 68,
            "provider_key": "local",
        },
        {
            "job_type": "news.classify_entities",
            "idempotency_key": f"news-classify:{window}",
            "payload": {"limit": settings.news_processing_batch_limit},
            "job_group": "news",
            "priority": 68,
            "provider_key": "local",
        },
        {
            "job_type": "news.cluster_events",
            "idempotency_key": f"news-cluster:{window}",
            "payload": {"limit": settings.news_processing_batch_limit},
            "job_group": "news",
            "priority": 68,
            "provider_key": "local",
        },
        {
            "job_type": "news.score_events",
            "idempotency_key": f"news-score:{window}",
            "payload": {},
            "job_group": "news",
            "priority": 68,
            "provider_key": "local",
        },
        {
            "job_type": "news.purge_email_raw",
            "idempotency_key": f"news-purge-email-raw:{purge_window}",
            "payload": {"limit": 500},
            "job_group": "news",
            "priority": 68,
            "provider_key": "local",
        },
    ]


def market_history_job_specs(
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    if not settings.worker_scheduler_enabled or not getattr(
        settings, "market_data_scheduled_refresh_enabled", True
    ):
        return []
    symbols = list(
        dict.fromkeys(getattr(settings, "market_data_refresh_symbol_list", []))
    )
    if not symbols:
        return []
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    timestamp = int(now.timestamp())
    window = timestamp // 86_400
    window_start = datetime.fromtimestamp(window * 86_400, tz=timezone.utc)
    stagger_seconds = max(
        60, int(getattr(settings, "market_data_refresh_stagger_seconds", 3600))
    )
    daily_repair_days = int(getattr(settings, "market_data_daily_repair_days", 21))
    specs: list[dict[str, Any]] = []
    for symbol in symbols:
        offset = _stable_offset(symbol, stagger_seconds)
        specs.append(
            {
                "job_type": "market_data.refresh_history",
                "idempotency_key": f"market-history:daily:{symbol}:{window}",
                "payload": {
                    "symbol": symbol,
                    "mode": "daily_repair",
                    "days": daily_repair_days,
                },
                "job_group": "market_data",
                "priority": 65,
                "provider_key": "market_data",
                "run_after": window_start + timedelta(seconds=offset),
            }
        )
    # One symbol per day gets a deeper repair, spreading 3-year backfills across the month.
    backfill_days = int(getattr(settings, "market_data_full_backfill_days", 1095))
    if backfill_days > daily_repair_days:
        backfill_symbol = symbols[window % len(symbols)]
        specs.append(
            {
                "job_type": "market_data.refresh_history",
                "idempotency_key": f"market-history:backfill:{backfill_symbol}:{window}",
                "payload": {
                    "symbol": backfill_symbol,
                    "mode": "rolling_backfill",
                    "days": backfill_days,
                },
                "job_group": "market_data",
                "priority": 75,
                "provider_key": "market_data",
                "run_after": window_start
                + timedelta(
                    seconds=_stable_offset(
                        f"backfill:{backfill_symbol}", stagger_seconds
                    )
                ),
            }
        )
    return specs


def instrument_search_index_job_specs(
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    if (
        not settings.worker_scheduler_enabled
        or settings.instrument_universe_refresh_seconds <= 0
    ):
        return []
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    refresh_seconds = max(3600, int(settings.instrument_universe_refresh_seconds))
    window = int(now.timestamp()) // refresh_seconds
    window_start = datetime.fromtimestamp(window * refresh_seconds, tz=timezone.utc)
    return [
        {
            "job_type": "instrument_search_index_update",
            "idempotency_key": f"instrument-universe:{window}",
            "payload": {"source": "CONFIGURED_FREE_SOURCES", "mode": "FULL"},
            "job_group": "instrument_universe",
            "priority": 85,
            "provider_key": "instrument_universe",
            "run_after": window_start + timedelta(seconds=_stable_offset("instrument-universe", min(refresh_seconds, 3600))),
        }
    ]


def market_history_gap_job_specs(
    db: Session,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    if not settings.worker_scheduler_enabled or not getattr(
        settings, "market_data_scheduled_refresh_enabled", True
    ):
        return []
    symbols = list(
        dict.fromkeys(getattr(settings, "market_data_refresh_symbol_list", []))
    )
    if not symbols or not _table_available(db, "market_data_version"):
        return []
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    rows = _latest_market_data_versions(db, symbols)
    return _market_history_gap_specs_from_versions(
        symbols=symbols,
        latest_versions=rows,
        now=now,
        settings=settings,
    )


def schedule_due_jobs(
    db: Session, *, now: datetime | None = None, settings: Settings | None = None
) -> list[str]:
    job_ids: list[str] = []
    for spec in snapshot_refresh_job_specs(now=now, settings=settings):
        job_ids.append(enqueue_job(db, **spec))
    for spec in market_history_gap_job_specs(db, now=now, settings=settings):
        symbol = str(spec.get("payload", {}).get("symbol") or "")
        if symbol and _has_nonterminal_market_history(
            db, symbol, str(spec["idempotency_key"])
        ):
            continue
        job_ids.append(enqueue_job(db, **spec))
    for spec in market_history_job_specs(now=now, settings=settings):
        symbol = str(spec.get("payload", {}).get("symbol") or "")
        if symbol and _has_nonterminal_market_history(
            db, symbol, str(spec["idempotency_key"])
        ):
            continue
        job_ids.append(enqueue_job(db, **spec))
    for spec in instrument_search_index_job_specs(now=now, settings=settings):
        if _has_nonterminal_instrument_index(db, str(spec["idempotency_key"])):
            continue
        job_ids.append(enqueue_job(db, **spec))
    for spec in news_fetch_job_specs(now=now, settings=settings):
        source_key = str(spec.get("payload", {}).get("source_key") or "")
        if source_key and _has_nonterminal_fetch(
            db, source_key, str(spec["idempotency_key"])
        ):
            continue
        job_ids.append(enqueue_job(db, **spec))
    previous_news_pipeline_job_id: str | None = None
    for spec in news_pipeline_job_specs(now=now, settings=settings):
        if previous_news_pipeline_job_id:
            spec = {**spec, "depends_on_job_id": previous_news_pipeline_job_id}
        previous_news_pipeline_job_id = enqueue_job(db, **spec)
        job_ids.append(previous_news_pipeline_job_id)
    for spec in trump_disclosure_job_specs(now=now, settings=settings):
        job_ids.append(enqueue_job(db, **spec))
    return job_ids


def _has_nonterminal_fetch(db: Session, source_key: str, idempotency_key: str) -> bool:
    row = db.execute(
        text(
            """
            select 1
            from job_queue
            where job_type = 'news.fetch_source'
              and payload->>'source_key' = :source_key
              and status in ('queued','running','retry_wait','quota_wait')
              and idempotency_key <> :idempotency_key
            limit 1
            """
        ),
        {"source_key": source_key, "idempotency_key": idempotency_key},
    ).scalar_one_or_none()
    return row is not None


def _has_nonterminal_market_history(
    db: Session, symbol: str, idempotency_key: str
) -> bool:
    row = db.execute(
        text(
            """
            select 1
            from job_queue
            where job_type = 'market_data.refresh_history'
              and payload->>'symbol' = :symbol
              and status in ('queued','running','retry_wait','quota_wait')
              and idempotency_key <> :idempotency_key
            limit 1
            """
        ),
        {"symbol": symbol, "idempotency_key": idempotency_key},
    ).scalar_one_or_none()
    return row is not None


def _has_nonterminal_instrument_index(db: Session, idempotency_key: str) -> bool:
    row = db.execute(
        text(
            """
            select 1
            from job_queue
            where job_type = 'instrument_search_index_update'
              and status in ('queued','running','retry_wait','quota_wait')
              and idempotency_key <> :idempotency_key
            limit 1
            """
        ),
        {"idempotency_key": idempotency_key},
    ).scalar_one_or_none()
    return row is not None


def _latest_market_data_versions(
    db: Session, symbols: list[str]
) -> dict[str, date | None]:
    stmt = text(
        """
            select symbol, latest_price_date
            from market_data_version
            where interval = '1day'
              and symbol in :symbols
            """
    ).bindparams(bindparam("symbols", expanding=True))
    rows = db.execute(stmt, {"symbols": tuple(symbols)}).mappings().all()
    latest = {symbol: None for symbol in symbols}
    for row in rows:
        latest[str(row["symbol"])] = row["latest_price_date"]
    return latest


def _market_history_gap_specs_from_versions(
    *,
    symbols: list[str],
    latest_versions: dict[str, date | None],
    now: datetime,
    settings: Settings,
) -> list[dict[str, Any]]:
    end = now.date()
    repair_days = int(getattr(settings, "market_data_daily_repair_days", 21))
    stagger_seconds = max(
        60, int(getattr(settings, "market_data_refresh_stagger_seconds", 3600))
    )
    specs: list[dict[str, Any]] = []
    for symbol in symbols:
        latest_date = latest_versions.get(symbol)
        start = (
            (latest_date + timedelta(days=1))
            if latest_date
            else end - timedelta(days=repair_days)
        )
        if start > end:
            continue
        missing = expected_market_sessions(symbol, start, end)
        if not missing:
            continue
        newest_first = sorted(missing, reverse=True)
        latest_missing = newest_first[0]
        earliest_missing = newest_first[-1]
        window = int(now.timestamp()) // 86_400
        specs.append(
            {
                "job_type": "market_data.refresh_history",
                "idempotency_key": f"market-history:gap:{symbol}:{latest_missing.isoformat()}:{window}",
                "payload": {
                    "symbol": symbol,
                    "mode": "gap_catchup",
                    "start": earliest_missing.isoformat(),
                    "end": latest_missing.isoformat(),
                    "missing_dates": [item.isoformat() for item in newest_first[:20]],
                },
                "job_group": "market_data",
                "priority": 55,
                "provider_key": "market_data",
                "run_after": now
                + timedelta(
                    seconds=_stable_offset(f"gap:{symbol}", min(stagger_seconds, 900))
                ),
            }
        )
    return sorted(
        specs,
        key=lambda spec: (spec["payload"]["end"], spec["payload"]["symbol"]),
        reverse=True,
    )


def _table_available(db: Session, table_name: str) -> bool:
    try:
        row = db.execute(
            text("select to_regclass(:table_name)"), {"table_name": table_name}
        ).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - scheduler must keep running against partially migrated databases
        return False
    return row is not None


def _stable_offset(key: str, modulo_seconds: int) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % max(1, modulo_seconds)
