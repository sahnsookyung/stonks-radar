from __future__ import annotations

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
) -> None:
    db.execute(
        text(
            """
            insert into provider_usage_event(provider_key, unit, quantity, estimated_cost_usd, job_id)
            values (:provider_key, :unit, :quantity, :estimated_cost_usd, :job_id)
            """
        ),
        {
            "provider_key": provider_key,
            "unit": unit,
            "quantity": quantity,
            "estimated_cost_usd": estimated_cost_usd,
            "job_id": job_id,
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
