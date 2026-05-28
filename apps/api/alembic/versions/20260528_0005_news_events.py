"""news event intelligence tables

Revision ID: 20260528_0005
Revises: 20260526_0004
Create Date: 2026-05-28
"""

from __future__ import annotations

from alembic import op

revision = "20260528_0005"
down_revision = "20260526_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table if not exists news_event_cluster (
          id text primary key,
          canonical_title text not null,
          event_type text not null,
          first_seen_at timestamptz not null,
          last_seen_at timestamptz not null,
          published_at timestamptz,
          primary_region text,
          severity text not null,
          confidence numeric not null check (confidence >= 0 and confidence <= 1),
          breaking_score integer not null check (breaking_score >= 0 and breaking_score <= 100),
          trust_score integer not null check (trust_score >= 0 and trust_score <= 100),
          novelty_score integer not null check (novelty_score >= 0 and novelty_score <= 100),
          source_count integer not null default 0,
          review_state text not null default 'candidate',
          status text not null default 'active',
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );

        create index if not exists news_event_cluster_last_seen_idx
          on news_event_cluster(last_seen_at desc);
        create index if not exists news_event_cluster_review_status_idx
          on news_event_cluster(review_state, status);

        create table if not exists news_event_document (
          event_id text not null references news_event_cluster(id) on delete cascade,
          document_id uuid not null references source_document(id) on delete cascade,
          relationship text not null,
          confidence numeric not null check (confidence >= 0 and confidence <= 1),
          is_primary_source boolean not null default false,
          created_at timestamptz not null default now(),
          primary key (event_id, document_id)
        );

        create table if not exists news_event_entity (
          event_id text not null references news_event_cluster(id) on delete cascade,
          entity_key text not null,
          entity_type text not null,
          relationship text not null,
          confidence numeric not null check (confidence >= 0 and confidence <= 1),
          evidence_id uuid references source_evidence(id) on delete set null,
          created_at timestamptz not null default now(),
          primary key (event_id, entity_key, relationship)
        );

        create index if not exists news_event_entity_entity_idx
          on news_event_entity(entity_key, entity_type);

        create table if not exists news_event_region (
          event_id text not null references news_event_cluster(id) on delete cascade,
          region_key text not null,
          relation text not null check (relation in (
            'source_region',
            'event_region',
            'company_region',
            'affected_region',
            'market_region',
            'mentioned_region'
          )),
          confidence numeric not null check (confidence >= 0 and confidence <= 1),
          created_at timestamptz not null default now(),
          primary key (event_id, region_key, relation)
        );

        create index if not exists news_event_region_region_idx
          on news_event_region(region_key, relation);

        create table if not exists news_event_topic (
          event_id text not null references news_event_cluster(id) on delete cascade,
          topic_key text not null,
          confidence numeric not null check (confidence >= 0 and confidence <= 1),
          created_at timestamptz not null default now(),
          primary key (event_id, topic_key)
        );

        create index if not exists news_event_topic_topic_idx
          on news_event_topic(topic_key);

        alter table job_concurrency_limit
          drop constraint if exists job_concurrency_limit_scope_type_check;
        alter table job_concurrency_limit
          add constraint job_concurrency_limit_scope_type_check
          check (scope_type in ('job_type','job_group','source','provider','global'));

        insert into job_concurrency_limit(scope_type, scope_key, max_running)
        values ('job_group', 'news', 2)
        on conflict (scope_type, scope_key)
        do update set max_running = excluded.max_running, enabled = true;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        delete from job_concurrency_limit
        where scope_type = 'job_group' and scope_key = 'news';

        alter table job_concurrency_limit
          drop constraint if exists job_concurrency_limit_scope_type_check;
        alter table job_concurrency_limit
          add constraint job_concurrency_limit_scope_type_check
          check (scope_type in ('job_type','source','provider','global'));

        drop table if exists news_event_topic;
        drop table if exists news_event_region;
        drop table if exists news_event_entity;
        drop table if exists news_event_document;
        drop table if exists news_event_cluster;
        """
    )
