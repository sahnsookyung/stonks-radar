import Config

default_app_env = if config_env() == :prod, do: "production", else: "development"
app_env = System.get_env("APP_ENV", default_app_env)
prod_runtime? = config_env() == :prod or String.downcase(app_env) in ["production", "prod"]

runtime_env = fn name, dev_default ->
  value = System.get_env(name)

  cond do
    is_binary(value) and String.trim(value) != "" ->
      value

    prod_runtime? ->
      raise "#{name} must be set for the Elixir backend in production"

    true ->
      dev_default
  end
end

truthy_env = fn name, default ->
  value = System.get_env(name, default)
  String.downcase(String.trim(to_string(value))) in ["1", "true", "yes", "on"]
end

database_url =
  if config_env() == :test do
    System.get_env(
      "TEST_DATABASE_URL",
      System.get_env("DATABASE_URL", "postgres://frw:frw@localhost:5432/frw_test")
    )
  else
    System.get_env("DATABASE_URL", "postgres://frw:frw@localhost:5432/frw")
  end

database_url = String.replace(database_url, "postgresql+psycopg://", "postgres://")
port = String.to_integer(System.get_env("PORT", "8000"))
pool_size = String.to_integer(System.get_env("POOL_SIZE", "10"))

session_secret = runtime_env.("SESSION_SECRET", "dev-session-secret-change-me")

secret_key_base =
  case System.get_env("PHX_SECRET_KEY_BASE") do
    value when is_binary(value) ->
      trimmed = String.trim(value)

      if trimmed == "" do
        session_secret
      else
        trimmed
      end

    _ ->
      session_secret
  end

config :stonks_backend, :settings,
  app_env: app_env,
  app_base_url: System.get_env("APP_BASE_URL", "http://localhost:8000"),
  public_base_url: System.get_env("PUBLIC_BASE_URL", "http://localhost:5173"),
  dev_cors_origins: System.get_env("DEV_CORS_ORIGINS", "http://localhost:5173"),
  session_secret: session_secret,
  password_pepper: runtime_env.("PASSWORD_PEPPER", "dev-password-pepper-change-me"),
  admin_email: System.get_env("ADMIN_EMAIL", "owner@example.com"),
  admin_bootstrap_password: System.get_env("ADMIN_BOOTSTRAP_PASSWORD"),
  admin_totp_secret: System.get_env("ADMIN_TOTP_SECRET"),
  google_oauth_admin_enabled: System.get_env("GOOGLE_OAUTH_ADMIN_ENABLED", "false"),
  google_oauth_client_id: System.get_env("GOOGLE_OAUTH_CLIENT_ID"),
  google_oauth_client_secret: System.get_env("GOOGLE_OAUTH_CLIENT_SECRET"),
  google_oauth_redirect_path:
    System.get_env("GOOGLE_OAUTH_REDIRECT_PATH", "/api/auth/google/callback"),
  google_oauth_token_url:
    System.get_env("GOOGLE_OAUTH_TOKEN_URL", "https://oauth2.googleapis.com/token"),
  google_oauth_tokeninfo_url:
    System.get_env("GOOGLE_OAUTH_TOKENINFO_URL", "https://oauth2.googleapis.com/tokeninfo"),
  google_oauth_allowed_emails: System.get_env("GOOGLE_OAUTH_ALLOWED_EMAILS", ""),
  google_oauth_allowed_domains: System.get_env("GOOGLE_OAUTH_ALLOWED_DOMAINS", ""),
  yahoo_admin_enabled: System.get_env("YAHOO_ADMIN_ENABLED", "false"),
  published_snapshot_dir: System.get_env("PUBLISHED_SNAPSHOT_DIR", "apps/web/public/public"),
  snapshot_artifact_dir: System.get_env("SNAPSHOT_ARTIFACT_DIR", "artifacts/snapshots"),
  snapshot_schema_dir: System.get_env("SNAPSHOT_SCHEMA_DIR"),
  worker_scheduler_enabled: System.get_env("WORKER_SCHEDULER_ENABLED", "true"),
  worker_scheduler_tick_seconds: System.get_env("WORKER_SCHEDULER_TICK_SECONDS", "60"),
  snapshot_refresh_seconds: System.get_env("SNAPSHOT_REFRESH_SECONDS", "900"),
  news_rss_enabled: System.get_env("NEWS_RSS_ENABLED", "true"),
  news_gdelt_enabled: System.get_env("NEWS_GDELT_ENABLED", "false"),
  news_public_health_enabled: System.get_env("NEWS_PUBLIC_HEALTH_ENABLED", "true"),
  news_source_refresh_seconds: System.get_env("NEWS_SOURCE_REFRESH_SECONDS", "900"),
  news_publication_interval_seconds: System.get_env("NEWS_PUBLICATION_INTERVAL_SECONDS", "300"),
  news_pipeline_runtime_enabled: System.get_env("NEWS_PIPELINE_RUNTIME_ENABLED", "true"),
  news_max_documents_per_source_per_run:
    System.get_env("NEWS_MAX_DOCUMENTS_PER_SOURCE_PER_RUN", "100"),
  news_processing_batch_limit: System.get_env("NEWS_PROCESSING_BATCH_LIMIT", "500"),
  news_page_read_batch_limit: System.get_env("NEWS_PAGE_READ_BATCH_LIMIT", "25"),
  news_breaking_window_hours: System.get_env("NEWS_BREAKING_WINDOW_HOURS", "24"),
  news_analysis_window_days: System.get_env("NEWS_ANALYSIS_WINDOW_DAYS", "7"),
  news_search_window_days: System.get_env("NEWS_SEARCH_WINDOW_DAYS", "30"),
  news_discovery_retention_days: System.get_env("NEWS_DISCOVERY_RETENTION_DAYS", "30"),
  news_metadata_retention_days: System.get_env("NEWS_METADATA_RETENTION_DAYS", "90"),
  news_event_retention_days: System.get_env("NEWS_EVENT_RETENTION_DAYS", "365"),
  source_fetch_timeout_seconds: System.get_env("SOURCE_FETCH_TIMEOUT_SECONDS", "20"),
  source_fetch_max_bytes: System.get_env("SOURCE_FETCH_MAX_BYTES", "5000000"),
  sec_user_agent:
    System.get_env("SEC_USER_AGENT", "StonksRadar/1.0 research contact=admin@example.com"),
  gdelt_doc_cycle_budget: System.get_env("GDELT_DOC_CYCLE_BUDGET", "10"),
  gdelt_doc_max_records: System.get_env("GDELT_DOC_MAX_RECORDS", "250"),
  gdelt_doc_query_pack: System.get_env("GDELT_DOC_QUERY_PACK", "market_watch"),
  gdelt_doc_timespan: System.get_env("GDELT_DOC_TIMESPAN", "36h"),
  gdelt_doc_backfill_timespan: System.get_env("GDELT_DOC_BACKFILL_TIMESPAN", "7d"),
  gdelt_doc_api_url:
    System.get_env("GDELT_DOC_API_URL", "https://api.gdeltproject.org/api/v2/doc/doc"),
  gdelt_runtime_fetch_enabled:
    System.get_env(
      "GDELT_RUNTIME_FETCH_ENABLED",
      if(config_env() == :test, do: "false", else: "true")
    ),
  gdelt_title_fetch_limit: System.get_env("GDELT_TITLE_FETCH_LIMIT", "20"),
  gdelt_title_fetch_timeout_seconds: System.get_env("GDELT_TITLE_FETCH_TIMEOUT_SECONDS", "8"),
  gdelt_title_fetch_max_bytes: System.get_env("GDELT_TITLE_FETCH_MAX_BYTES", "131072"),
  gdelt_title_per_host_interval_seconds:
    System.get_env("GDELT_TITLE_PER_HOST_INTERVAL_SECONDS", "2"),
  gdelt_bulk_max_documents: System.get_env("GDELT_BULK_MAX_DOCUMENTS", "500"),
  gdelt_bulk_runtime_enabled: System.get_env("GDELT_BULK_RUNTIME_ENABLED", "false"),
  news_ticker_watchlist_path: System.get_env("NEWS_TICKER_WATCHLIST_PATH"),
  trump_disclosure_sec_poll_seconds: System.get_env("TRUMP_DISCLOSURE_SEC_POLL_SECONDS", "1800"),
  trump_disclosure_oge_poll_seconds: System.get_env("TRUMP_DISCLOSURE_OGE_POLL_SECONDS", "86400"),
  trump_disclosure_oge_pdf_limit: System.get_env("TRUMP_DISCLOSURE_OGE_PDF_LIMIT", "12"),
  market_data_scheduled_refresh_enabled:
    System.get_env("MARKET_DATA_SCHEDULED_REFRESH_ENABLED", "true"),
  market_data_provider_order:
    System.get_env("MARKET_DATA_PROVIDER_ORDER", "twelve_data,alpha_vantage,fmp"),
  market_data_api_key: System.get_env("MARKET_DATA_API_KEY"),
  twelve_data_api_key: System.get_env("TWELVE_DATA_API_KEY"),
  alpha_vantage_api_key: System.get_env("ALPHA_VANTAGE_API_KEY"),
  fmp_api_key: System.get_env("FMP_API_KEY"),
  finnhub_api_key: System.get_env("FINNHUB_API_KEY"),
  instrument_provider_search_enabled:
    System.get_env("INSTRUMENT_PROVIDER_SEARCH_ENABLED", "true"),
  instrument_public_symbol_lookup_enabled:
    System.get_env("INSTRUMENT_PUBLIC_SYMBOL_LOOKUP_ENABLED", "true"),
  instrument_public_symbol_directory_cache_seconds:
    System.get_env("INSTRUMENT_PUBLIC_SYMBOL_DIRECTORY_CACHE_SECONDS", "86400"),
  instrument_nasdaq_listed_url:
    System.get_env(
      "INSTRUMENT_NASDAQ_LISTED_URL",
      "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
    ),
  instrument_nasdaq_other_listed_url:
    System.get_env(
      "INSTRUMENT_NASDAQ_OTHER_LISTED_URL",
      "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
    ),
  instrument_provider_search_cache_seconds:
    System.get_env("INSTRUMENT_PROVIDER_SEARCH_CACHE_SECONDS", "900"),
  instrument_provider_search_limit: System.get_env("INSTRUMENT_PROVIDER_SEARCH_LIMIT", "8"),
  instrument_provider_search_timeout_seconds:
    System.get_env("INSTRUMENT_PROVIDER_SEARCH_TIMEOUT_SECONDS", "8"),
  market_data_public_display_allowlist:
    System.get_env("MARKET_DATA_PUBLIC_DISPLAY_ALLOWLIST", ""),
  market_data_fetch_timeout_seconds: System.get_env("MARKET_DATA_FETCH_TIMEOUT_SECONDS", "20"),
  market_data_refresh_symbols: System.get_env("MARKET_DATA_REFRESH_SYMBOLS", ""),
  market_data_refresh_spread_minutes: System.get_env("MARKET_DATA_REFRESH_SPREAD_MINUTES", "240"),
  market_data_snapshot_window_days: System.get_env("MARKET_DATA_SNAPSHOT_WINDOW_DAYS", "1095"),
  market_data_refresh_after_close_minutes:
    System.get_env("MARKET_DATA_REFRESH_AFTER_CLOSE_MINUTES", "45"),
  shorts_ingestion_enabled: System.get_env("SHORTS_INGESTION_ENABLED", "true"),
  yield_curve_history_enabled: System.get_env("YIELD_CURVE_HISTORY_ENABLED", "true"),
  yield_curve_history_months: System.get_env("YIELD_CURVE_HISTORY_MONTHS", "24"),
  yield_curve_fetch_timeout_seconds: System.get_env("YIELD_CURVE_FETCH_TIMEOUT_SECONDS", "15"),
  instrument_universe_refresh_seconds:
    System.get_env("INSTRUMENT_UNIVERSE_REFRESH_SECONDS", "14400"),
  news_email_webhook_secret: System.get_env("NEWS_EMAIL_WEBHOOK_SECRET"),
  news_email_signature_max_skew_seconds:
    System.get_env("NEWS_EMAIL_SIGNATURE_MAX_SKEW_SECONDS", "300")

config :stonks_backend, StonksBackend.Repo,
  url: database_url,
  pool_size: pool_size

config :stonks_backend, StonksBackendWeb.Endpoint,
  http: [ip: {0, 0, 0, 0}, port: port],
  secret_key_base: secret_key_base,
  check_origin: false

default_start_scheduler = if config_env() == :test, do: "false", else: "true"
config :stonks_backend, :start_scheduler, truthy_env.("START_SCHEDULER", default_start_scheduler)

unless truthy_env.("OBAN_QUEUES_ENABLED", "true") do
  config :stonks_backend, Oban,
    queues: false,
    plugins: false
end

if app_env in ["production", "prod"] do
  config :logger, level: :info
end
