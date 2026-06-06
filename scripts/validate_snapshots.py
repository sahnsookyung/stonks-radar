from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
    "news_index_snapshot.schema.json",
    "news_event_snapshot.schema.json",
    "news_ticker_snapshot.schema.json",
    "news_region_snapshot.schema.json",
    "news_topic_snapshot.schema.json",
]

PROHIBITED_PUBLIC_FIELDS = {
    "raw_html",
    "private_note",
    "restricted_source_text",
    "full_article_text",
    "prompt_text",
    "secret",
    "api_key",
}

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
    public_root = _public_root()
    require_fresh = _truthy(os.getenv("STONKS_REQUIRE_FRESH_SNAPSHOTS"))
    min_hard_expiry_hours = float(os.getenv("STONKS_SNAPSHOT_MIN_HARD_EXPIRY_HOURS", "12"))
    min_hard_expiry = datetime.now(timezone.utc) + timedelta(hours=min_hard_expiry_hours)
    missing_schemas = [name for name in REQUIRED_SHEMAS if not (SCHEMA_ROOT / name).exists()]
    if missing_schemas:
        raise SystemExit(f"Missing snapshot schemas: {missing_schemas}")
    manifest_path = public_root / "latest" / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit("Missing latest manifest. Run scripts/build_seed_snapshots.py")
    manifest = json.loads(manifest_path.read_text())
    if sorted(manifest["locales"]) != ["en", "ko"]:
        raise SystemExit("Manifest must include en and ko locales")
    for object_key, locale_paths in manifest["objects"].items():
        for locale, path in locale_paths.items():
            snapshot_path = public_root / path.removeprefix("public/")
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
            if require_fresh:
                _assert_not_near_hard_expiry(snapshot["hard_expires_at"], path, min_hard_expiry)
            if snapshot["object_type"] != "correction_log" and isinstance(snapshot["data"], dict):
                _assert_no_raw_private_text(snapshot["data"], path)
    print(f"Validated {sum(len(v) for v in manifest['objects'].values())} snapshots")


def _public_root() -> Path:
    raw = os.getenv("STONKS_SNAPSHOT_PUBLIC_ROOT")
    if not raw:
        return ROOT / "apps" / "web" / "public" / "public"
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _assert_not_near_hard_expiry(value: str, path: str, min_hard_expiry: datetime) -> None:
    try:
        expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"{path} hard_expires_at is not an ISO timestamp") from exc
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= min_hard_expiry:
        raise SystemExit(f"{path} hard_expires_at is too close or expired: {value}")


def _assert_no_raw_private_text(value, path: str) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in PROHIBITED_PUBLIC_FIELDS:
                raise SystemExit(f"{path} contains prohibited public field {key}")
            _assert_no_raw_private_text(nested, path)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_raw_private_text(nested, path)


if __name__ == "__main__":
    main()
