defmodule StonksBackend.Repo.Migrations.AddTickerMemberFoundations do
  use Ecto.Migration

  def up do
    execute("alter table app_user drop constraint if exists app_user_role_check")

    execute("""
    alter table app_user
      add constraint app_user_role_check
      check (role in ('owner','admin','editor','viewer','member'))
    """)

    execute("""
    alter table oauth_login_state
      add column if not exists purpose text not null default 'admin'
    """)

    execute(
      "alter table oauth_login_state drop constraint if exists oauth_login_state_purpose_check"
    )

    execute("""
    alter table oauth_login_state
      add constraint oauth_login_state_purpose_check
      check (purpose in ('admin','member'))
    """)

    execute("""
    create table if not exists ticker_workspace (
      user_id uuid primary key references app_user(id) on delete cascade,
      revision bigint not null default 1 check (revision > 0),
      workspace jsonb not null,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      check (octet_length(workspace::text) <= 500000)
    )
    """)

    execute("""
    create table if not exists ticker_alert_rule (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references app_user(id) on delete cascade,
      symbol text not null,
      rule_type text not null check (rule_type in (
        'price_threshold','rsi','macd_cross','volume_spike','sec_filing',
        'news_spike','short_interest_update','option_iv_threshold'
      )),
      configuration jsonb not null,
      cooldown_seconds int not null default 3600 check (cooldown_seconds between 0 and 2592000),
      email_enabled boolean not null default false,
      active boolean not null default true,
      last_evaluated_source_at timestamptz,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )
    """)

    execute(
      "create index if not exists ticker_alert_rule_user_idx on ticker_alert_rule(user_id, active, updated_at desc)"
    )

    execute(
      "create index if not exists ticker_alert_rule_eval_idx on ticker_alert_rule(rule_type, active, last_evaluated_source_at)"
    )

    execute("""
    create table if not exists ticker_alert_event (
      id uuid primary key default gen_random_uuid(),
      rule_id uuid not null references ticker_alert_rule(id) on delete cascade,
      user_id uuid not null references app_user(id) on delete cascade,
      source_event_key text not null,
      source_at timestamptz not null,
      reason text not null,
      payload jsonb not null default '{}'::jsonb,
      delivery_status text not null default 'in_app' check (delivery_status in ('in_app','email_queued','email_accepted','email_failed')),
      read_at timestamptz,
      created_at timestamptz not null default now(),
      unique(rule_id, source_event_key)
    )
    """)

    execute(
      "create index if not exists ticker_alert_event_user_idx on ticker_alert_event(user_id, created_at desc)"
    )

    execute(
      "create index if not exists ticker_alert_event_unread_idx on ticker_alert_event(user_id, created_at desc) where read_at is null"
    )

    execute("""
    create table if not exists user_notification_preference (
      user_id uuid primary key references app_user(id) on delete cascade,
      locale text not null default 'en' check (locale in ('en','ko')),
      email_opt_in boolean not null default false,
      unsubscribed_at timestamptz,
      unsubscribe_token_hash text unique,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )
    """)

    execute("""
    create table if not exists user_provider_connection (
      id uuid primary key default gen_random_uuid(),
      user_id uuid not null references app_user(id) on delete cascade,
      provider_key text not null check (provider_key in ('marketdata_app')),
      token_ciphertext bytea not null,
      token_nonce bytea not null,
      key_version int not null default 1,
      verification_status text not null default 'pending' check (verification_status in ('pending','verified','failed')),
      verified_at timestamptz,
      verification_metadata jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      unique(user_id, provider_key)
    )
    """)

    execute(
      "create index if not exists user_provider_connection_status_idx on user_provider_connection(user_id, verification_status)"
    )

    execute("""
    create table if not exists ticker_fundamental_snapshot (
      id uuid primary key default gen_random_uuid(),
      symbol text not null,
      cik text,
      status text not null check (status in ('ready','stale','unavailable','failed')),
      coverage_reason text,
      metrics jsonb not null default '{}'::jsonb,
      provenance jsonb not null default '{}'::jsonb,
      period_end date,
      form text,
      filing_url text,
      source_filed_at timestamptz,
      fetched_at timestamptz not null,
      stale_after timestamptz not null,
      created_at timestamptz not null default now(),
      unique(symbol, fetched_at)
    )
    """)

    execute(
      "create index if not exists ticker_fundamental_snapshot_latest_idx on ticker_fundamental_snapshot(symbol, fetched_at desc)"
    )
  end

  def down do
    # Member tables and role/state additions are deliberately retained during an
    # application rollback. Rollback is performed by disabling the additive
    # feature flags, which avoids destroying user workspaces, alert history, or
    # encrypted connection records before a corrected release is deployed.
    :ok
  end
end
