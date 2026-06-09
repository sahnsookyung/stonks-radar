#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
[[ -f .env ]] || cp .env.example .env
if [[ -f package-lock.json ]]; then
  npm ci --ignore-scripts
else
  npm install --ignore-scripts
fi
npm run seed:snapshots
docker compose -f compose.yaml -f compose.dev.yaml up --build
