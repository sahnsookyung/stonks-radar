#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
npm run seed:snapshots
npm run check:schemas
python3 - <<'PY'
try:
    from frw_api.db.session import SessionLocal
    from frw_api.services.snapshot_service import build_candidate_snapshots, publish_snapshots
except Exception as exc:
    raise SystemExit(f"Run inside the API environment to publish local snapshots: {exc}")

with SessionLocal() as db:
    candidate = build_candidate_snapshots(db)
    result = publish_snapshots(db, snapshot_version=candidate.snapshot_version)
    db.commit()
    print(result)
PY
