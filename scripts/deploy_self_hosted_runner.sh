#!/usr/bin/env bash
set -euo pipefail

env_file="${1:-/tmp/stonks-production.env}"
source_dir="${GITHUB_WORKSPACE:-$(pwd)}"
deploy_dir="${STONKS_DEPLOY_DIR:-/opt/stonks-radar}"
compose_files=(-f compose.yaml -f infra/docker-compose.prod.yml)

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

if [[ ! -d "$deploy_dir" ]]; then
  "${sudo_cmd[@]}" mkdir -p "$deploy_dir"
  "${sudo_cmd[@]}" chown "$(id -u):$(id -g)" "$deploy_dir"
elif [[ ! -w "$deploy_dir" ]]; then
  "${sudo_cmd[@]}" chown -R "$(id -u):$(id -g)" "$deploy_dir"
fi

docker container prune -f || true
docker builder prune -af || true
docker image prune -af || true

rm -rf \
  "$deploy_dir/node_modules" \
  "$deploy_dir/apps/web/node_modules" \
  "$deploy_dir/apps/web/dist" \
  "$deploy_dir/apps/web/.generated-public" \
  "$deploy_dir/apps/backend_elixir/deps" \
  "$deploy_dir/apps/backend_elixir/_build" \
  "$deploy_dir/apps/backend_elixir/.elixir_ls" \
  "$deploy_dir/.pytest_cache"

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
    --exclude 'playwright-report' \
    --exclude 'test-results' \
    "$source_dir/" "$deploy_dir/"
fi

mkdir -p "$deploy_dir/apps/web/dist/assets" "$deploy_dir/.secrets"
install -m 600 "$env_file" "$deploy_dir/.env"
install -m 600 "$env_file" "$deploy_dir/.secrets/stonks-radar.production.env"

cd "$deploy_dir"
docker compose "${compose_files[@]}" --profile python-legacy down --remove-orphans || true
docker rm -f stonks-radar-api-1 stonks-radar-worker-1 stonks-radar-fetch-sandbox-1 || true
for volume in stonks-radar_snapshot-artifacts stonks-radar_published-snapshots; do
  mountpoint="$(docker volume inspect "$volume" --format "{{ .Mountpoint }}" 2>/dev/null || true)"
  if [[ -n "$mountpoint" && -d "$mountpoint" ]]; then
    "${sudo_cmd[@]}" find "$mountpoint" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
  fi
done
docker image rm -f stonks-radar-api stonks-radar-api-elixir stonks-radar-fetch-sandbox || true
docker container prune -f || true
docker builder prune -af || true
docker image prune -f || true
df -h / /opt /tmp || true

COMPOSE_PARALLEL_LIMIT=1 DOCKER_BUILDKIT=1 docker compose "${compose_files[@]}" build api-elixir
docker builder prune -af || true
COMPOSE_PARALLEL_LIMIT=1 docker compose "${compose_files[@]}" up -d postgres valkey
docker compose "${compose_files[@]}" run --rm --no-deps api-elixir \
  /app/bin/stonks_backend eval 'StonksBackend.Release.migrate()'
COMPOSE_PARALLEL_LIMIT=1 docker compose "${compose_files[@]}" up -d api-elixir caddy
docker image prune -f || true
df -h / /opt /tmp || true
docker run --rm \
  -v stonks-radar_published-snapshots:/dest \
  -v "$deploy_dir/apps/web/public/public:/src:ro" \
  alpine:3.24 \
  sh -lc 'set -e; rm -rf /dest/* /dest/.[!.]* /dest/..?* 2>/dev/null || true; cp -a /src/. /dest/; test -s /dest/latest/manifest.json'

public_hostname="$(awk -F= '$1=="PUBLIC_HOSTNAME"{print $2}' .env)"
public_hostname="$(printf '%s' "$public_hostname" | tr -d '[:space:]"')"
public_hostname="$(printf '%s' "$public_hostname" | tr -d "'")"
if [[ -z "$public_hostname" ]]; then
  echo "PUBLIC_HOSTNAME is missing from production env" >&2
  exit 1
fi

curl -fsS --resolve "$public_hostname:443:127.0.0.1" "https://$public_hostname/api/public/health" >/dev/null
curl -fsS --resolve "$public_hostname:443:127.0.0.1" "https://$public_hostname/public/latest/manifest.json" \
  | tee /tmp/stonks-manifest.json >/dev/null
grep -q '"current_version"' /tmp/stonks-manifest.json
grep -q '"objects"' /tmp/stonks-manifest.json
