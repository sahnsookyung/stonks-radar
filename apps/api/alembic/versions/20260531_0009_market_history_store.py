"""market history storage and portfolio calculation cache

Revision ID: 20260531_0009
Revises: 20260531_0008
Create Date: 2026-05-31
"""

from __future__ import annotations

from alembic import op

revision = "20260531_0009"
down_revision = "20260531_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table if not exists market_data_provider_capability (
          provider_key text not null,
          endpoint_key text not null,
          max_requests_per_minute numeric,
          max_requests_per_day numeric,
          cost_per_symbol numeric not null default 1,
          cost_per_request numeric not null default 1,
          max_output_points integer,
          supports_adjusted boolean not null default false,
          supports_batch boolean not null default false,
          history_depth_days integer,
          source_url text,
          source_checked_at date,
          notes text,
          active boolean not null default true,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          primary key (provider_key, endpoint_key)
        );

        create table if not exists market_data_source_policy (
          provider_key text not null,
          endpoint_key text not null,
          entitlement_status text not null default 'pending_review' check (
            entitlement_status in (
              'pending_review',
              'policy_approved',
              'policy_approved_pending_live_test',
              'blocked',
              'unknown'
            )
          ),
          live_test_status text not null default 'untested' check (
            live_test_status in ('untested','passing','failing','disabled')
          ),
          internal_calculation_allowed boolean not null default false,
          normalized_storage_allowed boolean not null default false,
          raw_storage_allowed boolean not null default false,
          raw_public_allowed boolean not null default false,
          derived_public_allowed boolean not null default false,
          retention_days integer,
          attribution_required boolean not null default false,
          policy_reviewed_at timestamptz,
          source_url text,
          notes text,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          primary key (provider_key, endpoint_key)
        );

        create table if not exists market_data_provider_symbol (
          instrument_key text not null,
          provider_key text not null,
          provider_symbol text not null,
          exchange text,
          currency_code text,
          timezone text,
          supported_intervals text[] not null default array['1day']::text[],
          active boolean not null default true,
          last_success_at timestamptz,
          last_error_class text,
          details jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          primary key (instrument_key, provider_key, provider_symbol)
        );

        create table if not exists market_data_quota_reservation (
          id uuid primary key default gen_random_uuid(),
          reservation_token uuid not null,
          provider_key text not null,
          endpoint_key text not null default 'daily_prices',
          partition_key text not null default 'scheduled_public',
          window_start timestamptz not null,
          window_seconds integer not null,
          cost numeric not null default 1,
          units jsonb not null default '{}'::jsonb,
          status text not null default 'reserved' check (
            status in ('reserved','succeeded','failed','deferred','cancelled')
          ),
          idempotency_key text,
          job_id uuid references job_queue(id),
          actor text not null default 'scheduler',
          reserved_at timestamptz not null default now(),
          finalized_at timestamptz,
          retry_after_seconds integer,
          error_class text,
          details jsonb not null default '{}'::jsonb
        );

        create index if not exists market_data_quota_reservation_window_idx
          on market_data_quota_reservation(provider_key, endpoint_key, window_start, status);

        create index if not exists market_data_quota_reservation_token_idx
          on market_data_quota_reservation(reservation_token);

        drop index if exists market_data_quota_reservation_idempotency_idx;

        create unique index if not exists market_data_quota_reservation_idempotency_idx
          on market_data_quota_reservation(
            provider_key,
            endpoint_key,
            partition_key,
            idempotency_key,
            window_seconds,
            window_start
          )
          where idempotency_key is not null
            and status in ('reserved','succeeded');

        create table if not exists market_fetch_run (
          id uuid primary key default gen_random_uuid(),
          batch_id uuid not null unique default gen_random_uuid(),
          provider_key text not null,
          endpoint_key text not null default 'daily_prices',
          requested_symbols text[] not null,
          requested_start date not null,
          requested_end date not null,
          fetch_started_at timestamptz not null default now(),
          fetch_completed_at timestamptz,
          provider_batch_id text,
          provider_revision text,
          status text not null default 'fetched' check (
            status in ('fetched','validated','promoted','quarantined','failed')
          ),
          quality_state text not null default 'unchecked' check (
            quality_state in ('unchecked','valid','suspect','quarantined','failed')
          ),
          quota_reservation_token uuid,
          quota_reservation_tokens uuid[] not null default '{}'::uuid[],
          source_policy_digest text,
          content_hash text,
          validation_summary jsonb not null default '{}'::jsonb,
          error_class text,
          error_message text,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now()
        );

        create index if not exists market_fetch_run_provider_idx
          on market_fetch_run(provider_key, endpoint_key, fetch_started_at desc);

        create table if not exists market_price_bar_candidate (
          id bigserial primary key,
          fetch_run_id uuid not null references market_fetch_run(id) on delete cascade,
          batch_id uuid not null,
          provider_key text not null,
          symbol text not null,
          interval text not null default '1day',
          price_date date not null,
          open numeric,
          high numeric,
          low numeric,
          close numeric not null,
          adjusted_close numeric,
          volume numeric,
          currency_code text not null default 'USD',
          exchange text,
          timezone text,
          provider_price_timestamp timestamptz,
          source_hash text not null,
          source_revision text,
          quality_state text not null default 'unchecked' check (
            quality_state in ('unchecked','valid','suspect','quarantined')
          ),
          quality_json jsonb not null default '{}'::jsonb,
          source_policy_json jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now(),
          unique (batch_id, provider_key, symbol, interval, price_date)
        );

        create index if not exists market_price_bar_candidate_lookup_idx
          on market_price_bar_candidate(symbol, interval, price_date desc, quality_state);

        create table if not exists market_data_snapshot (
          id uuid primary key default gen_random_uuid(),
          fetch_run_id uuid not null references market_fetch_run(id),
          batch_id uuid not null,
          provider_key text not null,
          endpoint_key text not null default 'daily_prices',
          interval text not null default '1day',
          symbols text[] not null,
          price_start date not null,
          price_end date not null,
          provider_batch_id text,
          provider_revision text,
          quality_state text not null check (quality_state in ('valid','suspect','quarantined')),
          promoted_at timestamptz,
          source_policy_digest text not null,
          content_hash text not null,
          manifest_json jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now()
        );

        create index if not exists market_data_snapshot_lookup_idx
          on market_data_snapshot(interval, price_end desc, promoted_at desc);

        create table if not exists market_data_snapshot_member (
          snapshot_id uuid not null references market_data_snapshot(id) on delete cascade,
          candidate_id bigint not null references market_price_bar_candidate(id),
          symbol text not null,
          interval text not null default '1day',
          price_date date not null,
          provider_key text not null,
          quality_state text not null,
          primary key (snapshot_id, symbol, interval, price_date)
        );

        create index if not exists market_data_snapshot_member_lookup_idx
          on market_data_snapshot_member(symbol, interval, price_date desc);

        create table if not exists market_data_backup_restore_event (
          id uuid primary key default gen_random_uuid(),
          event_type text not null check (event_type in ('backup','restore','verify')),
          storage_uri text,
          content_hash text,
          started_at timestamptz not null default now(),
          completed_at timestamptz,
          status text not null default 'started' check (
            status in ('started','succeeded','failed')
          ),
          details jsonb not null default '{}'::jsonb
        );

        create table if not exists market_price_bar_staging (
          id bigserial primary key,
          batch_id uuid not null default gen_random_uuid(),
          provider_key text not null,
          symbol text not null,
          interval text not null default '1day',
          requested_start date,
          requested_end date,
          payload_json jsonb not null,
          source_hash text not null,
          created_at timestamptz not null default now()
        );

        create index if not exists market_price_bar_staging_symbol_idx
          on market_price_bar_staging(provider_key, symbol, interval, created_at desc);

        create table if not exists market_price_bar (
          id bigserial primary key,
          symbol text not null,
          interval text not null default '1day',
          price_date date not null,
          provider_key text not null,
          open numeric,
          high numeric,
          low numeric,
          close numeric not null,
          adjusted_close numeric,
          adjustment_factor numeric,
          volume numeric,
          currency_code text not null default 'USD',
          exchange text,
          timezone text,
          provider_price_timestamp timestamptz,
          ingested_at timestamptz not null default now(),
          source_hash text not null,
          source_revision text,
          is_adjusted boolean not null default false,
          is_partial boolean not null default false,
          is_suspect boolean not null default false,
          quality_state text not null default 'valid' check (
            quality_state in ('valid','suspect','quarantined')
          ),
          market_data_snapshot_id uuid references market_data_snapshot(id),
          is_corporate_action_window boolean not null default false,
          quality_json jsonb not null default '{}'::jsonb,
          raw_retained_until timestamptz,
          source_policy_json jsonb not null default '{}'::jsonb,
          created_at timestamptz not null default now(),
          updated_at timestamptz not null default now(),
          unique (symbol, interval, price_date, provider_key)
        );

        create index if not exists market_price_bar_lookup_idx
          on market_price_bar(symbol, interval, price_date desc);

        create index if not exists market_price_bar_provider_idx
          on market_price_bar(provider_key, interval, ingested_at desc);

        create index if not exists market_price_bar_snapshot_idx
          on market_price_bar(market_data_snapshot_id, symbol, price_date desc);

        create table if not exists market_data_version (
          symbol text not null,
          interval text not null default '1day',
          version bigint not null default 1,
          latest_price_date date,
          updated_at timestamptz not null default now(),
          source_policy_digest text,
          primary key (symbol, interval)
        );

        create table if not exists portfolio_calculation_cache (
          cache_key text primary key,
          portfolio_hash text not null,
          assumptions_hash text not null,
          base_currency text not null,
          benchmark_symbol text,
          date_start date,
          date_end date,
          market_data_version_key text not null,
          market_data_snapshot_id uuid references market_data_snapshot(id),
          source_policy_digest text not null,
          public_allowed boolean not null default false,
          payload jsonb not null,
          created_at timestamptz not null default now(),
          expires_at timestamptz not null
        );

        create index if not exists portfolio_calculation_cache_expiry_idx
          on portfolio_calculation_cache(expires_at);

        create index if not exists job_queue_market_history_nonterminal_idx
          on job_queue(job_type, (payload->>'symbol'), status)
          where job_type = 'market_data.refresh_history'
            and status in ('queued','running','retry_wait','quota_wait');

        alter table job_concurrency_limit
          drop constraint if exists job_concurrency_limit_scope_type_check;

        alter table job_concurrency_limit
          add constraint job_concurrency_limit_scope_type_check
          check (scope_type in ('job_type','job_group','source','provider','global'));

        insert into job_concurrency_limit(scope_type, scope_key, max_running)
        values
          ('job_group', 'market_data', 1),
          ('provider', 'market_data', 1)
        on conflict (scope_type, scope_key)
        do update set max_running = excluded.max_running, enabled = true;
        """
    )
    op.execute(
        """
        insert into market_data_provider_capability (
          provider_key,
          endpoint_key,
          max_requests_per_minute,
          max_requests_per_day,
          max_output_points,
          supports_adjusted,
          supports_batch,
          history_depth_days,
          source_url,
          source_checked_at,
          notes
        )
        values
          ('twelve_data','daily_prices',5,560,5000,true,false,3650,'https://support.twelvedata.com/en/articles/5335783-trial','2026-05-25','Use as a scheduled normalized daily-bar source only. Caps are set near 70% of the documented free quota.'),
          ('alpha_vantage','daily_prices',null,17,100,true,false,100,'https://www.alphavantage.co/premium/','2026-05-25','Compact free endpoint is fallback only; avoid broad warmups. Caps are set near 70% of the documented free quota.'),
          ('fmp','daily_prices',null,175,5000,true,false,3650,'https://site.financialmodelingprep.com/pricing-plans','2026-05-25','Free endpoint is fallback and byte-budget constrained. Caps are set near 70% of the documented free quota.'),
          ('nasdaq_data_link','daily_prices',70,7000,5000,false,true,3650,'https://docs.data.nasdaq.com/docs/rate-limits-1','2026-05-25','Dataset access varies by table; not enabled for equities until dataset policy is reviewed. Caps are set near 70% of the documented free quota.')
        on conflict (provider_key, endpoint_key) do update set
          max_requests_per_minute = excluded.max_requests_per_minute,
          max_requests_per_day = excluded.max_requests_per_day,
          max_output_points = excluded.max_output_points,
          supports_adjusted = excluded.supports_adjusted,
          supports_batch = excluded.supports_batch,
          history_depth_days = excluded.history_depth_days,
          source_url = excluded.source_url,
          source_checked_at = excluded.source_checked_at,
          notes = excluded.notes,
          updated_at = now();

        insert into market_data_source_policy (
          provider_key,
          endpoint_key,
          entitlement_status,
          live_test_status,
          internal_calculation_allowed,
          normalized_storage_allowed,
          raw_storage_allowed,
          raw_public_allowed,
          derived_public_allowed,
          retention_days,
          attribution_required,
          policy_reviewed_at,
          source_url,
          notes
        )
        values
          ('twelve_data','daily_prices','policy_approved_pending_live_test','untested',true,true,false,false,false,null,true,now(),'https://support.twelvedata.com/en/articles/5335783-trial','Store normalized daily bars for internal calculations; do not redistribute raw quotes/candles publicly.'),
          ('alpha_vantage','daily_prices','policy_approved_pending_live_test','untested',true,true,false,false,false,null,false,now(),'https://www.alphavantage.co/premium/','Store normalized fallback daily bars for internal calculations; do not redistribute raw quotes/candles publicly.'),
          ('fmp','daily_prices','policy_approved_pending_live_test','untested',true,true,false,false,false,null,false,now(),'https://site.financialmodelingprep.com/pricing-plans','Store normalized fallback daily bars for internal calculations; do not redistribute raw quotes/candles publicly.'),
          ('nasdaq_data_link','daily_prices','pending_review','untested',false,false,false,false,false,null,false,now(),'https://docs.data.nasdaq.com/docs/rate-limits-1','Rate limits are generous, but dataset entitlement and redistribution policy must be reviewed before use.')
        on conflict (provider_key, endpoint_key) do update set
          entitlement_status = excluded.entitlement_status,
          live_test_status = excluded.live_test_status,
          internal_calculation_allowed = excluded.internal_calculation_allowed,
          normalized_storage_allowed = excluded.normalized_storage_allowed,
          raw_storage_allowed = excluded.raw_storage_allowed,
          raw_public_allowed = excluded.raw_public_allowed,
          derived_public_allowed = excluded.derived_public_allowed,
          retention_days = excluded.retention_days,
          attribution_required = excluded.attribution_required,
          policy_reviewed_at = excluded.policy_reviewed_at,
          source_url = excluded.source_url,
          notes = excluded.notes,
          updated_at = now();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        delete from job_concurrency_limit
        where (scope_type = 'job_group' and scope_key = 'market_data')
           or (scope_type = 'provider' and scope_key = 'market_data');

        drop index if exists job_queue_market_history_nonterminal_idx;
        drop index if exists portfolio_calculation_cache_expiry_idx;
        drop table if exists portfolio_calculation_cache;
        drop table if exists market_data_version;
        drop index if exists market_price_bar_snapshot_idx;
        drop index if exists market_price_bar_provider_idx;
        drop index if exists market_price_bar_lookup_idx;
        drop table if exists market_price_bar;
        drop index if exists market_price_bar_staging_symbol_idx;
        drop table if exists market_price_bar_staging;
        drop table if exists market_data_backup_restore_event;
        drop index if exists market_data_snapshot_member_lookup_idx;
        drop table if exists market_data_snapshot_member;
        drop index if exists market_data_snapshot_lookup_idx;
        drop table if exists market_data_snapshot;
        drop index if exists market_price_bar_candidate_lookup_idx;
        drop table if exists market_price_bar_candidate;
        drop index if exists market_fetch_run_provider_idx;
        drop table if exists market_fetch_run;
        drop index if exists market_data_quota_reservation_idempotency_idx;
        drop index if exists market_data_quota_reservation_token_idx;
        drop index if exists market_data_quota_reservation_window_idx;
        drop table if exists market_data_quota_reservation;
        drop table if exists market_data_provider_symbol;
        drop table if exists market_data_source_policy;
        drop table if exists market_data_provider_capability;
        """
    )
