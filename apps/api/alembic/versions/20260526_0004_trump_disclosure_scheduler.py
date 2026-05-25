"""Add Trump disclosure scheduler concurrency limit.

Revision ID: 20260526_0004
Revises: 20260526_0003
Create Date: 2026-05-26
"""

from __future__ import annotations

from alembic import op

revision = "20260526_0004"
down_revision = "20260526_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        insert into job_concurrency_limit(scope_type, scope_key, max_running)
        values ('job_type', 'trump_disclosures_ingest', 1)
        on conflict (scope_type, scope_key)
        do update set max_running = excluded.max_running, enabled = true
        """
    )


def downgrade() -> None:
    op.execute(
        """
        delete from job_concurrency_limit
        where scope_type = 'job_type' and scope_key = 'trump_disclosures_ingest'
        """
    )
