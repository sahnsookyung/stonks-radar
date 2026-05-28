"""news summary controls and queue safeguards

Revision ID: 20260529_0007
Revises: 20260528_0006
Create Date: 2026-05-29
"""

from __future__ import annotations

from alembic import op

revision = "20260529_0007"
down_revision = "20260528_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        create index if not exists job_queue_news_source_nonterminal_idx
          on job_queue(job_type, (payload->>'source_key'), status)
          where job_type = 'news.fetch_source'
            and status in ('queued','running','retry_wait','quota_wait');

        alter table source_fact add column if not exists dedupe_key text;

        update source_fact
        set dedupe_key = 'sha256:' || encode(
          digest(
            coalesce(source_evidence_id::text, 'legacy:' || id::text) || '|' ||
            fact_type || '|' ||
            predicate || '|' ||
            coalesce(object_json::text, '{}') || '|' ||
            coalesce(time_reference::text, ''),
            'sha256'
          ),
          'hex'
        )
        where dedupe_key is null;

        with duplicate_facts as (
          select id,
                 row_number() over (
                   partition by dedupe_key
                   order by public_allowed desc, created_at asc, id asc
                 ) as rn
          from source_fact
        )
        update source_fact f
        set dedupe_key = f.dedupe_key || ':' || 'dup:' || f.id::text
        from duplicate_facts d
        where f.id = d.id
          and d.rn > 1;

        alter table source_fact alter column dedupe_key set not null;
        create unique index if not exists source_fact_dedupe_key_unique
          on source_fact(dedupe_key);

        with duplicate_evidence as (
          select id,
                 row_number() over (
                   partition by source_document_id, evidence_hash
                   order by manually_confirmed desc, public_allowed desc, created_at asc, id asc
                 ) as rn
          from source_evidence
        )
        update source_evidence e
        set evidence_hash = e.evidence_hash || ':' || 'dup:' || e.id::text
        from duplicate_evidence d
        where e.id = d.id
          and d.rn > 1;

        create unique index if not exists source_evidence_document_hash_unique
          on source_evidence(source_document_id, evidence_hash);

        insert into fact_type_registry(
          fact_type, display_name_en, display_name_ko, json_schema,
          allowed_predicates, public_allowed_default, requires_review
        )
        values
        (
          'news_document_metadata',
          'News document metadata',
          '뉴스 문서 메타데이터',
          '{
            "type":"object",
            "required":["title","source_url","source_key","trust_tier"],
            "properties":{
              "title":{"type":"string"},
              "snippet":{"type":["string","null"]},
              "published_at":{"type":["string","null"]},
              "source_url":{"type":"string"},
              "source_key":{"type":"string"},
              "trust_tier":{"type":"string"}
            },
            "additionalProperties"\:false
          }'::jsonb,
          array['states'],
          false,
          true
        ),
        (
          'news_event_link',
          'News event link',
          '뉴스 이벤트 연결',
          '{
            "type":"object",
            "required":["event_id","document_id","relationship"],
            "properties":{
              "event_id":{"type":"string"},
              "document_id":{"type":"string"},
              "relationship":{"type":"string"},
              "confidence":{"type":"number"}
            },
            "additionalProperties"\:false
          }'::jsonb,
          array['supports'],
          false,
          true
        ),
        (
          'news_entity_mention',
          'News entity mention',
          '뉴스 엔티티 언급',
          '{
            "type":"object",
            "required":["entity_key","entity_type","relationship"],
            "properties":{
              "entity_key":{"type":"string"},
              "entity_type":{"type":"string"},
              "relationship":{"type":"string"},
              "confidence":{"type":"number"}
            },
            "additionalProperties"\:false
          }'::jsonb,
          array['mentions'],
          false,
          true
        ),
        (
          'news_market_relevance',
          'News market relevance',
          '뉴스 시장 관련성',
          '{
            "type":"object",
            "required":["direction","confidence","reasoning"],
            "properties":{
              "direction":{"type":"string"},
              "confidence":{"type":"string"},
              "reasoning":{"type":"string"}
            },
            "additionalProperties"\:false
          }'::jsonb,
          array['suggests'],
          false,
          true
        )
        on conflict (fact_type) do update
        set json_schema = excluded.json_schema,
            allowed_predicates = excluded.allowed_predicates,
            active = true;

        create table if not exists news_event_fact (
          event_id text not null references news_event_cluster(id) on delete cascade,
          fact_id uuid not null references source_fact(id) on delete cascade,
          document_id uuid references source_document(id) on delete set null,
          role text not null default 'supporting_fact',
          created_at timestamptz not null default now(),
          primary key (event_id, fact_id)
        );
        create index if not exists news_event_fact_fact_idx
          on news_event_fact(fact_id);

        create table if not exists news_event_summary (
          id uuid primary key default gen_random_uuid(),
          event_id text not null references news_event_cluster(id) on delete cascade,
          locale text not null,
          prompt_version text not null,
          input_hash text not null,
          summary_json jsonb not null default '{}'::jsonb,
          cited_fact_ids uuid[] not null default '{}',
          source_document_ids uuid[] not null default '{}',
          status text not null default 'candidate'
            check (status in ('candidate','succeeded','schema_failed','rejected','provider_failed','quota_failed','disabled')),
          review_state text not null default 'candidate'
            check (review_state in ('candidate','approved','reviewed','published','rejected')),
          public_allowed boolean not null default false,
          llm_invocation_id uuid references llm_invocation(id) on delete set null,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          unique(event_id, locale, prompt_version, input_hash)
        );
        create index if not exists news_event_summary_public_idx
          on news_event_summary(event_id, locale)
          where public_allowed = true
            and review_state in ('approved','reviewed','published')
            and status = 'succeeded';

        alter table llm_invocation alter column model_profile_id drop not null;
        alter table llm_invocation alter column provider_key drop not null;
        alter table llm_invocation add column if not exists actor_user_id uuid;
        alter table llm_invocation add column if not exists session_id text;
        alter table llm_invocation add column if not exists request_id text;
        alter table llm_invocation add column if not exists job_id uuid;
        alter table llm_invocation add column if not exists event_id text;
        alter table llm_invocation add column if not exists cache_key text;
        alter table llm_invocation add column if not exists denial_reason text;
        alter table llm_invocation add column if not exists usage_estimate_json jsonb not null default '{}'::jsonb;
        alter table llm_invocation add column if not exists reservation_id text;
        alter table llm_invocation drop constraint if exists llm_invocation_status_check;
        alter table llm_invocation add constraint llm_invocation_status_check
          check (status in (
            'succeeded','schema_failed','rejected','provider_failed','quota_failed','denied','budget_failed'
          ));

        create table if not exists llm_usage_counter (
          counter_key text not null,
          period_key text not null,
          used numeric not null default 0,
          hard_limit numeric,
          updated_at timestamptz not null default now(),
          primary key (counter_key, period_key)
        );

        insert into job_concurrency_limit(scope_type, scope_key, max_running)
        values
          ('provider', 'google_news_rss', 1),
          ('provider', 'yahoo_finance_rss', 1),
          ('provider', 'company_ir', 1),
          ('provider', 'sec_edgar', 2),
          ('job_group', 'news', 2)
        on conflict (scope_type, scope_key)
        do update set max_running = excluded.max_running, enabled = true;

        update source_policy_decision sp
        set llm_allowed_classes = array['PUBLIC_FACTS_ONLY']
        from data_source ds
        where ds.id = sp.source_id
          and sp.active = true
          and (
            ds.source_type in ('rss','news_metadata','aggregator')
            or ds.raw_retention_policy = 'metadata_only'
          );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        delete from job_concurrency_limit
        where (scope_type, scope_key) in (
          ('provider', 'google_news_rss'),
          ('provider', 'yahoo_finance_rss'),
          ('provider', 'company_ir'),
          ('provider', 'sec_edgar')
        );

        drop table if exists llm_usage_counter;

        alter table llm_invocation drop constraint if exists llm_invocation_status_check;
        alter table llm_invocation add constraint llm_invocation_status_check
          check (status in ('succeeded','schema_failed','rejected','provider_failed','quota_failed'));
        alter table llm_invocation drop column if exists reservation_id;
        alter table llm_invocation drop column if exists usage_estimate_json;
        alter table llm_invocation drop column if exists denial_reason;
        alter table llm_invocation drop column if exists cache_key;
        alter table llm_invocation drop column if exists event_id;
        alter table llm_invocation drop column if exists job_id;
        alter table llm_invocation drop column if exists request_id;
        alter table llm_invocation drop column if exists session_id;
        alter table llm_invocation drop column if exists actor_user_id;
        alter table llm_invocation alter column provider_key set not null;
        alter table llm_invocation alter column model_profile_id set not null;

        drop table if exists news_event_summary;
        drop index if exists news_event_fact_fact_idx;
        drop table if exists news_event_fact;

        delete from fact_type_registry
        where fact_type in (
          'news_document_metadata',
          'news_event_link',
          'news_entity_mention',
          'news_market_relevance'
        );

        drop index if exists source_evidence_document_hash_unique;
        drop index if exists source_fact_dedupe_key_unique;
        alter table source_fact drop column if exists dedupe_key;
        drop index if exists job_queue_news_source_nonterminal_idx;
        """
    )
