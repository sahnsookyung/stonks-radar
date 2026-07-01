defmodule StonksBackend.Repo.Migrations.CreatePreservedDomainSchema do
  use Ecto.Migration

  def up do
    execute_many("""
    create extension if not exists pgcrypto;

    create table if not exists app_user (
      id uuid primary key default gen_random_uuid(),
      email text not null unique,
      password_hash text not null,
      role text not null check (role in ('owner','admin','editor','viewer')),
      active boolean not null default true,
      totp_required boolean not null default true,
      recovery_codes_hash text[] not null default '{}',
      auth_provider text not null default 'password',
      external_subject text,
      last_login_at timestamptz,
      auth_metadata jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    );

    create unique index if not exists app_user_auth_provider_subject_idx
      on app_user(auth_provider, external_subject)
      where external_subject is not null;

    create table if not exists user_totp_secret (
      user_id uuid primary key references app_user(id) on delete cascade,
      secret_ciphertext text not null,
      verified_at timestamptz,
      created_at timestamptz not null default now()
    );

    create table if not exists app_session (
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

    create table if not exists canonical_object (
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

    create table if not exists country_region (
      canonical_object_id uuid primary key references canonical_object(id),
      region_kind text not null check (region_kind in ('country','region','dynamic_group')),
      iso_alpha2 text,
      iso_alpha3 text,
      methodology_key text,
      methodology_year int,
      source_key text,
      display_order int not null default 100
    );

    create table if not exists country_region_membership (
      id uuid primary key default gen_random_uuid(),
      region_object_id uuid not null references canonical_object(id),
      member_object_id uuid not null references canonical_object(id),
      membership_version text not null,
      valid_from date not null,
      valid_to date,
      source_key text,
      unique(region_object_id, member_object_id, membership_version)
    );

    create table if not exists sector (
      canonical_object_id uuid primary key references canonical_object(id),
      sector_key text not null unique,
      public_enabled boolean not null default true,
      display_order int not null default 100
    );

    create table if not exists entity (
      canonical_object_id uuid primary key references canonical_object(id),
      entity_key text not null unique,
      entity_type text not null default 'company',
      domicile_object_id uuid references canonical_object(id),
      private_reference boolean not null default false
    );

    create table if not exists instrument (
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

    create table if not exists data_source (
      id uuid primary key default gen_random_uuid(),
      source_key text not null unique,
      display_name text not null,
      source_type text not null check (source_type in (
        'official_api','official_page','company_ir','company_email','filing','rss','news_metadata',
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

    create table if not exists provider_budget (
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

    create table if not exists provider_usage_event (
      id uuid primary key default gen_random_uuid(),
      provider_key text not null,
      endpoint_key text,
      partition_key text,
      unit text not null,
      quantity numeric not null,
      estimated_cost_usd numeric not null default 0,
      job_id uuid,
      status text not null default 'succeeded',
      error_class text,
      idempotency_key text,
      reserved_units jsonb not null default '{}'::jsonb,
      actual_units jsonb not null default '{}'::jsonb,
      retry_after_seconds int,
      next_allowed_at timestamptz,
      details jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now()
    );

    create index if not exists provider_usage_event_provider_endpoint_idx
      on provider_usage_event(provider_key, endpoint_key, created_at desc);

    create table if not exists provider_runtime_state (
      provider_key text not null,
      endpoint_key text not null,
      partition_key text not null default 'scheduled_public',
      circuit_state text not null default 'closed' check (circuit_state in ('closed','open')),
      opened_at timestamptz,
      next_allowed_at timestamptz,
      last_success_at timestamptz,
      last_failure_at timestamptz,
      last_error_class text,
      last_status_code int,
      failure_count int not null default 0,
      credential_version text,
      details jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now(),
      primary key (provider_key, endpoint_key, partition_key)
    );

    create index if not exists provider_runtime_state_open_idx
      on provider_runtime_state(next_allowed_at)
      where circuit_state = 'open';

    create table if not exists source_health_status (
      source_key text primary key,
      status text not null check (status in (
        'ready','degraded','unsupported','failed','disabled','denied','quarantined'
      )),
      status_code text,
      response_ms int,
      last_checked_at timestamptz not null default now(),
      last_success_at timestamptz,
      last_error text,
      details jsonb not null default '{}'::jsonb
    );

    create table if not exists source_policy_decision (
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

    create table if not exists job_queue (
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

    create index if not exists job_queue_claim_idx
      on job_queue(status, run_after, priority, created_at)
      where status in ('queued','retry_wait','quota_wait');

    create index if not exists job_queue_lease_idx
      on job_queue(status, lease_expires_at)
      where status = 'running';

    create index if not exists job_queue_news_source_nonterminal_idx
      on job_queue(job_type, (payload->>'source_key'), status)
      where job_type = 'news.fetch_source'
        and status in ('queued','running','retry_wait','quota_wait');

    create index if not exists job_queue_market_history_nonterminal_idx
      on job_queue(job_type, (payload->>'symbol'), status)
      where job_type = 'market_data.refresh_history'
        and status in ('queued','running','retry_wait','quota_wait');

    create table if not exists job_concurrency_limit (
      id uuid primary key default gen_random_uuid(),
      scope_type text not null check (scope_type in ('job_type','job_group','source','provider','global')),
      scope_key text not null,
      max_running int not null,
      enabled boolean not null default true,
      unique(scope_type, scope_key)
    );

    create table if not exists source_document (
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
      dedupe_key text,
      raw_expires_at timestamptz,
      legal_risk_level text not null default 'unknown',
      review_required boolean not null default true,
      downstream_ai_allowed text not null default 'extract_only',
      public_allowed boolean not null default false,
      status text not null default 'discovered',
      metadata jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    );

    create unique index if not exists source_document_dedupe_key_unique
      on source_document(dedupe_key)
      where dedupe_key is not null;

    create table if not exists source_evidence (
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

    create unique index if not exists source_evidence_document_hash_unique
      on source_evidence(source_document_id, evidence_hash);

    create table if not exists fact_type_registry (
      fact_type text primary key,
      display_name_en text not null,
      display_name_ko text,
      json_schema jsonb not null,
      allowed_predicates text[] not null,
      public_allowed_default boolean not null default false,
      requires_review boolean not null default true,
      active boolean not null default true
    );

    create table if not exists source_fact (
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
      dedupe_key text,
      created_at timestamptz not null default now()
    );

    create index if not exists source_fact_review_idx
      on source_fact(review_status, public_allowed);

    create unique index if not exists source_fact_dedupe_key_unique
      on source_fact(dedupe_key)
      where dedupe_key is not null;

    create table if not exists series (
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

    create table if not exists latest_series_state (
      series_id uuid primary key references series(id),
      canonical_observation_id uuid,
      observation_timestamp timestamptz,
      value_json jsonb not null,
      freshness_status text not null,
      delay_classification text not null,
      source_key text,
      fallback_in_use boolean not null,
      conflict_present boolean not null,
      rebuilt_at timestamptz not null default now()
    );

    create table if not exists economic_release (
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

    create table if not exists expectation_value (
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

    create table if not exists geo_event (
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

    create index if not exists geo_event_public_idx
      on geo_event(public_status, review_status, severity);

    create table if not exists geo_event_link (
      id uuid primary key default gen_random_uuid(),
      geo_event_id uuid not null references geo_event(id),
      linked_object_id uuid not null references canonical_object(id),
      link_type text not null check (link_type in ('country','region','sector','entity','instrument','source_fact')),
      confidence numeric not null default 1,
      unique(geo_event_id, linked_object_id, link_type)
    );

    create table if not exists scenario_basket (
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

    create table if not exists scenario_basket_item (
      id uuid primary key default gen_random_uuid(),
      scenario_basket_id uuid not null references scenario_basket(id),
      object_id uuid not null references canonical_object(id),
      inclusion_reason text not null,
      illustrative_weight numeric,
      unique(scenario_basket_id, object_id)
    );

    create table if not exists llm_model_profile (
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

    create table if not exists llm_invocation (
      id uuid primary key default gen_random_uuid(),
      task_type text not null,
      model_profile_id uuid references llm_model_profile(id),
      provider_key text,
      input_class text not null,
      input_hash text not null,
      output_hash text,
      prompt_version text not null,
      schema_key text,
      status text not null check (status in (
        'succeeded','schema_failed','rejected','provider_failed','quota_failed','denied','budget_failed'
      )),
      token_input_count int,
      token_output_count int,
      cost_estimate_usd numeric,
      cache_hit boolean not null default false,
      actor_user_id uuid,
      session_id text,
      request_id text,
      job_id uuid,
      event_id text,
      cache_key text,
      denial_reason text,
      usage_estimate_json jsonb not null default '{}'::jsonb,
      reservation_id text,
      created_at timestamptz not null default now()
    );

    create table if not exists llm_cache (
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

    create table if not exists llm_usage_counter (
      counter_key text not null,
      period_key text not null,
      used numeric not null default 0,
      hard_limit numeric,
      updated_at timestamptz not null default now(),
      primary key (counter_key, period_key)
    );

    create table if not exists content_summary (
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

    create index if not exists content_summary_public_idx
      on content_summary(source_object_id, locale)
      where public_allowed = true and stale = false;

    create table if not exists content_translation (
      id uuid primary key default gen_random_uuid(),
      source_object_id uuid not null references canonical_object(id),
      source_locale text not null,
      target_locale text not null,
      source_content_hash text not null,
      glossary_version text not null default 'seed-v1',
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

    create table if not exists publication_snapshot (
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

    create index if not exists publication_snapshot_status_idx
      on publication_snapshot(publication_status, generated_at desc);

    create table if not exists publication_manifest (
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

    create table if not exists correction_log (
      id uuid primary key default gen_random_uuid(),
      title text not null,
      summary text not null,
      status text not null check (status in ('correction','retraction','clarification')),
      affected_object_key text,
      published_at timestamptz not null default now(),
      published_by uuid references app_user(id)
    );

    create table if not exists audit_log (
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

    create index if not exists audit_log_created_idx on audit_log(created_at desc);

    create table if not exists operation_status (
      status_key text primary key,
      status_value text not null,
      severity text not null check (severity in ('info','warning','critical')) default 'info',
      details jsonb not null default '{}'::jsonb,
      updated_at timestamptz not null default now()
    );

    create table if not exists watched_people (
      id bigserial primary key,
      canonical_name text not null unique,
      category text not null check (category in (
        'donald_trump','spouse','dependent_child','adult_family','related_entity'
      )),
      aliases text[] not null default '{}',
      tickers text[] not null default '{}',
      sec_ciks text[] not null default '{}',
      oge_names text[] not null default '{}',
      notes text,
      created_at timestamptz not null default now()
    );

    create table if not exists source_filings (
      id bigserial primary key,
      source text not null check (source in ('OGE','SEC')),
      form_type text not null,
      filer_name text,
      issuer_name text,
      ticker text,
      cik text,
      accession_number text,
      doc_date date,
      filed_at timestamptz,
      source_url text not null,
      local_path text,
      sha256 text not null,
      raw_metadata jsonb not null default '{}'::jsonb,
      parse_status text not null default 'pending',
      created_at timestamptz not null default now(),
      unique (source, sha256)
    );

    create index if not exists source_filings_source_doc_date_idx
      on source_filings(source, doc_date desc nulls last, created_at desc);
    create index if not exists source_filings_ticker_idx
      on source_filings(ticker)
      where ticker is not null;
    create index if not exists source_filings_cik_idx
      on source_filings(cik)
      where cik is not null;

    create table if not exists security_transactions (
      id bigserial primary key,
      filing_id bigint not null references source_filings(id) on delete cascade,
      source text not null check (source in ('OGE','SEC')),
      person_name text,
      owner_name text,
      issuer_name text,
      ticker text,
      cik text,
      asset_description text,
      transaction_type text,
      transaction_code text,
      transaction_date date,
      amount_min numeric,
      amount_max numeric,
      shares numeric,
      price numeric,
      direct_or_indirect text,
      ownership_nature text,
      post_transaction_shares numeric,
      is_late boolean,
      source_page integer,
      confidence numeric,
      raw_row jsonb not null default '{}'::jsonb,
      dedupe_key text not null,
      created_at timestamptz not null default now(),
      unique (dedupe_key)
    );

    create index if not exists security_transactions_person_idx
      on security_transactions(person_name, transaction_date desc nulls last);
    create index if not exists security_transactions_ticker_idx
      on security_transactions(ticker, transaction_date desc nulls last)
      where ticker is not null;
    create index if not exists security_transactions_source_idx
      on security_transactions(source, transaction_date desc nulls last);

    create table if not exists parse_review_queue (
      id bigserial primary key,
      filing_id bigint references source_filings(id) on delete cascade,
      issue_type text not null,
      raw_excerpt text,
      suggested_fix jsonb,
      status text not null default 'open' check (status in ('open','resolved','dismissed')),
      created_at timestamptz not null default now()
    );

    create index if not exists parse_review_queue_status_idx
      on parse_review_queue(status, created_at desc);

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
        'source_region','event_region','company_region','affected_region','market_region','mentioned_region'
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

    create table if not exists instrument_review_request (
      id uuid primary key default gen_random_uuid(),
      user_id uuid references app_user(id) on delete set null,
      query text not null check (char_length(query) between 1 and 64),
      context_screen text not null check (context_screen in (
        'HOLDING_ENTRY','TAX_LOT','BUILDER','IMPORT_RECONCILIATION','CSV_IMPORT'
      )),
      optional_notes text,
      request_ip_hash text,
      status text not null default 'queued' check (status in (
        'queued','in_review','resolved','closed','rejected'
      )),
      admin_notes text,
      resolved_by uuid references app_user(id) on delete set null,
      resolved_at timestamptz,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    );

    create index if not exists instrument_review_request_status_idx
      on instrument_review_request(status, created_at desc);
    create index if not exists instrument_review_request_query_idx
      on instrument_review_request(lower(query));
    create index if not exists instrument_review_request_pending_dedupe_idx
      on instrument_review_request(request_ip_hash, lower(query), context_screen, created_at desc)
      where status in ('queued', 'in_review');

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
          'pending_review','policy_approved','policy_approved_pending_live_test','blocked','unknown'
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
    create unique index if not exists market_data_quota_reservation_idempotency_idx
      on market_data_quota_reservation(
        provider_key, endpoint_key, partition_key, idempotency_key, window_seconds, window_start
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

    create table if not exists market_data_backup_restore_event (
      id uuid primary key default gen_random_uuid(),
      event_type text not null check (event_type in ('backup','restore','verify')),
      storage_uri text,
      content_hash text,
      started_at timestamptz not null default now(),
      completed_at timestamptz,
      status text not null default 'started' check (status in ('started','succeeded','failed')),
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
    """)

    ensure_final_columns_and_constraints()
    seed_reference_rows()
  end

  def down do
    :ok
  end

  defp ensure_final_columns_and_constraints do
    execute_many("""
    alter table app_user
      add column if not exists auth_provider text not null default 'password',
      add column if not exists external_subject text,
      add column if not exists last_login_at timestamptz,
      add column if not exists auth_metadata jsonb not null default '{}'::jsonb;

    alter table provider_usage_event
      add column if not exists endpoint_key text,
      add column if not exists partition_key text,
      add column if not exists status text not null default 'succeeded',
      add column if not exists error_class text,
      add column if not exists idempotency_key text,
      add column if not exists reserved_units jsonb not null default '{}'::jsonb,
      add column if not exists actual_units jsonb not null default '{}'::jsonb,
      add column if not exists retry_after_seconds int,
      add column if not exists next_allowed_at timestamptz,
      add column if not exists details jsonb not null default '{}'::jsonb;

    alter table source_document
      add column if not exists dedupe_key text,
      add column if not exists raw_expires_at timestamptz,
      add column if not exists updated_at timestamptz not null default now();

    alter table source_fact
      add column if not exists dedupe_key text;

    alter table llm_invocation
      alter column model_profile_id drop not null,
      alter column provider_key drop not null,
      add column if not exists actor_user_id uuid,
      add column if not exists session_id text,
      add column if not exists request_id text,
      add column if not exists job_id uuid,
      add column if not exists event_id text,
      add column if not exists cache_key text,
      add column if not exists denial_reason text,
      add column if not exists usage_estimate_json jsonb not null default '{}'::jsonb,
      add column if not exists reservation_id text;

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

    alter table job_concurrency_limit
      drop constraint if exists job_concurrency_limit_scope_type_check;
    alter table job_concurrency_limit
      add constraint job_concurrency_limit_scope_type_check
      check (scope_type in ('job_type','job_group','source','provider','global'));

    alter table llm_invocation
      drop constraint if exists llm_invocation_status_check;
    alter table llm_invocation
      add constraint llm_invocation_status_check
      check (status in (
        'succeeded','schema_failed','rejected','provider_failed','quota_failed','denied','budget_failed'
      ));
    """)
  end

  defp seed_reference_rows do
    execute_many("""
    insert into watched_people(canonical_name, category, aliases, tickers, sec_ciks, oge_names, notes)
    values
      (
        'Donald J. Trump', 'donald_trump',
        array['Donald Trump','Donald J Trump','President Trump'],
        '{}', '{}',
        array['Trump, Donald J.','Trump, Donald J'],
        'OGE Form 278e/278-T coverage only; does not imply private brokerage visibility.'
      ),
      (
        'Melania Trump', 'spouse',
        array['Melania Trump','Trump, Melania'],
        '{}', '{}', '{}',
        'Only tracked where included in Donald J. Trump OGE reports or independent public filings.'
      ),
      (
        'Donald Trump Jr.', 'adult_family',
        array['Donald Trump Jr','Donald J. Trump Jr.','Trump, Donald J. Jr.'],
        '{}', '{}', '{}',
        'SEC-only unless a public filing names the person or entity.'
      ),
      (
        'Eric Trump', 'adult_family',
        array['Eric Trump','Trump, Eric'],
        '{}', '{}', '{}',
        'SEC-only unless a public filing names the person or entity.'
      ),
      (
        'Ivanka Trump', 'adult_family',
        array['Ivanka Trump','Trump, Ivanka'],
        '{}', '{}', '{}',
        'SEC-only unless a public filing names the person or entity.'
      ),
      (
        'Jared Kushner', 'adult_family',
        array['Jared Kushner','Kushner, Jared'],
        '{}', '{}', '{}',
        'SEC-only unless a public filing names the person or entity.'
      ),
      (
        'Trump Media & Technology Group', 'related_entity',
        array['Trump Media','TMTG','Trump Media & Technology Group Corp.'],
        array['DJT'], array['0001849635'], '{}',
        'Related public-company entity; filings are sourced from SEC EDGAR.'
      )
    on conflict (canonical_name) do update
    set category = excluded.category,
        aliases = excluded.aliases,
        tickers = excluded.tickers,
        sec_ciks = excluded.sec_ciks,
        oge_names = excluded.oge_names,
        notes = excluded.notes;

    insert into job_concurrency_limit(scope_type, scope_key, max_running)
    values
      ('job_type', 'trump_disclosures_ingest', 1),
      ('job_group', 'news', 2),
      ('provider', 'google_news_rss', 1),
      ('provider', 'yahoo_finance_rss', 1),
      ('provider', 'company_ir', 1),
      ('provider', 'sec_edgar', 2),
      ('job_group', 'market_data', 1),
      ('provider', 'market_data', 1)
    on conflict (scope_type, scope_key)
    do update set max_running = excluded.max_running, enabled = true;

    insert into fact_type_registry(
      fact_type, display_name_en, display_name_ko, json_schema,
      allowed_predicates, public_allowed_default, requires_review
    )
    values
      (
        'news_document_metadata',
        'News document metadata',
        '뉴스 문서 메타데이터',
        '{"type":"object","required":["title","source_url","source_key","trust_tier"],"properties":{"title":{"type":"string"},"snippet":{"type":["string","null"]},"published_at":{"type":["string","null"]},"source_url":{"type":"string"},"source_key":{"type":"string"},"trust_tier":{"type":"string"}},"additionalProperties":false}'::jsonb,
        array['states'],
        false,
        true
      ),
      (
        'news_event_link',
        'News event link',
        '뉴스 이벤트 연결',
        '{"type":"object","required":["event_id","document_id","relationship"],"properties":{"event_id":{"type":"string"},"document_id":{"type":"string"},"relationship":{"type":"string"},"confidence":{"type":"number"}},"additionalProperties":false}'::jsonb,
        array['supports'],
        false,
        true
      ),
      (
        'news_entity_mention',
        'News entity mention',
        '뉴스 엔티티 언급',
        '{"type":"object","required":["entity_key","entity_type","relationship"],"properties":{"entity_key":{"type":"string"},"entity_type":{"type":"string"},"relationship":{"type":"string"},"confidence":{"type":"number"}},"additionalProperties":false}'::jsonb,
        array['mentions'],
        false,
        true
      ),
      (
        'news_market_relevance',
        'News market relevance',
        '뉴스 시장 관련성',
        '{"type":"object","required":["direction","confidence","reasoning"],"properties":{"direction":{"type":"string"},"confidence":{"type":"string"},"reasoning":{"type":"string"}},"additionalProperties":false}'::jsonb,
        array['suggests'],
        false,
        true
      )
    on conflict (fact_type) do update
    set json_schema = excluded.json_schema,
        allowed_predicates = excluded.allowed_predicates,
        active = true;

    insert into market_data_provider_capability (
      provider_key, endpoint_key, max_requests_per_minute, max_requests_per_day,
      cost_per_symbol, cost_per_request, max_output_points, supports_adjusted,
      supports_batch, history_depth_days, source_url, source_checked_at, notes
    )
    values
      ('twelve_data','daily_prices',6,700,1,0,5000,true,true,3650,'https://support.twelvedata.com/en/articles/5615854-credits','2026-06-07','Full rolling 3Y daily snapshots. Twelve Data credits are charged per symbol, not per returned row; batch reduces HTTP overhead only.'),
      ('alpha_vantage','daily_prices',null,17,1,1,100,true,false,100,'https://www.alphavantage.co/premium/','2026-05-25','Compact free endpoint is fallback only; avoid broad warmups. Caps are set near 70% of the documented free quota.'),
      ('fmp','daily_prices',null,175,1,1,5000,true,false,3650,'https://site.financialmodelingprep.com/pricing-plans','2026-05-25','Free endpoint is fallback and byte-budget constrained. Caps are set near 70% of the documented free quota.'),
      ('nasdaq_data_link','daily_prices',70,7000,1,1,5000,false,true,3650,'https://docs.data.nasdaq.com/docs/rate-limits-1','2026-05-25','Dataset access varies by table; not enabled for equities until dataset policy is reviewed.'),
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
      provider_key, endpoint_key, entitlement_status, live_test_status,
      internal_calculation_allowed, normalized_storage_allowed, raw_storage_allowed,
      raw_public_allowed, derived_public_allowed, retention_days, attribution_required,
      policy_reviewed_at, source_url, notes
    )
    values
      ('twelve_data','daily_prices','policy_approved_pending_live_test','untested',true,true,false,false,false,null,true,now(),'https://support.twelvedata.com/en/articles/5615854-credits','Store normalized full-window daily snapshots for calculations. Do not redistribute raw candles publicly.'),
      ('alpha_vantage','daily_prices','policy_approved_pending_live_test','untested',true,true,false,false,false,null,false,now(),'https://www.alphavantage.co/premium/','Store normalized fallback daily bars for internal calculations; do not redistribute raw quotes/candles publicly.'),
      ('fmp','daily_prices','policy_approved_pending_live_test','untested',true,true,false,false,false,null,false,now(),'https://site.financialmodelingprep.com/pricing-plans','Store normalized fallback daily bars for internal calculations; do not redistribute raw quotes/candles publicly.'),
      ('nasdaq_data_link','daily_prices','pending_review','untested',false,false,false,false,false,null,false,now(),'https://docs.data.nasdaq.com/docs/rate-limits-1','Rate limits are generous, but dataset entitlement and redistribution policy must be reviewed before use.'),
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
    """)
  end

  defp execute_many(sql) do
    sql
    |> String.split(~r/;\s*(?:\n|$)/, trim: true)
    |> Enum.each(fn statement ->
      execute(statement <> ";")
    end)
  end
end
