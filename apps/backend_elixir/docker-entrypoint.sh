#!/bin/sh
set -eu

mkdir -p /app/artifacts/snapshots /app/published-public
chown -R stonks:stonks /app/artifacts /app/published-public

if [ "${RUN_MIGRATIONS_ON_START:-true}" = "true" ] &&
   [ "${1:-}" = "bin/stonks_backend" ] &&
   [ "${2:-}" = "start" ]; then
  su-exec stonks:stonks bin/stonks_backend eval 'StonksBackend.Release.migrate()'
fi

exec su-exec stonks:stonks "$@"
