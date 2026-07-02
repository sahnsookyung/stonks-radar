#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

deploy_mode="${STONKS_DEPLOY_MODE:-fast}"
deploy_verify="${STONKS_DEPLOY_VERIFY:-false}"
compose_files=(-f compose.yaml -f infra/docker-compose.prod.yml)

if [[ "$deploy_mode" != "fast" && "$deploy_mode" != "clean" ]]; then
  echo "STONKS_DEPLOY_MODE must be fast or clean, got: $deploy_mode" >&2
  exit 1
fi

if [[ "$deploy_mode" == "clean" || "$deploy_verify" == "true" ]]; then
  npm run web:test
  npm run backend:check
fi

npm run build

if [[ "$deploy_mode" == "clean" ]]; then
  docker builder prune -af || true
  docker image prune -af || true
fi

COMPOSE_PARALLEL_LIMIT=1 DOCKER_BUILDKIT=1 docker compose "${compose_files[@]}" build api-elixir
COMPOSE_PARALLEL_LIMIT=1 docker compose "${compose_files[@]}" up -d postgres valkey
docker compose "${compose_files[@]}" run --rm --no-deps api-elixir \
  /app/bin/stonks_backend eval 'StonksBackend.Release.migrate()'
COMPOSE_PARALLEL_LIMIT=1 docker compose "${compose_files[@]}" up -d api-elixir caddy
