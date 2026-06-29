defmodule StonksBackend.Repo do
  use Ecto.Repo,
    otp_app: :stonks_backend,
    adapter: Ecto.Adapters.Postgres
end
