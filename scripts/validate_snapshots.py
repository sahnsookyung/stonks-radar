from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = ROOT / "apps" / "web" / "public" / "public"
SCHEMA_ROOT = ROOT / "packages" / "schemas" / "snapshots"

REQUIRED_SHEMAS = [
    "home_snapshot.schema.json",
    "map_events_snapshot.schema.json",
    "calendar_snapshot.schema.json",
    "country_region_snapshot.schema.json",
    "sector_snapshot.schema.json",
    "scenario_basket_snapshot.schema.json",
    "source_status_snapshot.schema.json",
    "correction_log_snapshot.schema.json",
]

REQUIRED_ENVELOPE_FIELDS = {
    "schema_version",
    "snapshot_version",
    "locale",
    "generated_at",
    "stale_after",
    "hard_expires_at",
    "object_type",
    "object_key",
    "content_hash",
    "source_policy_versions",
    "data",
    "warnings",
    "corrections",
}


def main() -> None:
    missing_schemas = [name for name in REQUIRED_SHEMAS if not (SCHEMA_ROOT / name).exists()]
    if missing_schemas:
        raise SystemExit(f"Missing snapshot schemas: {missing_schemas}")
    manifest_path = PUBLIC_ROOT / "latest" / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit("Missing latest manifest. Run scripts/build_seed_snapshots.py")
    manifest = json.loads(manifest_path.read_text())
    if sorted(manifest["locales"]) != ["en", "ko"]:
        raise SystemExit("Manifest must include en and ko locales")
    for object_key, locale_paths in manifest["objects"].items():
        for locale, path in locale_paths.items():
            snapshot_path = PUBLIC_ROOT / path.removeprefix("public/")
            if not snapshot_path.exists():
                raise SystemExit(f"Manifest object {object_key}/{locale} points to missing {path}")
            snapshot = json.loads(snapshot_path.read_text())
            missing = REQUIRED_ENVELOPE_FIELDS.difference(snapshot)
            if missing:
                raise SystemExit(f"{path} missing envelope fields: {sorted(missing)}")
            if snapshot["locale"] != locale:
                raise SystemExit(f"{path} locale mismatch")
            if not snapshot["content_hash"].startswith("sha256:"):
                raise SystemExit(f"{path} content_hash must be sha256")
            if not snapshot["source_policy_versions"]:
                raise SystemExit(f"{path} must record source policy versions")
            if snapshot["object_type"] != "correction_log" and isinstance(snapshot["data"], dict):
                _assert_no_raw_private_text(snapshot["data"], path)
    print(f"Validated {sum(len(v) for v in manifest['objects'].values())} snapshots")


def _assert_no_raw_private_text(value, path: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in {"raw_html", "private_note", "restricted_source_text"}:
                raise SystemExit(f"{path} contains prohibited public field {key}")
            _assert_no_raw_private_text(nested, path)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_raw_private_text(nested, path)


if __name__ == "__main__":
    main()
