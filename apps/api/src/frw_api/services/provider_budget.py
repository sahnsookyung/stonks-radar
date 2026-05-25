from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.core.settings import get_settings


def provider_is_available(db: Session, provider_key: str) -> bool:
    row = (
        db.execute(
            text(
                """
                select routing_mode, billing_mode, paid_allowed, kill_switch_enabled,
                       current_period_usage, hard_limit
                from provider_budget
                where provider_key = :provider_key
                """
            ),
            {"provider_key": provider_key},
        )
        .mappings()
        .first()
    )
    if not row:
        return False
    settings = get_settings()
    mode = row["routing_mode"]
    if row["kill_switch_enabled"] or mode == "OFF":
        return False
    if row["hard_limit"] is not None and row["current_period_usage"] >= row["hard_limit"]:
        return False
    if mode == "LOCAL_ONLY":
        return provider_key == "local"
    if mode == "PAID_DISABLED":
        return False
    if mode == "FREE_ONLY":
        return row["billing_mode"] in ("always_free", "free_quota", "unknown") and not row["paid_allowed"]
    if mode == "PAID_ALLOWED_WITH_CAP":
        return settings.paid_usage_allowed and bool(row["paid_allowed"]) and row["hard_limit"] is not None
    return True


def record_usage(
    db: Session,
    *,
    provider_key: str,
    unit: str,
    quantity: float,
    estimated_cost_usd: float = 0,
    job_id: str | None = None,
    endpoint_key: str | None = None,
    partition_key: str | None = None,
    status: str = "succeeded",
    error_class: str | None = None,
    idempotency_key: str | None = None,
    reserved_units: dict[str, float] | None = None,
    actual_units: dict[str, float] | None = None,
    retry_after_seconds: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.execute(
        text(
            """
            insert into provider_usage_event(
              provider_key, endpoint_key, partition_key, status, error_class, idempotency_key,
              unit, quantity, estimated_cost_usd, job_id, reserved_units, actual_units,
              retry_after_seconds, details
            )
            values (
              :provider_key, :endpoint_key, :partition_key, :status, :error_class, :idempotency_key,
              :unit, :quantity, :estimated_cost_usd, :job_id, cast(:reserved_units as jsonb),
              cast(:actual_units as jsonb), :retry_after_seconds, cast(:details as jsonb)
            )
            """
        ),
        {
            "provider_key": provider_key,
            "endpoint_key": endpoint_key,
            "partition_key": partition_key,
            "status": status,
            "error_class": error_class,
            "idempotency_key": idempotency_key,
            "unit": unit,
            "quantity": quantity,
            "estimated_cost_usd": estimated_cost_usd,
            "job_id": job_id,
            "reserved_units": json.dumps(reserved_units or {}),
            "actual_units": json.dumps(actual_units or {}),
            "retry_after_seconds": retry_after_seconds,
            "details": json.dumps(details or {}),
        },
    )
    db.execute(
        text(
            """
            update provider_budget
            set current_period_usage = current_period_usage + :quantity,
                estimated_cost_usd_current_period = estimated_cost_usd_current_period + :estimated_cost_usd,
                last_usage_sync_at = now(),
                hard_stop_triggered_at = case
                  when hard_limit is not null and current_period_usage + :quantity >= hard_limit then now()
                  else hard_stop_triggered_at
                end
            where provider_key = :provider_key
            """
        ),
        {
            "provider_key": provider_key,
            "quantity": quantity,
            "estimated_cost_usd": estimated_cost_usd,
        },
    )


def set_kill_switch(db: Session, *, budget_id: str, enabled: bool) -> None:
    db.execute(
        text(
            """
            update provider_budget
            set kill_switch_enabled = :enabled,
                hard_stop_triggered_at = case when :enabled then now() else hard_stop_triggered_at end
            where id = :budget_id
            """
        ),
        {"budget_id": budget_id, "enabled": enabled},
    )
