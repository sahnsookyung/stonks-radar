import Config

config :stonks_backend,
  ecto_repos: [StonksBackend.Repo],
  generators: [timestamp_type: :utc_datetime_usec]

config :stonks_backend, StonksBackend.Repo,
  migration_primary_key: [name: :id, type: :binary_id],
  migration_foreign_key: [type: :binary_id]

config :stonks_backend, StonksBackendWeb.Endpoint,
  adapter: Bandit.PhoenixAdapter,
  url: [host: "localhost"],
  render_errors: [
    formats: [json: StonksBackendWeb.ErrorJSON],
    layout: false
  ],
  pubsub_server: StonksBackend.PubSub,
  live_view: [signing_salt: "stonks-backend"]

config :stonks_backend, Oban,
  repo: StonksBackend.Repo,
  queues: [
    snapshots: 1,
    market_data: 1,
    news: 2,
    instruments: 1,
    disclosures: 1,
    maintenance: 1,
    default: 5
  ],
  plugins: [
    Oban.Plugins.Pruner
  ]

config :phoenix, :json_library, Jason
config :swoosh, :api_client, false

import_config "#{config_env()}.exs"
