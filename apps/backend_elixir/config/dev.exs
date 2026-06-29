import Config

config :stonks_backend, StonksBackendWeb.Endpoint,
  http: [ip: {0, 0, 0, 0}, port: String.to_integer(System.get_env("PORT", "8000"))],
  check_origin: false,
  code_reloader: false,
  debug_errors: true,
  secret_key_base: String.duplicate("dev-secret-key-base", 4),
  server: true

config :logger, :console, format: "[$level] $message\n"
