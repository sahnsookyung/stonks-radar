from __future__ import annotations

import sys

from frw_api.services import snapshot_service


def test_snapshot_service_resolves_repo_assets() -> None:
    assert (snapshot_service.SCHEMA_DIR / "home_snapshot.schema.json").exists()
    assert (snapshot_service.WEB_PUBLIC / "latest" / "manifest.json").exists()
    assert str(snapshot_service.ROOT) in sys.path
