defmodule StonksBackend.MixProject do
  use Mix.Project

  def project do
    [
      app: :stonks_backend,
      version: "0.1.0",
      elixir: "~> 1.20",
      elixirc_paths: elixirc_paths(Mix.env()),
      start_permanent: Mix.env() == :prod,
      aliases: aliases(),
      deps: deps()
    ]
  end

  def cli do
    [preferred_envs: ["test.contract": :test]]
  end

  def application do
    [
      mod: {StonksBackend.Application, []},
      extra_applications: [:logger, :runtime_tools, :crypto]
    ]
  end

  defp elixirc_paths(:test), do: ["lib", "test/support"]
  defp elixirc_paths(_env), do: ["lib"]

  defp deps do
    [
      {:phoenix, "~> 1.8"},
      {:phoenix_ecto, "~> 4.6"},
      {:ecto_sql, "~> 3.13"},
      {:postgrex, ">= 0.0.0"},
      {:jason, "~> 1.4"},
      {:bandit, "~> 1.7"},
      {:oban, "~> 2.20"},
      {:req, "~> 0.5"},
      {:finch, "~> 0.19"},
      {:argon2_elixir, "~> 4.0"},
      {:nimble_totp, "~> 1.0"},
      {:assent, "~> 0.3"},
      {:hammer, "~> 7.0"},
      {:floki, "~> 0.37"},
      {:nimble_csv, "~> 1.2"},
      {:sweet_xml, "~> 0.7"},
      {:swoosh, "~> 1.17"},
      {:jsv, "~> 0.9"},
      {:broadway, "~> 1.2"},
      {:telemetry_metrics, "~> 1.0"},
      {:opentelemetry_phoenix, "~> 1.2"},
      {:opentelemetry_ecto, "~> 1.2"},
      {:mox, "~> 1.2", only: :test},
      {:bypass, "~> 2.1", only: :test},
      {:stream_data, "~> 1.1", only: :test}
    ]
  end

  defp aliases do
    [
      setup: ["deps.get"],
      "ecto.setup": ["ecto.create", "ecto.migrate"],
      "ecto.reset": ["ecto.drop", "ecto.setup"],
      test: ["test"],
      "test.contract": ["test --only contract"]
    ]
  end
end
