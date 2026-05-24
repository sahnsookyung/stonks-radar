#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
docker buildx build --platform linux/arm64 -f apps/api/Dockerfile .
docker buildx build --platform linux/arm64 -f apps/worker/Dockerfile .
docker buildx build --platform linux/arm64 -f apps/fetch-sandbox/Dockerfile .
