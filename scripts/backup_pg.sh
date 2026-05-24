#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL required}"
: "${BACKUP_PASSPHRASE:?BACKUP_PASSPHRASE required for encrypted backups}"

out_dir="${BACKUP_DIR:-artifacts/backups}"
mkdir -p "$out_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
pg_dump "$DATABASE_URL" | gzip -9 | openssl enc -aes-256-cbc -salt -pbkdf2 -pass "env:BACKUP_PASSPHRASE" -out "$out_dir/frw-$stamp.sql.gz.enc"
find "$out_dir" -name 'frw-*.sql.gz.enc' -type f | sort | head -n -7 | xargs -r rm
python3 - <<'PY' || true
import os
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["DATABASE_URL"], future=True)
with engine.begin() as conn:
    conn.execute(text("""
        insert into operation_status(status_key, status_value, severity, details, updated_at)
        values ('backup', 'succeeded', 'info', '{}'::jsonb, now())
        on conflict (status_key) do update set status_value='succeeded', severity='info', details='{}'::jsonb, updated_at=now()
    """))
PY
echo "backup_written=$out_dir/frw-$stamp.sql.gz.enc"
