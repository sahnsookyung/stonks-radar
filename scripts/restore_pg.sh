#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL required}"
: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE required}"
: "${BACKUP_FILE:?BACKUP_FILE required}"

openssl enc -d -aes-256-cbc -pbkdf2 -pass "env:BACKUP_PASSPHRASE" -in "$BACKUP_FILE" | gunzip | psql "$DATABASE_URL"
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL' >/dev/null || true
insert into operation_status(status_key, status_value, severity, details, updated_at)
values ('restore_drill_at', to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), 'info', '{}'::jsonb, now())
on conflict (status_key)
do update set status_value=excluded.status_value, severity='info', details='{}'::jsonb, updated_at=now();
SQL
echo "restore_completed=$BACKUP_FILE"
