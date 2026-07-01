#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

compose_files=(-f compose.yaml -f infra/docker-compose.prod.yml)

npm run web:test
npm run backend:check
npm run build

docker compose "${compose_files[@]}" build --pull api-elixir
docker compose "${compose_files[@]}" up -d postgres valkey
docker compose "${compose_files[@]}" run --rm --no-deps api-elixir \
  /app/bin/stonks_backend eval 'StonksBackend.Release.migrate()'
docker compose "${compose_files[@]}" up -d api-elixir caddy
docker builder prune -af
