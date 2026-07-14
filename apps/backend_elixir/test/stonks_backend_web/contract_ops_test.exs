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

    assert scripts["test"] =~ "backend:check"
    assert scripts["test:all"] =~ "backend:test"
  end

  test "Mix exposes an explicit contract-only alias" do
    mix_exs = read_repo_file("apps/backend_elixir/mix.exs")

    assert mix_exs =~ ~s(preferred_envs: ["test.contract": :test])
    assert mix_exs =~ ~s("test.contract": ["test --only contract"])
  end

  test "compose uses api-elixir as the only backend runtime" do
    compose = read_repo_file("compose.yaml")
    compose_dev = read_repo_file("compose.dev.yaml")
    compose_prod = read_repo_file("infra/docker-compose.prod.yml")
    ci_workflow = read_repo_file(".github/workflows/ci.yml")
    deploy_script = read_repo_file("scripts/deploy_self_hosted_runner.sh")
    deploy_workflow = read_repo_file(".github/workflows/deploy.yml")

    assert compose =~ ~s(api-elixir:)
    assert compose =~ "depends_on:\n      - api-elixir"
    assert compose =~ "/api/public/health"
    refute compose =~ "\n  api:"
    refute compose =~ "\n  worker:"
    refute compose =~ "fetch-sandbox:"
    refute compose =~ "python-legacy"
    refute compose =~ "FETCH_SANDBOX_URL"
    refute compose =~ "dev-elixir-secret-key-base"

    assert compose_dev =~ ~s("8000:8000")
    refute compose_dev =~ "python-legacy"

    assert compose_prod =~ "api-elixir:"
    assert compose_prod =~ ~s(START_SCHEDULER: "true")
    assert compose_prod =~ ~s(WORKER_SCHEDULER_ENABLED: "true")
    assert compose_prod =~ ~s(OBAN_QUEUES_ENABLED: "true")
    refute compose_prod =~ "\n  api:"
    refute compose_prod =~ "\n  worker:"
    refute compose_prod =~ "fetch-sandbox:"
    refute compose_prod =~ "python-legacy"
    refute compose_prod =~ "depends_on:\n      - api"
    refute compose_prod =~ "FETCH_SANDBOX_URL"

    refute deploy_script =~ "publish_runtime_snapshots.py"
    refute deploy_script =~ " up -d postgres valkey fetch-sandbox"
    refute deploy_script =~ "python3 -c"
    refute deploy_script =~ "python-legacy"
    refute deploy_script =~ "stonks-radar-fetch-sandbox"

    assert deploy_script =~ "StonksBackend.Release.migrate()"
    assert deploy_script =~ "stonks-radar_published-snapshots"
    assert deploy_script =~ "elixir_recurring_scheduler_scheduled"
    assert deploy_script =~ "snapshot_refresh_jobs"
    assert deploy_script =~ "exec -T postgres"
    assert deploy_script =~ "</dev/null"
    assert deploy_script =~ "No snapshot_refresh jobs found"

    refute deploy_workflow =~ "publish_runtime_snapshots.py"
    refute deploy_workflow =~ " up -d postgres valkey fetch-sandbox"
    refute deploy_workflow =~ "python3 -c"
    refute deploy_workflow =~ "actions/setup-python"
    refute deploy_workflow =~ "setup-uv"
    refute deploy_workflow =~ "seed:snapshots"
    refute deploy_workflow =~ "test:all"
    refute deploy_workflow =~ "STONKS_SNAPSHOT_ENV_FILE"
    refute deploy_workflow =~ "python-legacy"
    refute deploy_workflow =~ "stonks-radar-fetch-sandbox"

    assert deploy_workflow =~ "StonksBackend.Release.migrate()"
    assert deploy_workflow =~ "stonks-radar_published-snapshots"
    assert deploy_workflow =~ "/tmp/stonks-origin-manifest.json"
    assert deploy_workflow =~ "/tmp/stonks-public-manifest.json"
    assert deploy_workflow =~ "origin_manifest_hash=$(sha256sum"
    assert deploy_workflow =~ "public_manifest_hash=$(sha256sum"
    assert deploy_workflow =~ "origin/public manifest hash matched"
    assert deploy_workflow =~ "Verify scheduler runtime"
    assert deploy_workflow =~ "diagnose_scheduler_only"
    assert deploy_workflow =~ "Inspect scheduler without mutation"
    assert deploy_workflow =~ "elixir_recurring_scheduler_scheduled"
    assert deploy_workflow =~ "snapshot_refresh_jobs"
    assert deploy_workflow =~ "current_snapshot_publication"
    assert deploy_workflow =~ "date_bin("
    assert deploy_workflow =~ "exec -T postgres"
    assert deploy_workflow =~ "</dev/null"
    assert deploy_workflow =~ "No snapshot_refresh job or current-window publication found"

    caddyfile = read_repo_file("infra/Caddyfile")
    assert caddyfile =~ "reverse_proxy {$API_UPSTREAM:api-elixir:8000}"

    refute ci_workflow =~ "actions/setup-python"
    refute ci_workflow =~ "setup-uv"
    refute ci_workflow =~ "api:test"
    refute ci_workflow =~ "api:compile"
    refute ci_workflow =~ "apps/api/Dockerfile"
    refute ci_workflow =~ "apps/worker/Dockerfile"
    refute ci_workflow =~ "apps/fetch-sandbox/Dockerfile"
    assert ci_workflow =~ "backend:check"
    assert ci_workflow =~ "apps/backend_elixir/Dockerfile"
    assert ci_workflow =~ "concurrency:"
    assert ci_workflow =~ "github.head_ref || github.ref_name"
    assert ci_workflow =~ "cancel-in-progress: true"
    assert ci_workflow =~ "timeout-minutes: 25"
  end

  test "production autodeploy waits for green main CI and Sonar before dispatching deploy" do
    auto_deploy_workflow = read_repo_file(".github/workflows/production-autodeploy.yml")

    assert auto_deploy_workflow =~ "workflow_run:"
    assert auto_deploy_workflow =~ "- ci"
    assert auto_deploy_workflow =~ "- sonarqube"
    assert auto_deploy_workflow =~ "head_branch == 'main'"
    assert auto_deploy_workflow =~ "github.event.workflow_run.event == 'push'"
    assert auto_deploy_workflow =~ ~s(ref: "heads/main")
    assert auto_deploy_workflow =~ ~s(workflow_id: "ci.yml")
    assert auto_deploy_workflow =~ ~s(workflow_id: "sonarqube.yml")
    assert auto_deploy_workflow =~ ~s(const deployWorkflow = "deploy.yml")
    assert auto_deploy_workflow =~ "listWorkflowRuns"
    assert auto_deploy_workflow =~ "createWorkflowDispatch"
    assert auto_deploy_workflow =~ ~s(runner: "github-hosted")
    assert auto_deploy_workflow =~ ~s(mode: "fast")
    assert auto_deploy_workflow =~ ~s(verify: "false")
    assert auto_deploy_workflow =~ "Deploy already exists"
    assert auto_deploy_workflow =~ "Skipping stale SHA"
    assert auto_deploy_workflow =~ "Waiting for deploy run to appear"
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

  test "retired Python runtime roots have no tracked files" do
    tracked =
      @repo_root
      |> git_lines(["ls-files", "apps/api", "apps/worker"])

    assert tracked == []

    cleanup_doc = read_repo_file("docs/legacy-python-runtime-cleanup.md")
    assert cleanup_doc =~ "apps/backend_elixir"
    assert cleanup_doc =~ "old Python `apps/api` and `apps/worker`"
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

  defp git_lines(cwd, args) do
    {output, 0} = System.cmd("git", args, cd: cwd, stderr_to_stdout: true)

    output
    |> String.split("\n", trim: true)
  end
end
