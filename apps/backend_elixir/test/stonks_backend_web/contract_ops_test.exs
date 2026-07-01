defmodule StonksBackendWeb.ContractOpsTest do
  use ExUnit.Case, async: true

  @moduletag :contract

  @repo_root Path.expand("../../../..", __DIR__)

  test "root scripts keep the Elixir backend contract-gated" do
    scripts = package_scripts()

    assert scripts["backend:deps"] == "cd apps/backend_elixir && mix deps.get"
    assert scripts["backend:test:contract"] == "cd apps/backend_elixir && mix test.contract"

    assert scripts["backend:check"] ==
             "npm run backend:deps && npm run backend:compile && npm run backend:test:contract"

    assert scripts["test:all"] =~ "backend:check"
  end

  test "Mix exposes an explicit contract-only alias" do
    mix_exs = read_repo_file("apps/backend_elixir/mix.exs")

    assert mix_exs =~ ~s(preferred_envs: ["test.contract": :test])
    assert mix_exs =~ ~s("test.contract": ["test --only contract"])
  end

  test "compose uses api-elixir as the default backend and keeps Python runtime profile-only" do
    compose = read_repo_file("compose.yaml")
    compose_dev = read_repo_file("compose.dev.yaml")
    compose_prod = read_repo_file("infra/docker-compose.prod.yml")
    deploy_script = read_repo_file("scripts/deploy_self_hosted_runner.sh")
    deploy_workflow = read_repo_file(".github/workflows/deploy.yml")

    assert compose =~ ~s(api-elixir:)
    assert compose =~ ~s(profiles: ["python-legacy"])
    assert compose =~ "depends_on:\n      - api-elixir"
    assert compose =~ "/api/public/health"
    assert compose =~ "fetch-sandbox:"
    assert compose =~ "dockerfile: apps/fetch-sandbox/Dockerfile"
    assert compose =~ "fetch-sandbox:\n    profiles: [\"python-legacy\"]"
    refute compose =~ "FETCH_SANDBOX_URL"
    refute compose =~ "fetch-sandbox:\n        condition: service_healthy"
    refute compose =~ "dev-elixir-secret-key-base"

    assert compose_dev =~ ~s("8000:8000")

    assert compose_prod =~ "api-elixir:"
    assert compose_prod =~ "fetch-sandbox:"
    assert compose_prod =~ "fetch-sandbox:\n    profiles: [\"python-legacy\"]"
    refute compose_prod =~ "depends_on:\n      - api"
    refute compose_prod =~ "FETCH_SANDBOX_URL"

    refute deploy_script =~ "python-legacy"
    refute deploy_script =~ "publish_runtime_snapshots.py"
    refute deploy_script =~ " up -d postgres valkey fetch-sandbox"
    refute deploy_script =~ "python3 -c"
    assert deploy_script =~ "StonksBackend.Release.migrate()"
    assert deploy_script =~ "stonks-radar_published-snapshots"

    refute deploy_workflow =~ "publish_runtime_snapshots.py"
    refute deploy_workflow =~ " up -d postgres valkey fetch-sandbox"
    refute deploy_workflow =~ "python3 -c"
    assert deploy_workflow =~ "StonksBackend.Release.migrate()"
    assert deploy_workflow =~ "stonks-radar_published-snapshots"

    caddyfile = read_repo_file("infra/Caddyfile")
    assert caddyfile =~ "reverse_proxy {$API_UPSTREAM:api-elixir:8000}"
  end

  test "production runtime cannot bypass required secrets by downgrading APP_ENV" do
    runtime = read_repo_file("apps/backend_elixir/config/runtime.exs")

    assert runtime =~
             "prod_runtime? = config_env() == :prod or String.downcase(app_env) in [\"production\", \"prod\"]"

    assert runtime =~ "session_secret = runtime_env.(\"SESSION_SECRET\""
    assert runtime =~ "case System.get_env(\"PHX_SECRET_KEY_BASE\")"
    assert runtime =~ "session_secret: session_secret"
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
