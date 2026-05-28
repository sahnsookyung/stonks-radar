#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

snapshot_env_file="${STONKS_SNAPSHOT_ENV_FILE:-}"
if [[ -z "$snapshot_env_file" && -f ".secrets/stonks-radar.production.env" ]]; then
  snapshot_env_file=".secrets/stonks-radar.production.env"
fi

compose_env_args=()
if [[ -n "$snapshot_env_file" ]]; then
  compose_env_args=(--env-file "$snapshot_env_file")
fi
compose_files=(-f compose.yaml -f infra/docker-compose.prod.yml)

if [[ -n "$snapshot_env_file" ]]; then
  STONKS_SNAPSHOT_ENV_FILE="$snapshot_env_file" npm run deploy:preflight
else
  npm run deploy:preflight
fi
if [[ -n "$snapshot_env_file" ]]; then
  STONKS_SNAPSHOT_ENV_FILE="$snapshot_env_file" npm run build
else
  npm run build
fi
docker compose "${compose_env_args[@]}" "${compose_files[@]}" build --pull
docker compose "${compose_env_args[@]}" "${compose_files[@]}" up -d
docker builder prune -af
