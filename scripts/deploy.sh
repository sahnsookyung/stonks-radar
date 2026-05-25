#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

snapshot_env_file="${STONKS_SNAPSHOT_ENV_FILE:-}"
if [[ -z "$snapshot_env_file" && -f ".secrets/stonks-radar.production.env" ]]; then
  snapshot_env_file=".secrets/stonks-radar.production.env"
fi

npm run deploy:preflight
if [[ -n "$snapshot_env_file" ]]; then
  STONKS_SNAPSHOT_ENV_FILE="$snapshot_env_file" npm run build
else
  npm run build
fi
docker compose -f compose.yaml -f infra/docker-compose.prod.yml build --pull
docker compose -f compose.yaml -f infra/docker-compose.prod.yml up -d
docker builder prune -af
