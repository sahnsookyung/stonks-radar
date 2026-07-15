#!/usr/bin/env bash
set -euo pipefail

env_file="${1:-/tmp/stonks-production.env}"
source_dir="${GITHUB_WORKSPACE:-$(pwd)}"
deploy_dir="${STONKS_DEPLOY_DIR:-/opt/stonks-radar}"
deploy_mode="${STONKS_DEPLOY_MODE:-fast}"
api_image="${STONKS_API_IMAGE:-}"
ghcr_actor="${STONKS_GHCR_ACTOR:-${GITHUB_ACTOR:-}}"
ghcr_token="${STONKS_GHCR_TOKEN:-${GITHUB_TOKEN:-}}"
compose_files=(-f compose.yaml -f infra/docker-compose.prod.yml)
summary_started=0

if [[ "$deploy_mode" != "fast" && "$deploy_mode" != "clean" ]]; then
  echo "STONKS_DEPLOY_MODE must be fast or clean, got: $deploy_mode" >&2
  exit 1
fi

compose() {
  if [[ "$deploy_mode" == "fast" && -n "$api_image" ]]; then
    API_ELIXIR_IMAGE="$api_image" docker compose "${compose_files[@]}" "$@"
  else
    docker compose "${compose_files[@]}" "$@"
  fi
}

record_phase() {
  local name="$1"
  local duration="$2"

  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    if [[ "$summary_started" != "1" ]]; then
      {
        echo "### Deploy phase timings"
        echo
        echo "| Phase | Duration |"
        echo "| --- | ---: |"
      } >> "$GITHUB_STEP_SUMMARY"
      summary_started=1
    fi

    echo "| $name | ${duration}s |" >> "$GITHUB_STEP_SUMMARY"
  fi
}

run_phase() {
  local name="$1"
  shift
  local start
  local duration

  echo "==> $name"
  start="$(date +%s)"
  "$@"
  duration="$(( $(date +%s) - start ))"
  record_phase "$name" "$duration"
  echo "<== $name completed in ${duration}s"
}

if [[ ! -s "$env_file" ]]; then
  echo "Production env file is missing or empty: $env_file" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required on the self-hosted runner" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose v2 is required on the self-hosted runner" >&2
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync is required on the self-hosted runner" >&2
  exit 1
fi

sudo_cmd=()
if [[ ! -d "$deploy_dir" || ! -w "$deploy_dir" ]]; then
  if command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
    sudo_cmd=(sudo -n)
  else
    echo "Runner user cannot write $deploy_dir and passwordless sudo is unavailable" >&2
    exit 1
  fi
fi

prepare_host() {
  if [[ ! -d "$deploy_dir" ]]; then
    "${sudo_cmd[@]}" mkdir -p "$deploy_dir"
    "${sudo_cmd[@]}" chown "$(id -u):$(id -g)" "$deploy_dir"
  elif [[ ! -w "$deploy_dir" ]]; then
    "${sudo_cmd[@]}" chown -R "$(id -u):$(id -g)" "$deploy_dir"
  fi

  if [[ "$deploy_mode" == "clean" ]]; then
    if [[ -f "$deploy_dir/compose.yaml" ]]; then
      (cd "$deploy_dir" && compose down --remove-orphans || true)
    fi

    docker container prune -f || true
    docker builder prune -af || true
    docker image prune -af || true

    rm -rf \
      "$deploy_dir/node_modules" \
      "$deploy_dir/apps/web/node_modules" \
      "$deploy_dir/apps/web/.generated-public" \
      "$deploy_dir/apps/backend_elixir/deps" \
      "$deploy_dir/apps/backend_elixir/_build" \
      "$deploy_dir/apps/backend_elixir/.elixir_ls"

    if [[ "$(cd "$source_dir" && pwd -P)" != "$(cd "$deploy_dir" && pwd -P)" ]]; then
      rm -rf "$deploy_dir/apps/web/dist"
    fi

    for volume in stonks-radar_snapshot-artifacts stonks-radar_published-snapshots; do
      mountpoint="$(docker volume inspect "$volume" --format "{{ .Mountpoint }}" 2>/dev/null || true)"
      if [[ -n "$mountpoint" && -d "$mountpoint" ]]; then
        "${sudo_cmd[@]}" find "$mountpoint" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
      fi
    done

    docker image rm -f stonks-radar-api-elixir || true
  else
    docker container prune -f || true
  fi

  df -h / /opt /tmp || true
}

sync_release() {
  if [[ "$(cd "$source_dir" && pwd -P)" != "$(cd "$deploy_dir" && pwd -P)" ]]; then
    rsync -az --delete \
      --exclude '.git' \
      --exclude '.gitnexus' \
      --exclude '.deploy-old-assets' \
      --exclude '.secrets' \
      --exclude '.env' \
      --exclude '.env.*' \
      --exclude 'node_modules' \
      --exclude 'apps/backend_elixir/deps' \
      --exclude 'apps/backend_elixir/_build' \
      --exclude 'apps/backend_elixir/.elixir_ls' \
      --exclude 'artifacts' \
      --exclude 'web-deploy-artifact' \
      --exclude 'playwright-report' \
      --exclude 'test-results' \
      "$source_dir/" "$deploy_dir/"
  fi
}

install_env() {
  mkdir -p "$deploy_dir/apps/web/dist/assets" "$deploy_dir/.secrets"
  install -m 600 "$env_file" "$deploy_dir/.env"
  install -m 600 "$env_file" "$deploy_dir/.secrets/stonks-radar.production.env"
}

build_api() {
  cd "$deploy_dir"

  if [[ "$deploy_mode" == "fast" && -n "$api_image" ]]; then
    if [[ -n "$ghcr_actor" && -n "$ghcr_token" ]]; then
      printf '%s\n' "$ghcr_token" | docker login ghcr.io -u "$ghcr_actor" --password-stdin
    fi

    docker pull "$api_image"
  else
    COMPOSE_PARALLEL_LIMIT=1 DOCKER_BUILDKIT=1 compose build api-elixir
  fi
}

migrate() {
  cd "$deploy_dir"
  local migration_complete=0

  restore_api_on_migration_failure() {
    if [[ "$migration_complete" != "1" ]]; then
      COMPOSE_PARALLEL_LIMIT=1 compose up -d api-elixir caddy || true
    fi
  }

  trap restore_api_on_migration_failure RETURN
  compose stop api-elixir || true
  COMPOSE_PARALLEL_LIMIT=1 compose up -d postgres valkey
  compose run --rm --no-deps api-elixir \
    /app/bin/stonks_backend eval 'StonksBackend.Release.migrate()'
  migration_complete=1
  trap - RETURN
}

start_services() {
  cd "$deploy_dir"
  COMPOSE_PARALLEL_LIMIT=1 compose up -d api-elixir caddy
  df -h / /opt /tmp || true
}

verify_scheduler_runtime() {
  local attempt flags logs

  cd "$deploy_dir"
  flags="$(
    compose exec -T api-elixir sh -lc \
      'printf "%s %s %s" "$START_SCHEDULER" "$WORKER_SCHEDULER_ENABLED" "$OBAN_QUEUES_ENABLED"' \
      </dev/null
  )"
  [[ "$flags" == "true true true" ]] || {
    echo "Production scheduler flags are not enabled: $flags" >&2
    return 1
  }

  for attempt in 1 2 3 4 5 6; do
    logs="$(compose logs --since 5m --no-color api-elixir 2>&1 || true)"
    if grep -q "elixir_recurring_scheduler_failed" <<<"$logs"; then
      grep "elixir_recurring_scheduler_failed" <<<"$logs" >&2
      return 1
    fi
    if grep -q "elixir_recurring_scheduler_scheduled" <<<"$logs"; then
      grep "elixir_recurring_scheduler_scheduled" <<<"$logs" | tail -1
      break
    fi
    if [[ "$attempt" == "6" ]]; then
      echo "Production scheduler did not emit a scheduling heartbeat within 30 seconds" >&2
      return 1
    fi
    sleep 5
  done

  snapshot_jobs="$(
    compose exec -T postgres sh -lc '
      psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "|" -c "
        select id::text, state, attempt::text, max_attempts::text,
               inserted_at::text, coalesce(attempted_at::text, \$\$-\$\$),
               coalesce(completed_at::text, \$\$-\$\$),
               replace(left(coalesce(
                 errors[array_upper(errors, 1)] ->> \$\$message\$\$,
                 errors[array_upper(errors, 1)] ->> \$\$error\$\$,
                 \$\$\$\$
               ), 500), chr(10), \$\$ \$\$)
        from oban_jobs
        where args ->> \$\$job_type\$\$ = \$\$snapshot_refresh\$\$
        order by inserted_at desc
        limit 5
      "
    ' </dev/null
  )"
  [[ -n "$snapshot_jobs" ]] || {
    echo "No snapshot_refresh jobs found" >&2
    return 1
  }
  printf 'snapshot_refresh_jobs\n%s\n' "$snapshot_jobs"
}

refresh_snapshots() {
  docker run --rm -v stonks-radar_published-snapshots:/dest alpine:3.24 chmod -R a+rwX /dest

  cd "$deploy_dir"
  compose run --rm --no-deps api-elixir \
    env START_SCHEDULER=false OBAN_QUEUES_ENABLED=false \
    /app/bin/stonks_backend eval '
      {:ok, _} = Application.ensure_all_started(:stonks_backend)

      owner = "deploy:" <> Ecto.UUID.generate()

      acquire_lock = fn acquire_lock, attempts ->
        cond do
          StonksBackend.Jobs.RuntimeLock.acquire("global", "snapshots", owner, 900) ->
            :ok

          attempts > 1 ->
            Process.sleep(5_000)
            acquire_lock.(acquire_lock, attempts - 1)

          true ->
            {:error, :timeout}
        end
      end

      case acquire_lock.(acquire_lock, 60) do
        :ok ->
          try do
            case StonksBackend.Snapshots.refresh(%{"requested_by" => "deploy", "mode" => "db_generated_publish"}) do
              {:ok, result} -> IO.inspect(result, label: "published_snapshot")
              {:error, reason} -> raise "snapshot refresh failed: #{inspect(reason)}"
            end
          after
            StonksBackend.Jobs.RuntimeLock.release("global", "snapshots", owner)
          end

        {:error, :timeout} ->
          raise "snapshot refresh lock timed out"
      end
    '
}

smoke() {
  local public_hostname

  cd "$deploy_dir"
  public_hostname="$(awk -F= '$1=="PUBLIC_HOSTNAME"{print $2}' .env)"
  public_hostname="$(printf '%s' "$public_hostname" | tr -d '[:space:]"')"
  public_hostname="$(printf '%s' "$public_hostname" | tr -d "'")"
  if [[ -z "$public_hostname" ]]; then
    echo "PUBLIC_HOSTNAME is missing from production env" >&2
    exit 1
  fi

  curl -fsS --resolve "$public_hostname:443:127.0.0.1" "https://$public_hostname/" >/dev/null
  curl -fsS --resolve "$public_hostname:443:127.0.0.1" "https://$public_hostname/api/public/health" \
    | grep -q '"status":"ok"'
  [[ "$(curl -sS -o /dev/null -w '%{http_code}' --resolve "$public_hostname:443:127.0.0.1" "https://$public_hostname/api/public/status")" == "404" ]]
  [[ "$(curl -sS -o /dev/null -w '%{http_code}' --resolve "$public_hostname:443:127.0.0.1" "https://$public_hostname/api/public/provider-status")" == "404" ]]
  curl -fsS --resolve "$public_hostname:443:127.0.0.1" "https://$public_hostname/public/latest/manifest.json" \
    | tee /tmp/stonks-manifest.json >/dev/null
  grep -q '"current_version"' /tmp/stonks-manifest.json
  grep -q '"objects"' /tmp/stonks-manifest.json
  curl -fsS --resolve "$public_hostname:443:127.0.0.1" "https://$public_hostname/api/instruments/search?q=IBM&limit=1&context=BUILDER" \
    | grep -q 'IBM'
  curl -fsS --resolve "$public_hostname:443:127.0.0.1" "https://$public_hostname/en/curves" >/dev/null
}

run_phase prepare-host prepare_host
run_phase sync-release sync_release
run_phase install-env install_env
run_phase build-or-pull-api build_api
run_phase migrate migrate
run_phase start start_services
run_phase verify-scheduler verify_scheduler_runtime
run_phase refresh-snapshots refresh_snapshots
run_phase smoke smoke
