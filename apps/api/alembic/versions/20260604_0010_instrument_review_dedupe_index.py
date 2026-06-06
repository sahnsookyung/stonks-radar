"""instrument review request dedupe index

Revision ID: 20260604_0010
Revises: 20260531_0009
Create Date: 2026-06-04
"""

from __future__ import annotations

from alembic import op

revision = "20260604_0010"
down_revision = "20260531_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create index if not exists instrument_review_request_pending_dedupe_idx
          on instrument_review_request(request_ip_hash, lower(query), context_screen, created_at desc)
          where status in ('queued', 'in_review');
        """
    )


def downgrade() -> None:
    op.execute("drop index if exists instrument_review_request_pending_dedupe_idx;")
