from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def payload_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def enqueue_job(
    db: Session,
    *,
    job_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
    job_group: str = "default",
    priority: int = 100,
    provider_key: str | None = None,
    source_id: str | None = None,
    depends_on_job_id: str | None = None,
) -> str:
    row = db.execute(
        text(
            """
            insert into job_queue(
              job_type, job_group, priority, idempotency_key, payload, payload_hash,
              provider_key, source_id, depends_on_job_id
            )
            values (
              :job_type, :job_group, :priority, :idempotency_key, cast(:payload as jsonb), :payload_hash,
              :provider_key, :source_id, :depends_on_job_id
            )
            on conflict (job_type, idempotency_scope, idempotency_key)
            do update set updated_at = now()
            returning id
            """
        ),
        {
            "job_type": job_type,
            "job_group": job_group,
            "priority": priority,
            "idempotency_key": idempotency_key,
            "payload": json.dumps(payload),
            "payload_hash": payload_hash(payload),
            "provider_key": provider_key,
            "source_id": source_id,
            "depends_on_job_id": depends_on_job_id,
        },
    ).scalar_one()
    return str(row)


def claim_job(db: Session, *, worker_id: str, lease_seconds: int = 120) -> dict[str, Any] | None:
    lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
    row = (
        db.execute(
            text(
                """
                with candidate as (
                  select j.id
                  from job_queue j
                  left join job_queue dep on dep.id = j.depends_on_job_id
                  where j.status in ('queued','retry_wait','quota_wait')
                    and j.run_after <= now()
                    and (j.depends_on_job_id is null or dep.status = 'succeeded')
                    and not exists (
                      select 1
                      from job_concurrency_limit lim
                      where lim.enabled = true
                        and (
                          (lim.scope_type = 'global' and lim.scope_key = 'global')
                          or (lim.scope_type = 'job_type' and lim.scope_key = j.job_type)
                          or (lim.scope_type = 'provider' and lim.scope_key = coalesce(j.provider_key, ''))
                          or (lim.scope_type = 'source' and lim.scope_key = coalesce(j.source_id::text, ''))
                        )
                        and (
                          select count(*)
                          from job_queue running
                          where running.status = 'running'
                            and (
                              (lim.scope_type = 'global')
                              or (lim.scope_type = 'job_type' and running.job_type = j.job_type)
                              or (lim.scope_type = 'provider' and running.provider_key = j.provider_key)
                              or (lim.scope_type = 'source' and running.source_id = j.source_id)
                            )
                        ) >= lim.max_running
                    )
                  order by j.priority asc, j.created_at asc
                  for update of j skip locked
                  limit 1
                )
                update job_queue j
                set status = 'running',
                    locked_by = :worker_id,
                    locked_at = now(),
                    lease_expires_at = :lease_expires_at,
                    heartbeat_at = now(),
                    attempt_count = attempt_count + 1,
                    updated_at = now()
                from candidate
                where j.id = candidate.id
                returning j.*
                """
            ),
            {"worker_id": worker_id, "lease_expires_at": lease_expires_at},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def heartbeat(db: Session, *, job_id: str, worker_id: str, lease_seconds: int = 120) -> None:
    db.execute(
        text(
            """
            update job_queue
            set heartbeat_at = now(), lease_expires_at = :lease_expires_at, updated_at = now()
            where id = :job_id and locked_by = :worker_id and status = 'running'
            """
        ),
        {
            "job_id": job_id,
            "worker_id": worker_id,
            "lease_expires_at": datetime.now(timezone.utc) + timedelta(seconds=lease_seconds),
        },
    )


def complete_job(db: Session, *, job_id: str, result: dict[str, Any] | None = None) -> None:
    result_h = payload_hash(result or {})
    db.execute(
        text(
            """
            update job_queue
            set status = 'succeeded',
                result_hash = :result_hash,
                locked_by = null,
                locked_at = null,
                lease_expires_at = null,
                last_error_class = null,
                last_error_message = null,
                updated_at = now()
            where id = :job_id
            """
        ),
        {"job_id": job_id, "result_hash": result_h},
    )


def fail_job(
    db: Session,
    *,
    job_id: str,
    error_class: str,
    error_message: str,
    retryable: bool = True,
    retry_after_seconds: int | None = None,
    status_override: str | None = None,
) -> None:
    row = db.execute(
        text("select attempt_count, max_attempts, backoff_seconds from job_queue where id = :job_id"),
        {"job_id": job_id},
    ).mappings().one()
    exhausted = row["attempt_count"] >= row["max_attempts"]
    if retryable and not exhausted:
        if retry_after_seconds is not None:
            status = status_override or "retry_wait"
            run_after = datetime.now(timezone.utc) + timedelta(seconds=max(1, retry_after_seconds))
        else:
            jitter = random.randint(0, max(1, row["backoff_seconds"]))
            status = status_override or "retry_wait"
            run_after = datetime.now(timezone.utc) + timedelta(seconds=row["backoff_seconds"] * 2 + jitter)
    else:
        status = "dead_letter" if exhausted else "failed_permanent"
        run_after = datetime.now(timezone.utc)
    db.execute(
        text(
            """
            update job_queue
            set status = :status,
                run_after = :run_after,
                locked_by = null,
                lease_expires_at = null,
                last_error_class = :error_class,
                last_error_message = :error_message,
                updated_at = now()
            where id = :job_id
            """
        ),
        {
            "status": status,
            "run_after": run_after,
            "error_class": error_class,
            "error_message": error_message[:2000],
            "job_id": job_id,
        },
    )


def reap_expired_leases(db: Session) -> int:
    result = db.execute(
        text(
            """
            update job_queue
            set status = 'retry_wait',
                locked_by = null,
                lease_expires_at = null,
                last_error_class = 'LeaseExpired',
                last_error_message = 'Worker lease expired and was reset by reaper',
                updated_at = now()
            where status = 'running'
              and lease_expires_at is not null
              and lease_expires_at < now()
            """
        )
    )
    return int(result.rowcount or 0)


def replay_dead_letter(db: Session, *, job_id: str) -> None:
    db.execute(
        text(
            """
            update job_queue
            set status = 'queued',
                run_after = now(),
                locked_by = null,
                lease_expires_at = null,
                last_error_class = null,
                last_error_message = null,
                updated_at = now()
            where id = :job_id and status = 'dead_letter'
            """
        ),
        {"job_id": job_id},
    )
