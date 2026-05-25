#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
npm run deploy:preflight
npm run build
docker compose -f compose.yaml -f infra/docker-compose.prod.yml build --pull
docker compose -f compose.yaml -f infra/docker-compose.prod.yml up -d
docker builder prune -af
