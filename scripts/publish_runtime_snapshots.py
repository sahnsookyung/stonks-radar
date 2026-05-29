from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frw_api.db.session import SessionLocal
from frw_api.services.snapshot_service import build_candidate_snapshots, publish_snapshots


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and publish DB-backed public snapshots.")
    parser.add_argument("--generated-by", default="deploy", help="Audit label stored with publication rows.")
    args = parser.parse_args()

    with SessionLocal() as db:
        candidate = build_candidate_snapshots(db, generated_by=args.generated_by)
        if candidate.snapshot_version is None:
            raise RuntimeError("Snapshot builder did not return a snapshot version")
        published = publish_snapshots(db, snapshot_version=candidate.snapshot_version, generated_by=args.generated_by)
        db.commit()

    print(
        json.dumps(
            {
                "snapshot_version": published.snapshot_version,
                "file_count": len(published.files),
                "destination": published.destination,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
