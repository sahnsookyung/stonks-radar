import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from frw_worker.scheduler import (
    _market_history_gap_specs_from_versions,
    instrument_search_index_job_specs,
    market_history_job_specs,
    news_fetch_job_specs,
    news_pipeline_job_specs,
    schedule_due_jobs,
    snapshot_refresh_job_specs,
    source_max_documents,
    source_poll_seconds,
    trump_disclosure_job_specs,
)
from frw_api.services.news.source_registry import source_registry
from frw_worker.tasks import handle_job


def _settings(**overrides):
    values = {
        "worker_scheduler_enabled": True,
        "trump_disclosure_sec_poll_seconds": 1800,
        "trump_disclosure_oge_poll_seconds": 86400,
        "trump_disclosure_oge_pdf_limit": 12,
        "snapshot_refresh_seconds": 900,
        "news_source_refresh_seconds": 900,
        "news_publication_interval_seconds": 300,
        "news_max_documents_per_source_per_run": 100,
        "news_processing_batch_limit": 500,
        "news_page_read_batch_limit": 25,
        "news_rss_enabled": True,
        "news_gdelt_enabled": False,
        "news_public_health_enabled": True,
        "news_auto_review_trusted_events": True,
        "market_data_scheduled_refresh_enabled": True,
        "market_data_refresh_symbol_list": [],
        "market_data_daily_repair_days": 21,
        "market_data_full_backfill_days": 1095,
        "market_data_refresh_stagger_seconds": 3600,
        "instrument_universe_refresh_seconds": 14400,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_trump_disclosure_scheduler_creates_sec_and_daily_oge_specs():
    now = datetime(2026, 5, 26, 1, 17, tzinfo=timezone.utc)

    specs = trump_disclosure_job_specs(now=now, settings=_settings())

    assert [spec["provider_key"] for spec in specs] == ["sec_edgar", "oge_disclosures"]
    assert specs[0]["payload"] == {"include_sec": True, "include_oge": False}
    assert specs[1]["payload"] == {"include_sec": False, "include_oge": True}
    assert specs[0]["idempotency_key"].startswith("trump-disclosures:sec:")
    assert specs[1]["idempotency_key"].startswith("trump-disclosures:oge:")


def test_trump_disclosure_scheduler_can_skip_oge_when_pdf_limit_disabled():
    specs = trump_disclosure_job_specs(
        now=datetime(2026, 5, 26, 1, 17, tzinfo=timezone.utc),
        settings=_settings(trump_disclosure_oge_pdf_limit=0),
    )

    assert [spec["provider_key"] for spec in specs] == ["sec_edgar"]


def test_trump_disclosure_scheduler_can_be_disabled():
    specs = trump_disclosure_job_specs(
        now=datetime(2026, 5, 26, 1, 17, tzinfo=timezone.utc),
        settings=_settings(worker_scheduler_enabled=False),
    )

    assert specs == []


def test_snapshot_refresh_scheduler_creates_15_minute_spec():
    specs = snapshot_refresh_job_specs(
        now=datetime(2026, 5, 26, 1, 17, tzinfo=timezone.utc), settings=_settings()
    )

    assert specs == [
        {
            "job_type": "snapshot_refresh",
            "idempotency_key": "snapshot-refresh:1977509",
            "payload": {},
            "job_group": "snapshots",
            "priority": 60,
            "provider_key": "snapshot_refresh",
        }
    ]


def test_snapshot_refresh_scheduler_can_be_disabled():
    specs = snapshot_refresh_job_specs(
        now=datetime(2026, 5, 26, 1, 17, tzinfo=timezone.utc),
        settings=_settings(worker_scheduler_enabled=False),
    )

    assert specs == []


def test_news_fetch_scheduler_creates_enabled_source_specs():
    specs = news_fetch_job_specs(
        now=datetime(2026, 5, 26, 1, 17, tzinfo=timezone.utc), settings=_settings()
    )
    keys = {spec["payload"]["source_key"] for spec in specs}

    assert {"federal_reserve", "who", "google_news_rss"}.issubset(keys)
    assert "gdelt" not in keys
    assert all(spec["job_type"] == "news.fetch_source" for spec in specs)
    assert all(spec["job_group"] == "news" for spec in specs)
    assert all("run_after" in spec for spec in specs)


def test_news_fetch_scheduler_applies_source_cadence_and_caps():
    settings = _settings(news_max_documents_per_source_per_run=100)
    profiles = source_registry()

    assert source_poll_seconds(profiles["who"], settings) == 3600
    assert source_poll_seconds(profiles["nvidia_newsroom"], settings) == 900
    assert source_poll_seconds(profiles["rocket_lab_ir"], settings) == 1800
    assert source_max_documents(profiles["who"], settings) == 20
    assert source_max_documents(profiles["google_news_rss"], settings) == 20


def test_news_fetch_scheduler_respects_source_toggles():
    specs = news_fetch_job_specs(
        now=datetime(2026, 5, 26, 1, 17, tzinfo=timezone.utc),
        settings=_settings(
            news_rss_enabled=False,
            news_public_health_enabled=False,
            news_gdelt_enabled=True,
        ),
    )
    keys = {spec["payload"]["source_key"] for spec in specs}

    assert "google_news_rss" not in keys
    assert not any(key.startswith("google_news_") for key in keys)
    assert not any(key.startswith("yahoo_finance_") for key in keys)
    assert "who" not in keys
    assert "gdelt" in keys


def test_news_pipeline_scheduler_creates_local_processing_specs():
    specs = news_pipeline_job_specs(
        now=datetime(2026, 5, 26, 1, 17, tzinfo=timezone.utc), settings=_settings()
    )

    assert [spec["job_type"] for spec in specs] == [
        "news.read_pages",
        "news.normalize_document",
        "news.classify_entities",
        "news.cluster_events",
        "news.score_events",
        "news.purge_email_raw",
    ]
    assert [spec["provider_key"] for spec in specs] == [
        "company_ir",
        "local",
        "local",
        "local",
        "local",
        "local",
    ]


def test_news_pipeline_scheduler_chains_local_processing_jobs(monkeypatch):
    calls = []

    def fake_enqueue(db, **spec):
        calls.append(spec)
        return f"job-{len(calls)}"

    monkeypatch.setattr("frw_worker.scheduler.enqueue_job", fake_enqueue)

    job_ids = schedule_due_jobs(
        object(),
        now=datetime(2026, 5, 26, 1, 17, tzinfo=timezone.utc),
        settings=_settings(
            snapshot_refresh_seconds=0,
            news_source_refresh_seconds=0,
            trump_disclosure_sec_poll_seconds=0,
            trump_disclosure_oge_poll_seconds=0,
            instrument_universe_refresh_seconds=0,
        ),
    )

    assert job_ids == ["job-1", "job-2", "job-3", "job-4", "job-5", "job-6"]
    assert calls[0].get("depends_on_job_id") is None
    assert [call.get("depends_on_job_id") for call in calls[1:]] == [
        "job-1",
        "job-2",
        "job-3",
        "job-4",
        "job-5",
    ]


def test_market_history_scheduler_staggers_full_window_refresh_specs_after_close():
    specs = market_history_job_specs(
        now=datetime(2026, 5, 26, 14, 17, tzinfo=timezone.utc),
        settings=_settings(
            market_data_refresh_symbol_list=["AAPL", "MSFT"],
            market_data_full_backfill_days=21,
            market_data_refresh_after_close_minutes=45,
            market_data_refresh_spread_minutes=240,
            market_data_snapshot_window_days=1095,
        ),
    )

    assert [spec["job_type"] for spec in specs] == [
        "market_data.refresh_history",
        "market_data.refresh_history",
    ]
    assert {spec["payload"]["symbol"] for spec in specs} == {"AAPL", "MSFT"}
    assert all(spec["payload"]["mode"] == "rolling_3y_snapshot" for spec in specs)
    assert all(spec["payload"]["window_key"] == "rolling_3y" for spec in specs)
    assert all(spec["payload"]["window_days"] == 1095 for spec in specs)
    assert all(spec["payload"]["market_session_date"] == "2026-05-26" for spec in specs)
    assert all(spec["payload"]["start"] == "2023-05-27" for spec in specs)
    assert all(spec["payload"]["end"] == "2026-05-26" for spec in specs)
    assert all(spec["job_group"] == "market_data" for spec in specs)
    assert all("run_after" in spec for spec in specs)
    assert all(spec["run_after"] >= datetime(2026, 5, 26, 20, 45, tzinfo=timezone.utc) for spec in specs)
    assert all(spec["run_after"] < datetime(2026, 5, 27, 0, 45, tzinfo=timezone.utc) for spec in specs)


def test_market_history_scheduler_does_not_add_separate_incremental_backfill():
    specs = market_history_job_specs(
        now=datetime(2026, 5, 26, 14, 17, tzinfo=timezone.utc),
        settings=_settings(
            market_data_refresh_symbol_list=["AAPL", "MSFT"],
            market_data_daily_repair_days=21,
            market_data_full_backfill_days=1095,
            market_data_snapshot_window_days=1095,
        ),
    )

    backfills = [
        spec for spec in specs if spec["payload"]["mode"] == "rolling_backfill"
    ]
    assert backfills == []
    assert {spec["payload"]["mode"] for spec in specs} == {"rolling_3y_snapshot"}


def test_market_history_scheduler_uses_early_close_anchor():
    specs = market_history_job_specs(
        now=datetime(2026, 11, 27, 15, 0, tzinfo=timezone.utc),
        settings=_settings(
            market_data_refresh_symbol_list=["AAPL"],
            market_data_refresh_after_close_minutes=45,
            market_data_refresh_spread_minutes=15,
            market_data_snapshot_window_days=1095,
        ),
    )

    assert specs[0]["payload"]["market_session_date"] == "2026-11-27"
    assert specs[0]["run_after"] >= datetime(2026, 11, 27, 18, 45, tzinfo=timezone.utc)
    assert specs[0]["run_after"] < datetime(2026, 11, 27, 19, 0, tzinfo=timezone.utc)


def test_instrument_search_index_scheduler_creates_four_hour_refresh_spec():
    specs = instrument_search_index_job_specs(
        now=datetime(2026, 5, 26, 1, 17, tzinfo=timezone.utc),
        settings=_settings(),
    )

    assert specs == [
        {
            "job_type": "instrument_search_index_update",
            "idempotency_key": "instrument-universe:123594",
            "payload": {"source": "CONFIGURED_FREE_SOURCES", "mode": "FULL"},
            "job_group": "instrument_universe",
            "priority": 85,
            "provider_key": "instrument_universe",
            "run_after": specs[0]["run_after"],
        }
    ]
    assert specs[0]["run_after"].date().isoformat() == "2026-05-26"


def test_instrument_search_index_scheduler_has_one_hour_floor():
    specs = instrument_search_index_job_specs(
        now=datetime(2026, 5, 26, 1, 17, tzinfo=timezone.utc),
        settings=_settings(instrument_universe_refresh_seconds=60),
    )

    assert specs[0]["idempotency_key"] == "instrument-universe:494377"


def test_instrument_search_index_scheduler_can_be_disabled():
    specs = instrument_search_index_job_specs(
        now=datetime(2026, 5, 26, 1, 17, tzinfo=timezone.utc),
        settings=_settings(instrument_universe_refresh_seconds=0),
    )

    assert specs == []


def test_market_history_gap_scheduler_enqueues_newest_first_catchup():
    specs = _market_history_gap_specs_from_versions(
        symbols=["AAPL", "BTC-USD"],
        latest_versions={
            "AAPL": datetime(2026, 1, 2, tzinfo=timezone.utc).date(),
            "BTC-USD": datetime(2026, 1, 3, tzinfo=timezone.utc).date(),
        },
        now=datetime(2026, 1, 5, 12, tzinfo=timezone.utc),
        settings=_settings(),
    )

    assert [spec["payload"]["mode"] for spec in specs] == [
        "full_window_catchup",
        "full_window_catchup",
    ]
    assert specs[0]["payload"]["end"] == "2026-01-05"
    assert specs[0]["priority"] == 55
    btc = next(spec for spec in specs if spec["payload"]["symbol"] == "BTC-USD")
    assert btc["payload"]["missing_dates"] == ["2026-01-05", "2026-01-04"]
    assert btc["payload"]["start"] == "2023-01-06"
    assert btc["payload"]["window_key"] == "rolling_3y"


def test_trump_disclosure_job_dispatches_ingestion(monkeypatch):
    calls = []
    commits = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def commit(self):
            commits.append(True)

    async def fake_ingest(db, *, include_oge, include_sec):
        calls.append({"db": db, "include_oge": include_oge, "include_sec": include_sec})
        return {"filings": 1, "transactions": 2, "review_items": 0, "warnings": []}

    heartbeat_count = 0

    async def heartbeat():
        nonlocal heartbeat_count
        heartbeat_count += 1

    monkeypatch.setattr("frw_worker.tasks.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("frw_worker.tasks.ingest_trump_disclosures", fake_ingest)

    result = asyncio.run(
        handle_job(
            {
                "job_type": "trump_disclosures_ingest",
                "payload": {"include_oge": False, "include_sec": True},
            },
            heartbeat,
        )
    )

    assert result["transactions"] == 2
    assert calls[0]["include_oge"] is False
    assert calls[0]["include_sec"] is True
    assert heartbeat_count == 1
    assert commits == [True]


def test_news_fetch_job_dispatches_ingestion(monkeypatch):
    calls = []
    commits = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def commit(self):
            commits.append(True)

    async def fake_fetch(db, *, source_key, query=None, max_documents=None):
        calls.append(
            {
                "db": db,
                "source_key": source_key,
                "query": query,
                "max_documents": max_documents,
            }
        )
        return {"source_key": source_key, "documents": 2, "persisted": {"documents": 2}}

    heartbeat_count = 0

    async def heartbeat():
        nonlocal heartbeat_count
        heartbeat_count += 1

    monkeypatch.setattr("frw_worker.tasks.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("frw_worker.tasks.fetch_news_source", fake_fetch)

    result = asyncio.run(
        handle_job(
            {
                "job_type": "news.fetch_source",
                "payload": {
                    "source_key": "google_news_rss",
                    "query": "semiconductors",
                    "max_documents": 5,
                },
            },
            heartbeat,
        )
    )

    assert result["documents"] == 2
    assert calls == [
        {
            "db": calls[0]["db"],
            "source_key": "google_news_rss",
            "query": "semiconductors",
            "max_documents": 5,
        }
    ]
    assert heartbeat_count == 1
    assert commits == [True]


def test_instrument_refresh_job_rebuilds_local_index(monkeypatch):
    calls = []

    def fake_refresh(*, source, mode):
        calls.append({"source": source, "mode": mode})
        return {"status": "refreshed", "instrument_count": 12, "listing_count": 13}

    heartbeat_count = 0

    async def heartbeat():
        nonlocal heartbeat_count
        heartbeat_count += 1

    monkeypatch.setattr("frw_worker.tasks.refresh_instrument_index", fake_refresh)

    result = asyncio.run(
        handle_job(
            {
                "job_type": "instrument_search_index_update",
                "payload": {"source": "LOCAL_STATIC_INDEX", "mode": "FULL"},
            },
            heartbeat,
        )
    )

    assert result == {
        "status": "refreshed",
        "instrument_count": 12,
        "listing_count": 13,
    }
    assert calls == [{"source": "LOCAL_STATIC_INDEX", "mode": "FULL"}]
    assert heartbeat_count == 1


def test_snapshot_refresh_job_builds_and_publishes(monkeypatch):
    calls = []
    commits = []

    class FakeResult:
        def __init__(self, snapshot_version):
            self.files = ["manifest.json"]
            self.uploaded = False
            self.destination = "/tmp/public"
            self.snapshot_version = snapshot_version

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def commit(self):
            commits.append(True)

    def fake_build(db, *, generated_by=None):
        calls.append(("build", generated_by))
        return FakeResult(42)

    def fake_publish(db, *, snapshot_version, generated_by=None):
        calls.append(("publish", snapshot_version, generated_by))
        return FakeResult(snapshot_version)

    heartbeat_count = 0

    async def heartbeat():
        nonlocal heartbeat_count
        heartbeat_count += 1

    monkeypatch.setattr("frw_worker.tasks.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("frw_worker.tasks.build_candidate_snapshots", fake_build)
    monkeypatch.setattr("frw_worker.tasks.publish_snapshots", fake_publish)

    result = asyncio.run(
        handle_job(
            {"job_type": "snapshot_refresh", "payload": {"requested_by": "scheduler"}},
            heartbeat,
        )
    )

    assert result["status"] == "published"
    assert result["built"]["snapshot_version"] == 42
    assert calls == [("build", None), ("publish", 42, None)]
    assert heartbeat_count == 2
    assert commits == [True, True]
