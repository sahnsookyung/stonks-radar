defmodule StonksBackend.Release do
  @moduledoc "Release-time operational tasks."

  @app :stonks_backend

  def migrate do
    load_app()

    for repo <- repos() do
      {:ok, _repo, _migrations} =
        Ecto.Migrator.with_repo(repo, fn repo ->
          Ecto.Migrator.run(repo, :up, all: true)
        end)
    end

    :ok
  end

  defp repos do
    Application.fetch_env!(@app, :ecto_repos)
  end

  defp load_app do
    Application.load(@app)
  end
end
