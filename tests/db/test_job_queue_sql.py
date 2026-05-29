from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from frw_api.services.job_queue import complete_job, fail_job, payload_hash


def test_payload_hash_is_stable():
    assert payload_hash({"b": 1, "a": 2}) == payload_hash({"a": 2, "b": 1})


def test_fail_job_can_park_in_quota_wait():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.connection.driver_connection.create_function(
            "now",
            0,
            lambda: datetime.now(timezone.utc).isoformat(),
        )
        conn.execute(
            text(
                """
                create table job_queue (
                  id text primary key,
                  attempt_count int not null,
                  max_attempts int not null,
                  backoff_seconds int not null,
                  status text,
                  run_after timestamp,
                  locked_by text,
                  lease_expires_at timestamp,
                  last_error_class text,
                  last_error_message text,
                  updated_at timestamp
                )
                """
            )
        )
        conn.execute(
            text(
                """
                insert into job_queue(id, attempt_count, max_attempts, backoff_seconds, status)
                values ('job-1', 1, 5, 30, 'running')
                """
            )
        )
    with Session(engine) as db:
        fail_job(
            db,
            job_id="job-1",
            error_class="rate_limited",
            error_message="retry later",
            retry_after_seconds=90,
            status_override="quota_wait",
        )
        row = db.execute(text("select status, last_error_class from job_queue where id = 'job-1'")).one()

    assert row.status == "quota_wait"
    assert row.last_error_class == "rate_limited"


def test_fail_job_keeps_quota_wait_after_attempts_exhausted():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.connection.driver_connection.create_function(
            "now",
            0,
            lambda: datetime.now(timezone.utc).isoformat(),
        )
        conn.execute(
            text(
                """
                create table job_queue (
                  id text primary key,
                  attempt_count int not null,
                  max_attempts int not null,
                  backoff_seconds int not null,
                  status text,
                  run_after timestamp,
                  locked_by text,
                  lease_expires_at timestamp,
                  last_error_class text,
                  last_error_message text,
                  updated_at timestamp
                )
                """
            )
        )
        conn.execute(
            text(
                """
                insert into job_queue(id, attempt_count, max_attempts, backoff_seconds, status)
                values ('job-1', 5, 5, 30, 'running')
                """
            )
        )
    with Session(engine) as db:
        fail_job(
            db,
            job_id="job-1",
            error_class="quota_exhausted",
            error_message="free quota exhausted",
            retry_after_seconds=300,
            status_override="quota_wait",
        )
        row = db.execute(text("select status, last_error_class from job_queue where id = 'job-1'")).one()

    assert row.status == "quota_wait"
    assert row.last_error_class == "quota_exhausted"


def test_complete_job_clears_stale_error_state():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.connection.driver_connection.create_function(
            "now",
            0,
            lambda: datetime.now(timezone.utc).isoformat(),
        )
        conn.execute(
            text(
                """
                create table job_queue (
                  id text primary key,
                  status text,
                  result_hash text,
                  locked_by text,
                  locked_at timestamp,
                  lease_expires_at timestamp,
                  last_error_class text,
                  last_error_message text,
                  updated_at timestamp
                )
                """
            )
        )
        conn.execute(
            text(
                """
                insert into job_queue(
                  id, status, locked_by, locked_at, lease_expires_at,
                  last_error_class, last_error_message
                )
                values (
                  'job-1', 'running', 'worker-1', '2026-05-26T00:00:00Z',
                  '2026-05-26T00:02:00Z', 'PermissionError', 'old failure'
                )
                """
            )
        )
    with Session(engine) as db:
        complete_job(db, job_id="job-1", result={"ok": True})
        row = db.execute(
            text(
                """
                select status, result_hash, locked_by, locked_at, lease_expires_at,
                       last_error_class, last_error_message
                from job_queue
                where id = 'job-1'
                """
            )
        ).one()

    assert row.status == "succeeded"
    assert row.result_hash == payload_hash({"ok": True})
    assert row.locked_by is None
    assert row.locked_at is None
    assert row.lease_expires_at is None
    assert row.last_error_class is None
    assert row.last_error_message is None
