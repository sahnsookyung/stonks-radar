from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def upsert_operation_status(
    db: Session,
    *,
    key: str,
    value: str,
    severity: str = "info",
    details: dict[str, Any] | None = None,
) -> None:
    db.execute(
        text(
            """
            insert into operation_status(status_key, status_value, severity, details, updated_at)
            values (:key, :value, :severity, cast(:details as jsonb), now())
            on conflict (status_key) do update
            set status_value = excluded.status_value,
                severity = excluded.severity,
                details = excluded.details,
                updated_at = now()
            """
        ),
        {"key": key, "value": value, "severity": severity, "details": json.dumps(details or {})},
    )


def get_operation_status_map(db: Session) -> dict[str, dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select status_key, status_value, severity, details, updated_at
            from operation_status
            """
        )
    ).mappings().all()
    return {row["status_key"]: dict(row) for row in rows}


def upsert_source_health(
    db: Session,
    *,
    source_key: str,
    status: str,
    status_code: str | None = None,
    response_ms: int | None = None,
    error: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.execute(
        text(
            """
            insert into source_health_status(
              source_key, status, status_code, response_ms, last_checked_at,
              last_success_at, last_error, details
            )
            values (
              :source_key, :status, :status_code, :response_ms, now(),
              case when :status = 'ready' then now() else null end,
              :error, cast(:details as jsonb)
            )
            on conflict (source_key) do update
            set status = excluded.status,
                status_code = excluded.status_code,
                response_ms = excluded.response_ms,
                last_checked_at = now(),
                last_success_at = case when excluded.status = 'ready' then now() else source_health_status.last_success_at end,
                last_error = excluded.last_error,
                details = excluded.details
            """
        ),
        {
            "source_key": source_key,
            "status": status,
            "status_code": status_code,
            "response_ms": response_ms,
            "error": error,
            "details": json.dumps(details or {}),
        },
    )
