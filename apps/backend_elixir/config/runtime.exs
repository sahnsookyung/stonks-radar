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

database_url = System.get_env("DATABASE_URL", "postgres://frw:frw@localhost:5432/frw")
database_url = String.replace(database_url, "postgresql+psycopg://", "postgres://")
port = String.to_integer(System.get_env("PORT", "8000"))
pool_size = String.to_integer(System.get_env("POOL_SIZE", "10"))

secret_key_base =
  runtime_env.("PHX_SECRET_KEY_BASE", String.duplicate("runtime-secret-key-base", 4))

config :stonks_backend, :settings,
  app_env: app_env,
  app_base_url: System.get_env("APP_BASE_URL", "http://localhost:8000"),
  public_base_url: System.get_env("PUBLIC_BASE_URL", "http://localhost:5173"),
  dev_cors_origins: System.get_env("DEV_CORS_ORIGINS", "http://localhost:5173"),
  session_secret: runtime_env.("SESSION_SECRET", "dev-session-secret-change-me"),
  password_pepper: runtime_env.("PASSWORD_PEPPER", "dev-password-pepper-change-me"),
  admin_email: System.get_env("ADMIN_EMAIL", "owner@example.com"),
  admin_bootstrap_password: System.get_env("ADMIN_BOOTSTRAP_PASSWORD"),
  admin_totp_secret: System.get_env("ADMIN_TOTP_SECRET"),
  google_oauth_admin_enabled: System.get_env("GOOGLE_OAUTH_ADMIN_ENABLED", "false"),
  google_oauth_client_id: System.get_env("GOOGLE_OAUTH_CLIENT_ID"),
  google_oauth_client_secret: System.get_env("GOOGLE_OAUTH_CLIENT_SECRET"),
  google_oauth_redirect_path:
    System.get_env("GOOGLE_OAUTH_REDIRECT_PATH", "/api/auth/google/callback"),
  google_oauth_allowed_emails: System.get_env("GOOGLE_OAUTH_ALLOWED_EMAILS", ""),
  google_oauth_allowed_domains: System.get_env("GOOGLE_OAUTH_ALLOWED_DOMAINS", ""),
  yahoo_admin_enabled: System.get_env("YAHOO_ADMIN_ENABLED", "false"),
  published_snapshot_dir: System.get_env("PUBLISHED_SNAPSHOT_DIR", "apps/web/public/public"),
  snapshot_artifact_dir: System.get_env("SNAPSHOT_ARTIFACT_DIR", "artifacts/snapshots"),
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

if app_env in ["production", "prod"] do
  config :logger, level: :info
end
