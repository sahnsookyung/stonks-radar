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
  COMPOSE_PARALLEL_LIMIT=1 compose up -d postgres valkey
  compose run --rm --no-deps api-elixir \
    /app/bin/stonks_backend eval 'StonksBackend.Release.migrate()'
}

start_services() {
  cd "$deploy_dir"
  COMPOSE_PARALLEL_LIMIT=1 compose up -d api-elixir caddy
  df -h / /opt /tmp || true
}

refresh_snapshots() {
  if ! docker run --rm \
    -v stonks-radar_published-snapshots:/dest:ro \
    alpine:3.24 \
    test -s /dest/latest/manifest.json; then
    echo "Snapshot volume is empty; seeding static public snapshots before Elixir refresh"
    docker run --rm \
      -v stonks-radar_published-snapshots:/dest \
      -v "$deploy_dir/apps/web/public/public:/src:ro" \
      alpine:3.24 \
      sh -lc 'set -e; rm -rf /dest/* /dest/.[!.]* /dest/..?* 2>/dev/null || true; cp -a /src/. /dest/; chmod -R a+rwX /dest; test -s /dest/latest/manifest.json'
  fi

  docker run --rm -v stonks-radar_published-snapshots:/dest alpine:3.24 chmod -R a+rwX /dest

  cd "$deploy_dir"
  compose run --rm --no-deps api-elixir \
    env START_SCHEDULER=false OBAN_QUEUES_ENABLED=false \
    /app/bin/stonks_backend eval '
      case StonksBackend.Snapshots.refresh(%{"requested_by" => "deploy", "mode" => "db_generated_publish"}) do
        {:ok, result} -> IO.inspect(result, label: "published_snapshot")
        {:error, reason} -> raise "snapshot refresh failed: #{inspect(reason)}"
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
run_phase refresh-snapshots refresh_snapshots
run_phase smoke smoke
