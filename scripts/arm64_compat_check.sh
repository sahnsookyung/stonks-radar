#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
docker buildx build --platform linux/arm64 -f apps/backend_elixir/Dockerfile .
