import Config

database_url = System.get_env("TEST_DATABASE_URL", "postgres://frw:frw@localhost:5432/frw_test")

config :stonks_backend, StonksBackend.Repo,
  url: database_url,
  pool: Ecto.Adapters.SQL.Sandbox,
  pool_size: 4

config :stonks_backend, StonksBackendWeb.Endpoint,
  http: [ip: {127, 0, 0, 1}, port: 4002],
  secret_key_base: String.duplicate("test-secret-key-base", 4),
  server: false

config :stonks_backend, Oban, testing: :manual, queues: false, plugins: false
config :stonks_backend, :start_repo, false

config :logger, level: :warning
