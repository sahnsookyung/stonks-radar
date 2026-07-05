#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

deploy_mode="${STONKS_DEPLOY_MODE:-fast}"
deploy_verify="${STONKS_DEPLOY_VERIFY:-false}"
api_image="${STONKS_API_IMAGE:-}"
ghcr_actor="${STONKS_GHCR_ACTOR:-${GITHUB_ACTOR:-}}"
ghcr_token="${STONKS_GHCR_TOKEN:-${GITHUB_TOKEN:-}}"
compose_files=(-f compose.yaml -f infra/docker-compose.prod.yml)

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

if [[ "$deploy_mode" == "clean" || "$deploy_verify" == "true" ]]; then
  npm run web:test
  npm run backend:check
fi

export VITE_WEB_ARTIFACT_VERSION="${VITE_WEB_ARTIFACT_VERSION:-${GITHUB_SHA:-local}}"
npm run build

if [[ "$deploy_mode" == "clean" ]]; then
  docker builder prune -af || true
  docker image prune -af || true
fi

if [[ "$deploy_mode" == "fast" && -n "$api_image" ]]; then
  if [[ -n "$ghcr_actor" && -n "$ghcr_token" ]]; then
    printf '%s\n' "$ghcr_token" | docker login ghcr.io -u "$ghcr_actor" --password-stdin
  fi

  docker pull "$api_image"
else
  COMPOSE_PARALLEL_LIMIT=1 DOCKER_BUILDKIT=1 compose build api-elixir
fi

compose stop api-elixir || true
migration_complete=0
restore_api_on_migration_failure() {
  if [[ "$migration_complete" != "1" ]]; then
    COMPOSE_PARALLEL_LIMIT=1 compose up -d api-elixir caddy || true
  fi
}
trap restore_api_on_migration_failure EXIT

COMPOSE_PARALLEL_LIMIT=1 compose up -d postgres valkey
compose run --rm --no-deps api-elixir \
  /app/bin/stonks_backend eval 'StonksBackend.Release.migrate()'
migration_complete=1
trap - EXIT
COMPOSE_PARALLEL_LIMIT=1 compose up -d api-elixir caddy
