"""news email alerts and source dedupe

Revision ID: 20260528_0006
Revises: 20260528_0005
Create Date: 2026-05-28
"""

from __future__ import annotations

from alembic import op

revision = "20260528_0006"
down_revision = "20260528_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table source_health_status
          drop constraint if exists source_health_status_status_check;
        alter table source_health_status
          add constraint source_health_status_status_check
          check (status in ('ready','degraded','unsupported','failed','disabled','denied','quarantined'));

        alter table data_source
          drop constraint if exists data_source_source_type_check;
        alter table data_source
          add constraint data_source_source_type_check
          check (source_type in (
            'official_api','official_page','company_ir','company_email','filing','rss','news_metadata',
            'public_web','manual','user_clip','aggregator','market_data','llm_provider'
          ));

        alter table source_document
          add column if not exists dedupe_key text,
          add column if not exists raw_expires_at timestamptz,
          add column if not exists updated_at timestamptz not null default now();

        create unique index if not exists source_document_dedupe_key_unique
          on source_document(dedupe_key)
          where dedupe_key is not null;

        create table if not exists news_email_alert (
          id uuid primary key default gen_random_uuid(),
          source_document_id uuid references source_document(id) on delete set null,
          recipient text not null,
          sender text not null,
          envelope_from text,
          subject text,
          message_id text,
          received_at timestamptz not null,
          raw_hash text not null,
          raw_object_key text,
          raw_size integer not null check (raw_size >= 0),
          raw_expires_at timestamptz not null,
          auth_results jsonb not null default '{}'::jsonb,
          links jsonb not null default '[]'::jsonb,
          status text not null check (status in ('accepted','duplicate','rejected','quarantined','dead_letter','raw_purged')),
          rejection_reason text,
          metadata jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );

        create unique index if not exists news_email_alert_raw_hash_unique
          on news_email_alert(raw_hash);
        create unique index if not exists news_email_alert_message_id_unique
          on news_email_alert(message_id)
          where message_id is not null and message_id <> '';
        create index if not exists news_email_alert_recipient_received_idx
          on news_email_alert(recipient, received_at desc);
        create index if not exists news_email_alert_raw_expires_idx
          on news_email_alert(raw_expires_at)
          where raw_object_key is not null;

        create table if not exists news_email_webhook_nonce (
          nonce text primary key,
          received_at timestamptz not null default now()
        );
        create index if not exists news_email_webhook_nonce_received_idx
          on news_email_webhook_nonce(received_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists news_email_webhook_nonce;
        drop table if exists news_email_alert;

        drop index if exists source_document_dedupe_key_unique;
        alter table source_document
          drop column if exists raw_expires_at,
          drop column if exists updated_at,
          drop column if exists dedupe_key;

        alter table data_source
          drop constraint if exists data_source_source_type_check;
        alter table data_source
          add constraint data_source_source_type_check
          check (source_type in (
            'official_api','official_page','company_ir','filing','rss','news_metadata',
            'public_web','manual','user_clip','aggregator','market_data','llm_provider'
          ));

        alter table source_health_status
          drop constraint if exists source_health_status_status_check;
        alter table source_health_status
          add constraint source_health_status_status_check
          check (status in ('ready','degraded','unsupported','failed'));
        """
    )
