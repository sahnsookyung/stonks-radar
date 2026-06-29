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

old_assets_dir="${STONKS_DEPLOY_OLD_ASSETS_DIR:-${deploy_dir%/}-old-assets}"
rm -rf "$old_assets_dir"
mkdir -p "$old_assets_dir"
cleanup() {
  rm -rf "$old_assets_dir"
}
trap cleanup EXIT

if [[ -d "$deploy_dir/apps/web/dist/assets" ]]; then
  cp -a "$deploy_dir/apps/web/dist/assets/." "$old_assets_dir/" || true
fi

if [[ "$(cd "$source_dir" && pwd -P)" != "$(cd "$deploy_dir" && pwd -P)" ]]; then
  rsync -az --delete \
    --exclude '.git' \
    --exclude '.gitnexus' \
    --exclude '.secrets' \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude 'node_modules' \
    --exclude 'artifacts' \
    --exclude 'playwright-report' \
    --exclude 'test-results' \
    "$source_dir/" "$deploy_dir/"
fi

mkdir -p "$deploy_dir/apps/web/dist/assets" "$deploy_dir/.secrets"
cp -an "$old_assets_dir/." "$deploy_dir/apps/web/dist/assets/" || true
install -m 600 "$env_file" "$deploy_dir/.env"
install -m 600 "$env_file" "$deploy_dir/.secrets/stonks-radar.production.env"

cd "$deploy_dir"
docker compose "${compose_files[@]}" build --pull
docker compose "${compose_files[@]}" up -d
docker builder prune -af
docker compose "${compose_files[@]}" run --rm -e PYTHONPATH=/app worker \
  python scripts/publish_runtime_snapshots.py --generated-by github-actions-self-hosted

public_hostname="$(awk -F= '$1=="PUBLIC_HOSTNAME"{print $2}' .env)"
public_hostname="$(printf '%s' "$public_hostname" | tr -d '[:space:]"')"
public_hostname="$(printf '%s' "$public_hostname" | tr -d "'")"
if [[ -z "$public_hostname" ]]; then
  echo "PUBLIC_HOSTNAME is missing from production env" >&2
  exit 1
fi

curl -fsS --resolve "$public_hostname:443:127.0.0.1" "https://$public_hostname/api/public/health" >/dev/null
curl -fsS --resolve "$public_hostname:443:127.0.0.1" "https://$public_hostname/public/latest/manifest.json" \
  | python3 -c 'import json, sys; data=json.load(sys.stdin); assert data.get("current_version") and data.get("objects")'
