"""instrument autocomplete review queue

Revision ID: 20260531_0008
Revises: 20260529_0007
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op

revision = "20260531_0008"
down_revision = "20260529_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table if not exists instrument_review_request (
          id uuid primary key default gen_random_uuid(),
          user_id uuid references app_user(id) on delete set null,
          query text not null check (char_length(query) between 1 and 64),
          context_screen text not null check (context_screen in (
            'HOLDING_ENTRY','TAX_LOT','BUILDER','IMPORT_RECONCILIATION','CSV_IMPORT'
          )),
          optional_notes text,
          request_ip_hash text,
          status text not null default 'queued' check (status in (
            'queued','in_review','resolved','closed','rejected'
          )),
          admin_notes text,
          resolved_by uuid references app_user(id) on delete set null,
          resolved_at timestamptz,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );

        create index if not exists instrument_review_request_status_idx
          on instrument_review_request(status, created_at desc);

        create index if not exists instrument_review_request_query_idx
          on instrument_review_request(lower(query));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop index if exists instrument_review_request_query_idx;
        drop index if exists instrument_review_request_status_idx;
        drop table if exists instrument_review_request;
        """
    )
