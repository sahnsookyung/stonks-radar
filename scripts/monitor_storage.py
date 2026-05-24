from __future__ import annotations

import shutil
from pathlib import Path
import os


def main() -> None:
    usage = shutil.disk_usage(Path.cwd())
    pct = usage.used / usage.total * 100
    status = "ok"
    if pct >= 90:
        status = "degraded_read_only"
    elif pct >= 80:
        status = "critical_warning"
    elif pct >= 70:
        status = "warning"
    print(f"disk_used_pct={pct:.2f}")
    print(f"disk_watermark_status={status}")
    if os.getenv("DATABASE_URL"):
        from sqlalchemy import create_engine, text

        engine = create_engine(os.environ["DATABASE_URL"], future=True)
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    insert into operation_status(status_key, status_value, severity, details, updated_at)
                    values ('disk_watermark', :status, :severity, jsonb_build_object('used_pct', :pct), now())
                    on conflict (status_key) do update
                    set status_value = excluded.status_value,
                        severity = excluded.severity,
                        details = excluded.details,
                        updated_at = now()
                    """
                ),
                {
                    "status": status,
                    "severity": "critical" if pct >= 90 else "warning" if pct >= 70 else "info",
                    "pct": pct,
                },
            )


if __name__ == "__main__":
    main()
