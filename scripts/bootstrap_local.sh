#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
test -f .env || cp .env.example .env
npm install
npm run seed:snapshots
docker compose -f compose.yaml -f compose.dev.yaml up --build
