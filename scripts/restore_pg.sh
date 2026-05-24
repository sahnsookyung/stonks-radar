#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL required}"
: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE required}"
: "${BACKUP_FILE:?BACKUP_FILE required}"

openssl enc -d -aes-256-cbc -pbkdf2 -pass "env:BACKUP_PASSPHRASE" -in "$BACKUP_FILE" | gunzip | psql "$DATABASE_URL"
python3 - <<'PY' || true
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"], future=True)
with engine.begin() as conn:
    conn.execute(text("""
        insert into operation_status(status_key, status_value, severity, details, updated_at)
        values ('restore_drill_at', to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), 'info', '{}'::jsonb, now())
        on conflict (status_key) do update set status_value=excluded.status_value, severity='info', details='{}'::jsonb, updated_at=now()
    """))
PY
echo "restore_completed=$BACKUP_FILE"
