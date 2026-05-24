"""initial v8 schema

Revision ID: 20260524_0001
Revises:
Create Date: 2026-05-24
"""

from __future__ import annotations

from alembic import op

revision = "20260524_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create extension if not exists pgcrypto;

        create table app_user (
          id uuid primary key default gen_random_uuid(),
          email text not null unique,
          password_hash text not null,
          role text not null check (role in ('owner','admin','editor','viewer')),
          active boolean not null default true,
          totp_required boolean not null default true,
          recovery_codes_hash text[] not null default '{}',
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );

        create table user_totp_secret (
          user_id uuid primary key references app_user(id) on delete cascade,
          secret_ciphertext text not null,
          verified_at timestamptz,
          created_at timestamptz not null default now()
        );

        create table app_session (
          id uuid primary key default gen_random_uuid(),
          user_id uuid not null references app_user(id) on delete cascade,
          session_hash text not null unique,
          csrf_hash text not null,
          role text not null,
          expires_at timestamptz not null,
          rotated_at timestamptz not null default now(),
          ip_hash text,
          user_agent_hash text,
          created_at timestamptz not null default now()
        );

        create table canonical_object (
          id uuid primary key default gen_random_uuid(),
          object_type text not null check (object_type in (
            'country_region','sector','entity','instrument','series','economic_release',
            'geo_event','event_cluster','scenario_basket','source_document','source_fact',
            'content_summary','source_policy','provider'
          )),
          object_key text not null,
          display_name_en text not null,
          display_name_ko text,
          active boolean not null default true,
          created_at timestamptz not null default now(),
          unique(object_type, object_key)
        );

        create table country_region (
          canonical_object_id uuid primary key references canonical_object(id),
          region_kind text not null check (region_kind in ('country','region','dynamic_group')),
          iso_alpha2 text,
          iso_alpha3 text,
          methodology_key text,
          methodology_year int,
          source_key text,
          display_order int not null default 100
        );

        create table country_region_membership (
          id uuid primary key default gen_random_uuid(),
          region_object_id uuid not null references canonical_object(id),
          member_object_id uuid not null references canonical_object(id),
          membership_version text not null,
          valid_from date not null,
          valid_to date,
          source_key text,
          unique(region_object_id, member_object_id, membership_version)
        );

        create table sector (
          canonical_object_id uuid primary key references canonical_object(id),
          sector_key text not null unique,
          public_enabled boolean not null default true,
          display_order int not null default 100
        );

        create table entity (
          canonical_object_id uuid primary key references canonical_object(id),
          entity_key text not null unique,
          entity_type text not null default 'company',
          domicile_object_id uuid references canonical_object(id),
          private_reference boolean not null default false
        );

        create table instrument (
          canonical_object_id uuid primary key references canonical_object(id),
          instrument_key text not null unique,
          entity_object_id uuid references canonical_object(id),
          ticker text,
          exchange text,
          currency_code text,
          active_from date,
          active_to date,
          market_data_policy text not null default 'delayed_reference_only'
        );

        create table data_source (
          id uuid primary key default gen_random_uuid(),
          source_key text not null unique,
          display_name text not null,
          source_type text not null check (source_type in (
            'official_api','official_page','company_ir','filing','rss','news_metadata',
            'public_web','manual','user_clip','aggregator','market_data','llm_provider'
          )),
          base_url text,
          public_display_policy text not null default 'facts_with_attribution',
          raw_retention_policy text not null default 'metadata_only',
          redistribution_risk text not null default 'unknown',
          rate_limit_per_minute int,
          rate_limit_per_day int,
          robots_policy text not null default 'respect',
          enabled boolean not null default true,
          last_policy_review_at timestamptz,
          notes text,
          created_at timestamptz not null default now()
        );

        create table provider_budget (
          id uuid primary key default gen_random_uuid(),
          provider_key text not null unique,
          provider_type text not null,
          billing_mode text not null check (billing_mode in (
            'always_free','free_quota','trial_credit','paid_disabled','paid_enabled','unknown'
          )),
          routing_mode text not null default 'FREE_ONLY' check (routing_mode in (
            'OFF','FREE_ONLY','PAID_DISABLED','PAID_ALLOWED_WITH_CAP','LOCAL_ONLY'
          )),
          free_quota_unit text,
          free_quota_limit numeric,
          soft_limit numeric,
          hard_limit numeric,
          current_period_usage numeric not null default 0,
          period_started_at timestamptz,
          period_ends_at timestamptz,
          usage_reset_policy text not null default 'monthly',
          last_usage_sync_at timestamptz,
          estimated_cost_usd_current_period numeric not null default 0,
          warning_sent_at timestamptz,
          hard_stop_triggered_at timestamptz,
          paid_allowed boolean not null default false,
          kill_switch_enabled boolean not null default false,
          degrade_mode text not null default 'disable_noncritical_jobs',
          last_verified_at timestamptz,
          notes text,
          created_at timestamptz not null default now()
        );

        create table provider_usage_event (
          id uuid primary key default gen_random_uuid(),
          provider_key text not null,
          unit text not null,
          quantity numeric not null,
          estimated_cost_usd numeric not null default 0,
          job_id uuid,
          created_at timestamptz not null default now()
        );

        create table source_health_status (
          source_key text primary key,
          status text not null check (status in ('ready','degraded','unsupported','failed')),
          status_code text,
          response_ms int,
          last_checked_at timestamptz not null default now(),
          last_success_at timestamptz,
          last_error text,
          details jsonb not null default '{}'::jsonb
        );

        create table source_policy_decision (
          id uuid primary key default gen_random_uuid(),
          source_id uuid not null references data_source(id),
          policy_version int not null,
          allowed_acquisition_modes text[] not null,
          allowed_retention_classes text[] not null,
          public_display_policy text not null,
          llm_allowed_classes text[] not null default '{}',
          redistribution_notes text,
          reviewed_by uuid references app_user(id),
          reviewed_at timestamptz not null default now(),
          active boolean not null default true,
          unique(source_id, policy_version)
        );

        create table job_queue (
          id uuid primary key default gen_random_uuid(),
          job_type text not null,
          job_group text not null default 'default',
          priority int not null default 100,
          status text not null check (status in (
            'queued','running','succeeded','retry_wait','quota_wait',
            'failed_permanent','dead_letter','cancelled'
          )) default 'queued',
          idempotency_scope text not null default 'global',
          idempotency_key text not null,
          payload jsonb not null,
          payload_hash text not null,
          result_hash text,
          depends_on_job_id uuid references job_queue(id),
          run_after timestamptz not null default now(),
          locked_by text,
          locked_at timestamptz,
          lease_expires_at timestamptz,
          heartbeat_at timestamptz,
          attempt_count int not null default 0,
          max_attempts int not null default 5,
          backoff_seconds int not null default 30,
          last_error_class text,
          last_error_message text,
          source_id uuid references data_source(id),
          provider_key text,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          unique(job_type, idempotency_scope, idempotency_key)
        );

        create index job_queue_claim_idx
          on job_queue(status, run_after, priority, created_at)
          where status in ('queued','retry_wait','quota_wait');

        create index job_queue_lease_idx
          on job_queue(status, lease_expires_at)
          where status = 'running';

        create table job_concurrency_limit (
          id uuid primary key default gen_random_uuid(),
          scope_type text not null check (scope_type in ('job_type','source','provider','global')),
          scope_key text not null,
          max_running int not null,
          enabled boolean not null default true,
          unique(scope_type, scope_key)
        );

        create table series (
          id uuid primary key default gen_random_uuid(),
          canonical_object_id uuid not null references canonical_object(id),
          series_key text not null unique,
          display_name_en text not null,
          display_name_ko text,
          subject_object_id uuid not null references canonical_object(id),
          frequency text not null,
          units text not null,
          currency_code text,
          value_kind text not null default 'level',
          seasonal_adjustment text,
          annualization text,
          timezone text not null default 'UTC',
          market_calendar_key text,
          latency_tier text not null,
          stale_after_seconds int not null,
          revision_policy text not null default 'not_revised',
          source_priority jsonb not null default '[]'::jsonb,
          methodology_key text,
          active boolean not null default true,
          created_at timestamptz not null default now()
        );

        create table observation_candidate (
          id uuid default gen_random_uuid(),
          series_id uuid not null references series(id),
          source_id uuid not null references data_source(id),
          provider_observation_key text,
          observation_timestamp timestamptz not null,
          period_start timestamptz,
          period_end timestamptz,
          publication_timestamp timestamptz,
          source_timestamp timestamptz,
          ingest_timestamp timestamptz not null default now(),
          value_json jsonb not null,
          value_schema_key text not null,
          quality_flags text[] not null default '{}',
          delay_classification text not null default 'unknown',
          parse_confidence numeric,
          idempotency_key text not null,
          payload_hash text not null,
          primary key (id, observation_timestamp),
          unique(series_id, source_id, observation_timestamp, idempotency_key)
        ) partition by range (observation_timestamp);

        create table observation_candidate_default partition of observation_candidate default;
        create index observation_candidate_default_series_ts_idx
          on observation_candidate_default(series_id, observation_timestamp desc);
        create index observation_candidate_default_source_ingest_idx
          on observation_candidate_default(source_id, ingest_timestamp desc);

        create table canonical_observation (
          id uuid primary key default gen_random_uuid(),
          series_id uuid not null references series(id),
          observation_timestamp timestamptz not null,
          version int not null,
          accepted_candidate_id uuid,
          accepted_candidate_timestamp timestamptz,
          value_json jsonb not null,
          value_schema_key text not null,
          acceptance_reason text not null,
          canonical_status text not null check (canonical_status in (
            'active','superseded','rejected','under_review'
          )),
          stale_status text not null default 'unknown',
          fallback_in_use boolean not null default false,
          conflict_present boolean not null default false,
          accepted_at timestamptz not null default now(),
          accepted_by uuid references app_user(id),
          check (
            (accepted_candidate_id is null and accepted_candidate_timestamp is null)
            or
            (accepted_candidate_id is not null and accepted_candidate_timestamp is not null)
          ),
          foreign key (accepted_candidate_id, accepted_candidate_timestamp)
            references observation_candidate(id, observation_timestamp),
          unique(series_id, observation_timestamp, version)
        );

        create unique index canonical_one_active_idx
          on canonical_observation(series_id, observation_timestamp)
          where canonical_status = 'active';

        create table latest_series_state (
          series_id uuid primary key references series(id),
          canonical_observation_id uuid references canonical_observation(id),
          observation_timestamp timestamptz,
          value_json jsonb not null,
          freshness_status text not null,
          delay_classification text not null,
          source_key text,
          fallback_in_use boolean not null,
          conflict_present boolean not null,
          rebuilt_at timestamptz not null default now()
        );

        create table source_document (
          id uuid primary key default gen_random_uuid(),
          canonical_object_id uuid references canonical_object(id),
          source_id uuid references data_source(id),
          title text,
          original_url text,
          canonical_url text,
          publisher text,
          acquisition_mode text not null,
          acquisition_stack text not null,
          retention_class text not null,
          fetched_at timestamptz,
          source_published_at timestamptz,
          language text,
          content_hash text,
          raw_object_key text,
          parse_quality numeric,
          completeness_score numeric,
          legal_risk_level text not null default 'unknown',
          review_required boolean not null default true,
          downstream_ai_allowed text not null default 'extract_only',
          public_allowed boolean not null default false,
          status text not null default 'discovered',
          metadata jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now()
        );

        create table source_evidence (
          id uuid primary key default gen_random_uuid(),
          source_document_id uuid not null references source_document(id),
          evidence_excerpt text,
          evidence_hash text not null,
          location_json jsonb,
          extraction_model_version text,
          confidence numeric,
          manually_confirmed boolean not null default false,
          public_allowed boolean not null default false,
          created_at timestamptz not null default now()
        );

        create table fact_type_registry (
          fact_type text primary key,
          display_name_en text not null,
          display_name_ko text,
          json_schema jsonb not null,
          allowed_predicates text[] not null,
          public_allowed_default boolean not null default false,
          requires_review boolean not null default true,
          active boolean not null default true
        );

        create table source_fact (
          id uuid primary key default gen_random_uuid(),
          source_evidence_id uuid references source_evidence(id),
          fact_type text not null references fact_type_registry(fact_type),
          subject_object_id uuid references canonical_object(id),
          predicate text not null,
          object_json jsonb not null,
          time_reference jsonb,
          confidence numeric not null,
          extraction_source text not null check (extraction_source in ('rule','llm','manual')),
          review_status text not null default 'candidate',
          public_allowed boolean not null default false,
          created_at timestamptz not null default now()
        );

        create table economic_release (
          id uuid primary key default gen_random_uuid(),
          canonical_object_id uuid not null references canonical_object(id),
          release_key text not null unique,
          country_region_object_id uuid not null references canonical_object(id),
          release_type text not null,
          scheduled_at timestamptz,
          scheduled_local_date date,
          time_precision text not null check (time_precision in ('date_only','time_confirmed','time_estimated')),
          timezone text not null,
          source_id uuid references data_source(id),
          status text not null default 'scheduled',
          linked_series_id uuid references series(id),
          created_at timestamptz not null default now()
        );

        create table expectation_value (
          id uuid primary key default gen_random_uuid(),
          economic_release_id uuid not null references economic_release(id),
          expectation_type text not null check (expectation_type in (
            'official_projection','licensed_consensus','open_survey','manual_estimate','internal_forecast','unknown'
          )),
          value_json jsonb,
          units text,
          source_id uuid references data_source(id),
          methodology_key text,
          public_allowed boolean not null default false,
          review_status text not null default 'candidate',
          created_at timestamptz not null default now()
        );

        create table geo_event (
          id uuid primary key default gen_random_uuid(),
          canonical_object_id uuid not null references canonical_object(id),
          event_key text not null unique,
          primary_country_region_object_id uuid references canonical_object(id),
          event_type text not null,
          severity text not null check (severity in ('low','medium','high','critical')),
          confidence numeric not null,
          source_strength text not null,
          review_status text not null default 'candidate',
          public_status text not null default 'not_public',
          occurred_at timestamptz,
          discovered_at timestamptz not null default now(),
          published_at timestamptz,
          correction_status text not null default 'none',
          summary_object_id uuid references canonical_object(id)
        );

        create table geo_event_link (
          id uuid primary key default gen_random_uuid(),
          geo_event_id uuid not null references geo_event(id),
          linked_object_id uuid not null references canonical_object(id),
          link_type text not null check (link_type in ('country','region','sector','entity','instrument','source_fact')),
          confidence numeric not null default 1,
          unique(geo_event_id, linked_object_id, link_type)
        );

        create table scenario_basket (
          id uuid primary key default gen_random_uuid(),
          canonical_object_id uuid not null references canonical_object(id),
          basket_key text not null unique,
          thesis text not null,
          methodology text not null,
          risk_summary text not null,
          data_delay_warning text not null,
          approval_status text not null default 'draft',
          approved_by uuid references app_user(id),
          approved_at timestamptz,
          created_at timestamptz not null default now()
        );

        create table scenario_basket_item (
          id uuid primary key default gen_random_uuid(),
          scenario_basket_id uuid not null references scenario_basket(id),
          object_id uuid not null references canonical_object(id),
          inclusion_reason text not null,
          illustrative_weight numeric,
          unique(scenario_basket_id, object_id)
        );

        create table llm_model_profile (
          id uuid primary key default gen_random_uuid(),
          provider_key text not null,
          model_key text not null,
          context_length int,
          structured_output_support boolean not null default false,
          tool_support boolean not null default false,
          privacy_class text not null default 'PUBLIC_FACTS_ONLY',
          data_use_policy text not null default 'unknown',
          billing_mode text not null default 'unknown',
          rate_limits jsonb not null default '{}'::jsonb,
          quality_scores jsonb not null default '{}'::jsonb,
          latency_score numeric,
          enabled boolean not null default false,
          created_at timestamptz not null default now(),
          unique(provider_key, model_key)
        );

        create table llm_invocation (
          id uuid primary key default gen_random_uuid(),
          task_type text not null,
          model_profile_id uuid not null references llm_model_profile(id),
          provider_key text not null,
          input_class text not null,
          input_hash text not null,
          output_hash text,
          prompt_version text not null,
          schema_key text,
          status text not null check (status in ('succeeded','schema_failed','rejected','provider_failed','quota_failed')),
          token_input_count int,
          token_output_count int,
          cost_estimate_usd numeric,
          cache_hit boolean not null default false,
          created_at timestamptz not null default now()
        );

        create table llm_cache (
          cache_key text primary key,
          task_type text not null,
          prompt_version text not null,
          model_profile_id uuid not null references llm_model_profile(id),
          input_object_hash text not null,
          locale text,
          glossary_hash text,
          output_json jsonb not null,
          output_hash text not null,
          created_at timestamptz not null default now()
        );

        create table content_summary (
          id uuid primary key default gen_random_uuid(),
          source_object_id uuid not null references canonical_object(id),
          locale text not null check (locale in ('en','ko')),
          title text not null,
          summary text not null,
          why_it_matters text not null default '',
          source_content_hash text not null,
          glossary_version text not null default 'seed-v1',
          review_status text not null default 'candidate',
          public_allowed boolean not null default false,
          stale boolean not null default false,
          source_policy_versions jsonb not null default '[]'::jsonb,
          created_at timestamptz not null default now(),
          reviewed_at timestamptz,
          unique(source_object_id, locale, source_content_hash, glossary_version),
          check (not (public_allowed and stale))
        );

        create table content_translation (
          id uuid primary key default gen_random_uuid(),
          source_object_id uuid not null references canonical_object(id),
          source_locale text not null,
          target_locale text not null,
          source_content_hash text not null,
          glossary_version text not null,
          translated_text text not null,
          translation_method text not null check (translation_method in ('manual','llm','hybrid')),
          model_profile_id uuid references llm_model_profile(id),
          review_status text not null default 'candidate',
          stale boolean not null default false,
          public_allowed boolean not null default false,
          created_at timestamptz not null default now(),
          reviewed_at timestamptz,
          unique(source_object_id, target_locale, source_content_hash, glossary_version),
          check (not (public_allowed and stale))
        );

        create table publication_snapshot (
          id uuid primary key default gen_random_uuid(),
          snapshot_version int not null,
          locale text not null,
          object_type text not null,
          object_key text not null,
          schema_version text not null,
          storage_object_key text not null,
          content_hash text not null,
          byte_size bigint not null,
          generated_at timestamptz not null,
          stale_after timestamptz,
          hard_expires_at timestamptz,
          source_policy_versions jsonb not null default '[]'::jsonb,
          publication_status text not null check (publication_status in ('candidate','published','rolled_back','retracted')),
          generated_by uuid references app_user(id),
          unique(snapshot_version, locale, object_type, object_key)
        );

        create table publication_manifest (
          snapshot_version int primary key,
          manifest_json jsonb not null,
          storage_object_key text not null default 'public/latest/manifest.json',
          content_hash text not null,
          byte_size bigint not null,
          generated_at timestamptz not null,
          published_at timestamptz,
          publication_status text not null check (publication_status in ('candidate','published','rolled_back','retracted')),
          generated_by uuid references app_user(id)
        );

        create table correction_log (
          id uuid primary key default gen_random_uuid(),
          title text not null,
          summary text not null,
          status text not null check (status in ('correction','retraction','clarification')),
          affected_object_key text,
          published_at timestamptz not null default now(),
          published_by uuid references app_user(id)
        );

        create table audit_log (
          id uuid primary key default gen_random_uuid(),
          actor_user_id uuid references app_user(id),
          actor_role text,
          action text not null,
          target_object_id uuid references canonical_object(id),
          target_table text,
          target_pk text,
          before_hash text,
          after_hash text,
          request_id text,
          ip_hash text,
          user_agent_hash text,
          created_at timestamptz not null default now()
        );

        create table operation_status (
          status_key text primary key,
          status_value text not null,
          severity text not null check (severity in ('info','warning','critical')) default 'info',
          details jsonb not null default '{}'::jsonb,
          updated_at timestamptz not null default now()
        );

        create index audit_log_created_idx on audit_log(created_at desc);
        create index content_summary_public_idx on content_summary(source_object_id, locale)
          where public_allowed = true and stale = false;
        create index source_fact_review_idx on source_fact(review_status, public_allowed);
        create index geo_event_public_idx on geo_event(public_status, review_status, severity);
        create index publication_snapshot_status_idx on publication_snapshot(publication_status, generated_at desc);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists audit_log cascade;
        drop table if exists operation_status cascade;
        drop table if exists correction_log cascade;
        drop table if exists publication_manifest cascade;
        drop table if exists publication_snapshot cascade;
        drop table if exists content_translation cascade;
        drop table if exists content_summary cascade;
        drop table if exists llm_cache cascade;
        drop table if exists llm_invocation cascade;
        drop table if exists llm_model_profile cascade;
        drop table if exists scenario_basket_item cascade;
        drop table if exists scenario_basket cascade;
        drop table if exists geo_event_link cascade;
        drop table if exists geo_event cascade;
        drop table if exists expectation_value cascade;
        drop table if exists economic_release cascade;
        drop table if exists source_fact cascade;
        drop table if exists fact_type_registry cascade;
        drop table if exists source_evidence cascade;
        drop table if exists source_document cascade;
        drop table if exists latest_series_state cascade;
        drop table if exists canonical_observation cascade;
        drop table if exists observation_candidate cascade;
        drop table if exists series cascade;
        drop table if exists job_concurrency_limit cascade;
        drop table if exists job_queue cascade;
        drop table if exists source_policy_decision cascade;
        drop table if exists provider_usage_event cascade;
        drop table if exists source_health_status cascade;
        drop table if exists provider_budget cascade;
        drop table if exists data_source cascade;
        drop table if exists instrument cascade;
        drop table if exists entity cascade;
        drop table if exists sector cascade;
        drop table if exists country_region_membership cascade;
        drop table if exists country_region cascade;
        drop table if exists canonical_object cascade;
        drop table if exists app_session cascade;
        drop table if exists user_totp_secret cascade;
        drop table if exists app_user cascade;
        """
    )
