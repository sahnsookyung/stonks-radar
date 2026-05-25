import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from frw_worker.scheduler import trump_disclosure_job_specs
from frw_worker.tasks import handle_job


def _settings(**overrides):
    values = {
        "worker_scheduler_enabled": True,
        "trump_disclosure_sec_poll_seconds": 1800,
        "trump_disclosure_oge_poll_seconds": 86400,
        "trump_disclosure_oge_pdf_limit": 12,
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
            {"job_type": "trump_disclosures_ingest", "payload": {"include_oge": False, "include_sec": True}},
            heartbeat,
        )
    )

    assert result["transactions"] == 2
    assert calls[0]["include_oge"] is False
    assert calls[0]["include_sec"] is True
    assert heartbeat_count == 1
    assert commits == [True]
