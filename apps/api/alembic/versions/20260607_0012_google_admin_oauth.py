"""google admin oauth

Revision ID: 20260607_0012
Revises: 20260607_0011
Create Date: 2026-06-07
"""

from __future__ import annotations

from alembic import op

revision = "20260607_0012"
down_revision = "20260607_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table app_user
          add column if not exists auth_provider text not null default 'password',
          add column if not exists external_subject text,
          add column if not exists last_login_at timestamptz,
          add column if not exists auth_metadata jsonb not null default '{}'::jsonb;

        create unique index if not exists app_user_auth_provider_subject_idx
          on app_user(auth_provider, external_subject)
          where external_subject is not null;

        create table if not exists oauth_login_state (
          state_hash text primary key,
          nonce_hash text not null,
          provider text not null,
          redirect_to text,
          created_at timestamptz not null default now(),
          expires_at timestamptz not null,
          used_at timestamptz
        );

        create index if not exists oauth_login_state_expiry_idx
          on oauth_login_state(provider, expires_at)
          where used_at is null;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop index if exists oauth_login_state_expiry_idx;
        drop table if exists oauth_login_state;

        drop index if exists app_user_auth_provider_subject_idx;
        alter table app_user
          drop column if exists auth_metadata,
          drop column if exists last_login_at,
          drop column if exists external_subject,
          drop column if exists auth_provider;
        """
    )
