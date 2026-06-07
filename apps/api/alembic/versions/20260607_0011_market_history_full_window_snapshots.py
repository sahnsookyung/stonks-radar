"""full-window market history snapshots

Revision ID: 20260607_0011
Revises: 20260604_0010
Create Date: 2026-06-07
"""

from __future__ import annotations

from alembic import op

revision = "20260607_0011"
down_revision = "20260604_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table if not exists market_data_snapshot_current (
          symbol text not null,
          provider_key text not null,
          endpoint_key text not null default 'daily_prices',
          interval text not null default '1day',
          window_key text not null default 'rolling_3y',
          window_days integer not null default 1095,
          snapshot_id uuid not null references market_data_snapshot(id) on delete cascade,
          previous_snapshot_id uuid references market_data_snapshot(id),
          requested_start date not null,
          requested_end date not null,
          price_start date not null,
          complete_through date not null,
          source_observed_at timestamptz,
          hard_expires_at timestamptz,
          staleness_state text not null default 'active' check (
            staleness_state in ('active','delayed','stale_fallback','hard_expired','unavailable')
          ),
          calculation_eligible boolean not null default true,
          source_policy_digest text,
          content_hash text,
          updated_at timestamptz not null default now(),
          created_at timestamptz not null default now(),
          primary key (symbol, provider_key, endpoint_key, interval, window_key)
        );

        create index if not exists market_data_snapshot_current_lookup_idx
          on market_data_snapshot_current(symbol, interval, provider_key, window_key);

        create index if not exists market_data_snapshot_current_snapshot_idx
          on market_data_snapshot_current(snapshot_id);
        """
    )
    op.execute(
        """
        insert into market_data_provider_capability (
          provider_key,
          endpoint_key,
          max_requests_per_minute,
          max_requests_per_day,
          cost_per_symbol,
          cost_per_request,
          max_output_points,
          supports_adjusted,
          supports_batch,
          history_depth_days,
          source_url,
          source_checked_at,
          notes
        )
        values
          ('twelve_data','daily_prices',6,700,1,0,5000,true,true,3650,'https://support.twelvedata.com/en/articles/5615854-credits','2026-06-07','Full rolling 3Y daily snapshots. Twelve Data credits are charged per symbol, not per returned row; batch reduces HTTP overhead only.'),
          ('yahoo_admin','daily_prices',1,30,1,0,5000,true,false,3650,'https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html','2026-06-07','Admin/private only. Not eligible for public snapshots or redistribution.')
        on conflict (provider_key, endpoint_key) do update set
          max_requests_per_minute = excluded.max_requests_per_minute,
          max_requests_per_day = excluded.max_requests_per_day,
          cost_per_symbol = excluded.cost_per_symbol,
          cost_per_request = excluded.cost_per_request,
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
          ('twelve_data','daily_prices','policy_approved_pending_live_test','untested',true,true,false,false,false,null,true,now(),'https://support.twelvedata.com/en/articles/5615854-credits','Store normalized full-window daily snapshots for calculations. Do not redistribute raw candles publicly.'),
          ('yahoo_admin','daily_prices','blocked','disabled',false,false,false,false,false,null,false,now(),'https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html','Yahoo chart data is admin/private only and must never be included in public snapshots.')
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
        delete from market_data_provider_capability
        where provider_key = 'yahoo_admin' and endpoint_key = 'daily_prices';

        delete from market_data_source_policy
        where provider_key = 'yahoo_admin' and endpoint_key = 'daily_prices';

        drop index if exists market_data_snapshot_current_snapshot_idx;
        drop index if exists market_data_snapshot_current_lookup_idx;
        drop table if exists market_data_snapshot_current;
        """
    )
