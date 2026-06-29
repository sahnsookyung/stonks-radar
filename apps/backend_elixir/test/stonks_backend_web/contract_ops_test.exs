defmodule StonksBackendWeb.ContractOpsTest do
  use ExUnit.Case, async: true

  @moduletag :contract

  @repo_root Path.expand("../../../..", __DIR__)

  test "root scripts keep the Elixir backend optional and contract-gated" do
    scripts = package_scripts()

    assert scripts["backend:deps"] == "cd apps/backend_elixir && mix deps.get"
    assert scripts["backend:test:contract"] == "cd apps/backend_elixir && mix test.contract"

    assert scripts["backend:check"] ==
             "npm run backend:deps && npm run backend:compile && npm run backend:test:contract"

    refute scripts["test"] =~ "backend:"
    assert scripts["test:all"] =~ "backend:check"
  end

  test "Mix exposes an explicit contract-only alias" do
    mix_exs = read_repo_file("apps/backend_elixir/mix.exs")

    assert mix_exs =~ ~s(preferred_envs: ["test.contract": :test])
    assert mix_exs =~ ~s("test.contract": ["test --only contract"])
  end

  test "compose keeps api-elixir profile-isolated and healthchecked" do
    compose = read_repo_file("compose.yaml")
    compose_dev = read_repo_file("compose.dev.yaml")
    compose_prod = read_repo_file("infra/docker-compose.prod.yml")

    assert compose =~ ~s(profiles: ["elixir-backend"])
    assert compose =~ "/api/public/health"
    refute compose =~ "dev-elixir-secret-key-base"

    assert compose_dev =~ ~s("8001:8000")

    assert compose_prod =~ "api-elixir:"
    assert compose_prod =~ "depends_on:\n      - api"
    refute compose_prod =~ "depends_on:\n      - api-elixir"
  end

  test "production runtime cannot bypass required secrets by downgrading APP_ENV" do
    runtime = read_repo_file("apps/backend_elixir/config/runtime.exs")

    assert runtime =~
             "prod_runtime? = config_env() == :prod or String.downcase(app_env) in [\"production\", \"prod\"]"

    assert runtime =~ "runtime_env.(\"PHX_SECRET_KEY_BASE\""
    assert runtime =~ "runtime_env.(\"SESSION_SECRET\""
    assert runtime =~ "runtime_env.(\"PASSWORD_PEPPER\""
    assert runtime =~ "must be set for the Elixir backend in production"
  end

  test "generated Elixir artifacts stay out of git" do
    gitignore = read_repo_file(".gitignore")

    assert gitignore =~ "apps/backend_elixir/_build/"
    assert gitignore =~ "apps/backend_elixir/deps/"
  end

  test "fixture loader stays inside the sanitized contract fixture tree" do
    assert_raise ArgumentError, ~r/contract fixtures must stay under/, fn ->
      StonksBackendWeb.ContractCase.load_fixture("../contract_case.ex")
    end
  end

  defp package_scripts do
    "package.json"
    |> read_repo_file()
    |> Jason.decode!()
    |> Map.fetch!("scripts")
  end

  defp read_repo_file(relative_path) do
    @repo_root
    |> Path.join(relative_path)
    |> File.read!()
  end
end
