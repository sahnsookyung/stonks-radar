#!/bin/sh
set -eu

mkdir -p /app/artifacts/snapshots /app/published-public
chown -R frw:frw /app/artifacts /app/published-public

exec gosu frw "$@"
