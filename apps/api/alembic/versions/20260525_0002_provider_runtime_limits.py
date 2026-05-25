"""provider runtime limits

Revision ID: 20260525_0002
Revises: 20260524_0001
Create Date: 2026-05-25
"""

from __future__ import annotations

from alembic import op

revision = "20260525_0002"
down_revision = "20260524_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table provider_usage_event add column if not exists endpoint_key text;
        alter table provider_usage_event add column if not exists partition_key text;
        alter table provider_usage_event add column if not exists status text not null default 'succeeded';
        alter table provider_usage_event add column if not exists error_class text;
        alter table provider_usage_event add column if not exists idempotency_key text;
        alter table provider_usage_event add column if not exists reserved_units jsonb not null default '{}'::jsonb;
        alter table provider_usage_event add column if not exists actual_units jsonb not null default '{}'::jsonb;
        alter table provider_usage_event add column if not exists retry_after_seconds int;
        alter table provider_usage_event add column if not exists next_allowed_at timestamptz;
        alter table provider_usage_event add column if not exists details jsonb not null default '{}'::jsonb;

        create index if not exists provider_usage_event_provider_endpoint_idx
          on provider_usage_event(provider_key, endpoint_key, created_at desc);

        create table if not exists provider_runtime_state (
          provider_key text not null,
          endpoint_key text not null,
          partition_key text not null default 'scheduled_public',
          circuit_state text not null default 'closed' check (circuit_state in ('closed','open')),
          opened_at timestamptz,
          next_allowed_at timestamptz,
          last_success_at timestamptz,
          last_failure_at timestamptz,
          last_error_class text,
          last_status_code int,
          failure_count int not null default 0,
          credential_version text,
          details jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          primary key (provider_key, endpoint_key, partition_key)
        );

        create index if not exists provider_runtime_state_open_idx
          on provider_runtime_state(next_allowed_at)
          where circuit_state = 'open';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop index if exists provider_runtime_state_open_idx;
        drop table if exists provider_runtime_state;
        drop index if exists provider_usage_event_provider_endpoint_idx;
        alter table provider_usage_event drop column if exists details;
        alter table provider_usage_event drop column if exists next_allowed_at;
        alter table provider_usage_event drop column if exists retry_after_seconds;
        alter table provider_usage_event drop column if exists actual_units;
        alter table provider_usage_event drop column if exists reserved_units;
        alter table provider_usage_event drop column if exists idempotency_key;
        alter table provider_usage_event drop column if exists error_class;
        alter table provider_usage_event drop column if exists status;
        alter table provider_usage_event drop column if exists partition_key;
        alter table provider_usage_event drop column if exists endpoint_key;
        """
    )
