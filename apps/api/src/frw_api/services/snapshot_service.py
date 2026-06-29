from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from sqlalchemy import text
from sqlalchemy.orm import Session

from frw_api.services.news.snapshot_builder import build_reviewed_news_snapshots
from frw_api.services.publication_gate import EventGateInput, can_publish_event


def _resolve_repo_root() -> Path:
    current = Path(__file__).resolve()
    candidates: list[Path] = []
    for env_name in ("STONKS_REPO_ROOT", "APP_ROOT"):
        if raw := os.getenv(env_name):
            candidates.append(Path(raw))
    candidates.extend([Path.cwd(), Path("/app")])
    candidates.extend(current.parents)
    for candidate in candidates:
        root = candidate.resolve()
        if (root / "packages" / "schemas" / "snapshots").is_dir() and (
            root / "apps" / "web" / "public" / "public"
        ).is_dir():
            return root
    return current.parents[5]


ROOT = _resolve_repo_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
WEB_PUBLIC = ROOT / "apps" / "web" / "public" / "public"
SCHEMA_DIR = ROOT / "packages" / "schemas" / "snapshots"
LOCAL_ARTIFACTS = Path(os.getenv("SNAPSHOT_ARTIFACT_DIR", str(ROOT / "artifacts" / "snapshots")))
CANDIDATE_ROOT = LOCAL_ARTIFACTS / "candidates"
PUBLISHED_ROOT = Path(os.getenv("PUBLISHED_SNAPSHOT_DIR", str(WEB_PUBLIC)))
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
PROHIBITED_PUBLIC_FIELDS = {
    "raw_html",
    "private_note",
    "restricted_source_text",
    "full_article_text",
    "prompt_text",
    "secret",
    "api_key",
}
MANIFEST_FILENAME = "manifest.json"
JSON_FILE_GLOB = "*.json"
SHA256_PREFIX = "sha256:"
PUBLIC_SNAPSHOT_PREFIX = "public/"
PUBLIC_LATEST_MANIFEST_KEY = f"public/latest/{MANIFEST_FILENAME}"
LATEST_MANIFEST_PATH = Path("latest") / MANIFEST_FILENAME


@dataclass
class SnapshotTreeContext:
    version: int
    generated_at: datetime
    corrections: list[dict[str, Any]]
    db_events: dict[str, list[dict[str, Any]]]
    db_calendar: list[dict[str, Any]]
    previous_macro_tiles: dict[str, dict[str, dict[str, Any]]]
    previous_breaking_market: dict[str, dict[str, Any]]
    db_news_by_locale: dict[str, dict[str, Any]]
    news_event_templates: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class SnapshotBuildResult:
    files: list[str]
    uploaded: bool
    destination: str
    snapshot_version: int | None = None


def build_local_seed_snapshots() -> SnapshotBuildResult:
    from scripts.build_seed_snapshots import build_snapshots

    build_snapshots()
    return SnapshotBuildResult(files=[str(path) for path in WEB_PUBLIC.rglob(JSON_FILE_GLOB)], uploaded=False, destination=str(WEB_PUBLIC), snapshot_version=1)


def build_candidate_snapshots(db: Session, *, generated_by: str | None = None) -> SnapshotBuildResult:
    _assert_publication_gates(db)
    version = _next_snapshot_version(db)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0)
    seed_public_root = LOCAL_ARTIFACTS / "runtime-seeds" / f"v{version}" / "public"
    candidate_public_root = CANDIDATE_ROOT / f"v{version}" / "public"
    if seed_public_root.exists():
        shutil.rmtree(seed_public_root)
    _build_fresh_seed_snapshots(seed_public_root)
    if candidate_public_root.exists():
        shutil.rmtree(candidate_public_root)
    candidate_public_root.mkdir(parents=True, exist_ok=True)

    files, manifest = _build_snapshot_tree(db, candidate_public_root, version, generated_at, seed_public_root=seed_public_root)
    _record_manifest(db, manifest, candidate_public_root / LATEST_MANIFEST_PATH, version, "candidate", generated_by)
    _record_publication_rows(db, files, candidate_public_root, generated_by, "candidate")
    return SnapshotBuildResult(
        files=[str(path) for path in files],
        uploaded=False,
        destination=str(candidate_public_root),
        snapshot_version=version,
    )


def _build_fresh_seed_snapshots(public_root: Path) -> None:
    from scripts import build_seed_snapshots

    public_root.mkdir(parents=True, exist_ok=True)
    previous_public_root = build_seed_snapshots.PUBLIC_ROOT
    previous_env_public_root = os.environ.get("STONKS_SNAPSHOT_PUBLIC_ROOT")
    build_seed_snapshots.PUBLIC_ROOT = public_root
    try:
        os.environ["STONKS_SNAPSHOT_PUBLIC_ROOT"] = str(public_root)
        build_seed_snapshots.build_snapshots()
    finally:
        build_seed_snapshots.PUBLIC_ROOT = previous_public_root
        if previous_env_public_root is None:
            os.environ.pop("STONKS_SNAPSHOT_PUBLIC_ROOT", None)
        else:
            os.environ["STONKS_SNAPSHOT_PUBLIC_ROOT"] = previous_env_public_root
    required_seed = public_root / "latest" / MANIFEST_FILENAME
    if not required_seed.exists():
        raise FileNotFoundError(f"Seed snapshot manifest was not generated at {required_seed}")
    _preserve_packaged_breaking_market_seed(public_root, datetime.now(timezone.utc).replace(microsecond=0))


def _preserve_packaged_breaking_market_seed(public_root: Path, generated_at: datetime) -> None:
    if public_root.resolve() == WEB_PUBLIC.resolve():
        return
    runtime_manifest_path = public_root / LATEST_MANIFEST_PATH
    packaged_manifest_path = WEB_PUBLIC / LATEST_MANIFEST_PATH
    if not runtime_manifest_path.exists() or not packaged_manifest_path.exists():
        return
    runtime_manifest = json.loads(runtime_manifest_path.read_text())
    packaged_manifest = json.loads(packaged_manifest_path.read_text())
    locales = runtime_manifest.get("locales")
    if not isinstance(locales, list):
        return
    for locale in locales:
        if not isinstance(locale, str):
            continue
        _preserve_packaged_breaking_market_locale(
            public_root,
            runtime_manifest=runtime_manifest,
            packaged_manifest=packaged_manifest,
            locale=locale,
            generated_at=generated_at,
        )


def _preserve_packaged_breaking_market_locale(
    public_root: Path,
    *,
    runtime_manifest: dict[str, Any],
    packaged_manifest: dict[str, Any],
    locale: str,
    generated_at: datetime,
) -> None:
    packaged_breaking = _breaking_market_projection_from_seed(WEB_PUBLIC, packaged_manifest, "home", locale)
    fresh_packaged = (
        _fresh_breaking_market_projection(packaged_breaking, generated_at)
        if isinstance(packaged_breaking, dict)
        else None
    )
    if fresh_packaged is None:
        return
    for object_key in ("home", "map_events"):
        runtime_path = _seed_manifest_path(public_root, runtime_manifest, object_key, locale)
        if runtime_path is None or not runtime_path.exists():
            continue
        snapshot = json.loads(runtime_path.read_text())
        data = snapshot.get("data")
        if not isinstance(data, dict):
            continue
        current_breaking = data.get("breaking_market_map")
        if isinstance(current_breaking, dict) and _fresh_breaking_market_projection(current_breaking, generated_at):
            continue
        _set_breaking_market_projection(snapshot, fresh_packaged)
        runtime_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")


def _breaking_market_projection_from_seed(
    public_root: Path,
    manifest: dict[str, Any],
    object_key: str,
    locale: str,
) -> dict[str, Any] | None:
    snapshot_path = _seed_manifest_path(public_root, manifest, object_key, locale)
    if snapshot_path is None or not snapshot_path.exists():
        return None
    snapshot = json.loads(snapshot_path.read_text())
    data = snapshot.get("data")
    if not isinstance(data, dict):
        return None
    breaking = data.get("breaking_market_map")
    return breaking if isinstance(breaking, dict) else None


def _seed_manifest_path(
    public_root: Path,
    manifest: dict[str, Any],
    object_key: str,
    locale: str,
) -> Path | None:
    objects = manifest.get("objects")
    if not isinstance(objects, dict):
        return None
    locale_paths = objects.get(object_key)
    if not isinstance(locale_paths, dict):
        return None
    raw_path = locale_paths.get(locale)
    if not isinstance(raw_path, str) or not raw_path:
        return None
    return _public_snapshot_path(public_root, raw_path)


def _public_snapshot_path(root: Path, raw_path: str) -> Path:
    return root / raw_path.removeprefix(PUBLIC_SNAPSHOT_PREFIX)


def list_snapshot_candidates(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select snapshot_version, publication_status, generated_at, published_at, byte_size, content_hash
            from publication_manifest
            order by generated_at desc
            limit 50
            """
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def publish_snapshots(
    db: Session,
    *,
    snapshot_version: int,
    generated_by: str | None = None,
) -> SnapshotBuildResult:
    manifest = _manifest_row(db, snapshot_version)
    candidate_root = CANDIDATE_ROOT / f"v{snapshot_version}" / "public"
    if not candidate_root.exists():
        raise ValueError(f"Snapshot candidate files for v{snapshot_version} are missing")
    files = sorted(candidate_root.rglob(JSON_FILE_GLOB))
    for file_path in files:
        _validate_snapshot_file(file_path)
    _publish_files_locally(files, candidate_root)
    uploaded = False
    destination = str(PUBLISHED_ROOT)
    db.execute(text("update publication_manifest set publication_status = 'rolled_back' where publication_status = 'published'"))
    db.execute(text("update publication_snapshot set publication_status = 'rolled_back' where publication_status = 'published'"))
    db.execute(
        text(
            """
            update publication_manifest
            set publication_status = 'published', published_at = now(), generated_by = coalesce(:generated_by, generated_by)
            where snapshot_version = :snapshot_version
            """
        ),
        {"snapshot_version": snapshot_version, "generated_by": generated_by},
    )
    db.execute(
        text(
            """
            update publication_snapshot
            set publication_status = 'published', generated_by = coalesce(:generated_by, generated_by)
            where snapshot_version = :snapshot_version
            """
        ),
        {"snapshot_version": snapshot_version, "generated_by": generated_by},
    )
    return SnapshotBuildResult(
        files=[str(path) for path in files],
        uploaded=uploaded,
        destination=destination,
        snapshot_version=int(manifest["snapshot_version"]),
    )


def rollback_snapshots(db: Session, *, snapshot_version: int, generated_by: str | None = None) -> SnapshotBuildResult:
    manifest = _manifest_row(db, snapshot_version, allowed_status=("published", "rolled_back"))
    source_root = CANDIDATE_ROOT / f"v{snapshot_version}" / "public"
    if not source_root.exists():
        raise ValueError(f"Snapshot files for v{snapshot_version} are missing")
    manifest_file = source_root / LATEST_MANIFEST_PATH
    if not manifest_file.exists():
        raise ValueError(f"Snapshot manifest for v{snapshot_version} is missing")
    files = sorted(source_root.rglob(JSON_FILE_GLOB))
    for file_path in files:
        _validate_snapshot_file(file_path)
    _publish_files_locally(files, source_root)
    uploaded = False
    destination = str(PUBLISHED_ROOT / LATEST_MANIFEST_PATH)
    db.execute(text("update publication_manifest set publication_status = 'rolled_back' where publication_status = 'published'"))
    db.execute(text("update publication_snapshot set publication_status = 'rolled_back' where publication_status = 'published'"))
    db.execute(
        text("update publication_manifest set publication_status = 'published', published_at = now(), generated_by = coalesce(:generated_by, generated_by) where snapshot_version = :snapshot_version"),
        {"snapshot_version": snapshot_version, "generated_by": generated_by},
    )
    db.execute(
        text("update publication_snapshot set publication_status = 'published', generated_by = coalesce(:generated_by, generated_by) where snapshot_version = :snapshot_version"),
        {"snapshot_version": snapshot_version, "generated_by": generated_by},
    )
    return SnapshotBuildResult(files=[str(manifest_file)], uploaded=uploaded, destination=destination, snapshot_version=int(manifest["snapshot_version"]))


def _build_snapshot_tree(
    db: Session,
    output_root: Path,
    version: int,
    generated_at: datetime,
    *,
    seed_public_root: Path = WEB_PUBLIC,
) -> tuple[list[Path], dict[str, Any]]:
    seed_manifest = json.loads((seed_public_root / LATEST_MANIFEST_PATH).read_text())
    manifest: dict[str, Any] = {
        "current_version": version,
        "generated_at": _iso(generated_at),
        "locales": seed_manifest["locales"],
        "objects": {},
    }
    files: list[Path] = []
    context = _snapshot_tree_context(db, version, generated_at, seed_manifest["locales"])
    for object_key, locale_paths in seed_manifest["objects"].items():
        for locale, source_path in locale_paths.items():
            snapshot = _seed_snapshot(seed_public_root, source_path, context)
            _apply_runtime_snapshot_data(db, snapshot, object_key, locale, context)
            _write_snapshot(
                output_root,
                snapshot,
                manifest,
                files,
                object_key=object_key,
                locale=locale,
                rel=_versioned_snapshot_path(version, locale, source_path, seed_manifest),
            )
    _write_news_event_snapshots(output_root, manifest, files, context)
    latest = output_root / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / LATEST_MANIFEST_PATH
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    files.append(manifest_path)
    return files, manifest


def _snapshot_tree_context(
    db: Session, version: int, generated_at: datetime, locales: list[str]
) -> SnapshotTreeContext:
    return SnapshotTreeContext(
        version=version,
        generated_at=generated_at,
        corrections=_corrections(db),
        db_events=_public_events(db),
        db_calendar=_calendar_items(db),
        previous_macro_tiles=_published_home_macro_tiles(),
        previous_breaking_market=_published_home_breaking_market(),
        db_news_by_locale={
            locale: build_reviewed_news_snapshots(db, locale=locale, generated_label=_iso(generated_at))
            for locale in locales
        },
        news_event_templates={},
    )


def _seed_snapshot(seed_public_root: Path, source_path: str, context: SnapshotTreeContext) -> dict[str, Any]:
    seed_path = _public_snapshot_path(seed_public_root, source_path)
    snapshot = json.loads(seed_path.read_text())
    snapshot["snapshot_version"] = context.version
    snapshot["generated_at"] = _iso(context.generated_at)
    snapshot["stale_after"] = _iso(context.generated_at + timedelta(hours=12))
    snapshot["hard_expires_at"] = _iso(context.generated_at + timedelta(days=7))
    snapshot["corrections"] = context.corrections
    return snapshot


def _apply_runtime_snapshot_data(
    db: Session,
    snapshot: dict[str, Any],
    object_key: str,
    locale: str,
    context: SnapshotTreeContext,
) -> None:
    object_type = snapshot["object_type"]
    if object_type == "home":
        _apply_home_snapshot_data(snapshot, locale, context)
    elif object_type == "map_events":
        _apply_map_snapshot_data(snapshot, locale, context)
    elif object_type == "calendar_upcoming":
        _apply_calendar_snapshot_data(snapshot, context)
    elif object_type == "source_status":
        seed_status = snapshot.get("data") if isinstance(snapshot.get("data"), dict) else None
        snapshot["data"] = _source_status_data(db, seed_status=seed_status)
    elif object_type == "correction_log":
        snapshot["data"]["entries"] = context.corrections
    else:
        _apply_news_snapshot_data(snapshot, object_key, object_type, locale, context)


def _apply_calendar_snapshot_data(snapshot: dict[str, Any], context: SnapshotTreeContext) -> None:
    if not context.db_calendar:
        return
    items = _sort_calendar_items(context.db_calendar)
    snapshot["data"]["items"] = items
    snapshot["data"]["central_banks"] = [
        item for item in items if "bank" in item["release_type"]
    ]


def _apply_news_snapshot_data(
    snapshot: dict[str, Any],
    object_key: str,
    object_type: str,
    locale: str,
    context: SnapshotTreeContext,
) -> None:
    news_data = context.db_news_by_locale.get(locale)
    if object_type == "news_event" and locale not in context.news_event_templates:
        context.news_event_templates[locale] = json.loads(json.dumps(snapshot))
    if not news_data:
        return
    if object_type == "news_index":
        snapshot["data"] = news_data["index"]
    elif object_type in {"news_ticker", "news_region", "news_topic"}:
        _apply_news_collection_snapshot(snapshot, object_key, object_type, news_data)


def _apply_home_snapshot_data(
    snapshot: dict[str, Any], locale: str, context: SnapshotTreeContext
) -> None:
    localized_events = context.db_events.get(locale, [])
    if localized_events:
        snapshot["data"]["top_events"] = localized_events + snapshot["data"].get("top_events", [])
    _apply_breaking_market_data(snapshot, locale, context)
    if context.db_calendar:
        snapshot["data"]["calendar_preview"] = _sort_calendar_items(context.db_calendar)[:6]
    snapshot["data"]["generated_label"] = _iso(context.generated_at)
    snapshot["data"]["snapshot_health"]["age_minutes"] = 0
    snapshot["data"]["snapshot_health"]["stale_after"] = snapshot["stale_after"]
    _apply_refresh_deltas(
        snapshot["data"].get("macro_tiles", []),
        context.previous_macro_tiles.get(locale, {}),
    )


def _apply_map_snapshot_data(
    snapshot: dict[str, Any], locale: str, context: SnapshotTreeContext
) -> None:
    localized_events = [event for event in context.db_events.get(locale, []) if _valid_public_event_geo(event)]
    _apply_breaking_market_data(snapshot, locale, context)
    if not localized_events:
        return
    snapshot["data"]["events"] = localized_events + [
        event for event in snapshot["data"].get("events", []) if _valid_public_event_geo(event)
    ]
    snapshot["data"]["filters"] = _map_filters(snapshot["data"]["events"])


def _apply_breaking_market_data(snapshot: dict[str, Any], locale: str, context: SnapshotTreeContext) -> None:
    news_data = context.db_news_by_locale.get(locale) or {}
    breaking = news_data.get("breaking_market")
    if isinstance(breaking, dict):
        fresh_runtime = _fresh_breaking_market_projection(breaking, context.generated_at)
        if fresh_runtime is not None:
            _set_breaking_market_projection(snapshot, fresh_runtime)
            return
    seed_breaking = snapshot.get("data", {}).get("breaking_market_map")
    if isinstance(seed_breaking, dict):
        fresh_seed = _fresh_breaking_market_projection(seed_breaking, context.generated_at)
        if fresh_seed is not None:
            _set_breaking_market_projection(snapshot, fresh_seed)
            return
    fallback = _fresh_breaking_market_projection(
        context.previous_breaking_market.get(locale, {}),
        context.generated_at,
    )
    if fallback is not None:
        _set_breaking_market_projection(snapshot, fallback)
        return
    if isinstance(seed_breaking, dict):
        _set_breaking_market_projection(snapshot, _empty_breaking_market_projection(seed_breaking, context.generated_at))


def _has_breaking_market_content(breaking: dict[str, Any]) -> bool:
    events = breaking.get("events")
    map_points = breaking.get("map_points")
    return bool(isinstance(events, list) and events and isinstance(map_points, list) and map_points)


def _set_breaking_market_projection(snapshot: dict[str, Any], breaking: dict[str, Any]) -> None:
    snapshot["data"]["breaking_market_events"] = breaking.get("events", [])
    snapshot["data"]["breaking_market_map"] = breaking


def _empty_breaking_market_projection(template: dict[str, Any], generated_at: datetime) -> dict[str, Any]:
    projection = {
        "events": [],
        "map_points": [],
        "shown_count": 0,
        "total_count": 0,
        "ranking_cutoff": template.get("ranking_cutoff"),
        "registry_version": template.get("registry_version", 1),
        "scoring_version": template.get("scoring_version", "geo-priority-v1"),
        "thinning_version": template.get("thinning_version", "freshness-area-cap-v1"),
        "generated_at": template.get("generated_at") if isinstance(template.get("generated_at"), str) else _iso(generated_at),
    }
    return projection


def _fresh_breaking_market_projection(
    breaking: dict[str, Any],
    generated_at: datetime,
) -> dict[str, Any] | None:
    if not _has_breaking_market_content(breaking):
        return None
    events = breaking.get("events")
    if not isinstance(events, list):
        return None
    current_events: list[dict[str, Any]] = []
    current_event_ids: set[str] = set()
    for event in events:
        if not isinstance(event, dict) or not _breaking_event_is_current(event, generated_at):
            continue
        event_id = event.get("event_id") or event.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            continue
        current_events.append(event)
        current_event_ids.add(event_id)
    if not current_events:
        return None
    map_points = [
        point
        for point in breaking.get("map_points", [])
        if isinstance(point, dict)
        and _valid_breaking_map_point(point, current_event_ids, generated_at)
    ]
    if not map_points:
        return None
    projection = json.loads(json.dumps(breaking))
    projection["events"] = current_events
    projection["map_points"] = map_points
    projection["shown_count"] = len(current_events)
    projection["total_count"] = len(current_events)
    return projection


def _breaking_event_is_current(event: dict[str, Any], generated_at: datetime) -> bool:
    published_at = _parse_public_timestamp(event.get("source_published_at"))
    if published_at is None:
        return False
    generated_at = _ensure_utc(generated_at)
    if published_at > generated_at + timedelta(minutes=5):
        return False
    return generated_at - published_at <= timedelta(hours=24)


def _valid_breaking_map_point(
    point: dict[str, Any],
    current_event_ids: set[str],
    generated_at: datetime,
) -> bool:
    try:
        latitude = float(point.get("latitude"))
        longitude = float(point.get("longitude"))
    except (TypeError, ValueError):
        return False
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return False
    if abs(latitude) < 0.0001 and abs(longitude) < 0.0001:
        return False
    point_published_at = point.get("source_published_at")
    if point_published_at is not None:
        parsed_point_time = _parse_public_timestamp(point_published_at)
        if parsed_point_time is None:
            return False
        generated_at = _ensure_utc(generated_at)
        if parsed_point_time > generated_at + timedelta(minutes=5):
            return False
        if generated_at - parsed_point_time > timedelta(hours=24):
            return False
    event_ids = point.get("event_ids")
    if not isinstance(event_ids, list):
        event_ids = [point.get("event_id")]
    return any(isinstance(event_id, str) and event_id in current_event_ids for event_id in event_ids)


def _parse_public_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _ensure_utc(parsed)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _valid_public_event_geo(event: dict[str, Any]) -> bool:
    try:
        latitude = float(event.get("latitude"))
        longitude = float(event.get("longitude"))
    except (TypeError, ValueError):
        return False
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return False
    if abs(latitude) < 0.0001 and abs(longitude) < 0.0001:
        return False
    return bool(event.get("country_region_keys"))


def _apply_news_collection_snapshot(
    snapshot: dict[str, Any], object_key: str, object_type: str, news_data: dict[str, Any]
) -> None:
    collection_key = object_type.removeprefix("news_") + "s"
    key = object_key.removeprefix(f"{object_type}_")
    snapshot["data"] = news_data.get(collection_key, {}).get(key, snapshot["data"])


def _versioned_snapshot_path(
    version: int, locale: str, source_path: str, seed_manifest: dict[str, Any]
) -> Path:
    seed_relative = Path(source_path).relative_to(
        f"public/v{seed_manifest['current_version']}/{locale}"
    )
    return Path(f"v{version}") / locale / seed_relative


def _write_snapshot(
    output_root: Path,
    snapshot: dict[str, Any],
    manifest: dict[str, Any],
    files: list[Path],
    *,
    object_key: str,
    locale: str,
    rel: Path,
) -> None:
    snapshot["content_hash"] = _payload_hash(snapshot["data"])
    target = output_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
    _validate_snapshot_file(target)
    manifest["objects"].setdefault(object_key, {})[locale] = f"public/{rel.as_posix()}"
    files.append(target)


def _write_news_event_snapshots(
    output_root: Path,
    manifest: dict[str, Any],
    files: list[Path],
    context: SnapshotTreeContext,
) -> None:
    for locale, news_data in context.db_news_by_locale.items():
        if not news_data or locale not in context.news_event_templates:
            continue
        for event_id, event_data in news_data.get("events", {}).items():
            object_key = f"news_event_{event_id}"
            if locale in manifest["objects"].get(object_key, {}):
                continue
            snapshot = json.loads(json.dumps(context.news_event_templates[locale]))
            snapshot["object_key"] = object_key
            snapshot["data"] = event_data
            _write_snapshot(
                output_root,
                snapshot,
                manifest,
                files,
                object_key=object_key,
                locale=locale,
                rel=Path(f"v{context.version}") / locale / "news" / "events" / f"{event_id}.json",
            )


def _published_home_macro_tiles() -> dict[str, dict[str, dict[str, Any]]]:
    previous: dict[str, dict[str, dict[str, Any]]] = {}
    for locale, snapshot in _published_home_snapshots():
        tiles = snapshot.get("data", {}).get("macro_tiles", [])
        if not isinstance(tiles, list):
            continue
        previous[str(locale)] = {
            str(tile["key"]): tile
            for tile in tiles
            if isinstance(tile, dict) and isinstance(tile.get("key"), str)
        }
    return previous


def _published_home_breaking_market() -> dict[str, dict[str, Any]]:
    previous: dict[str, dict[str, Any]] = {}
    for locale, snapshot in _published_home_snapshots():
        breaking = _home_breaking_market(snapshot)
        if breaking is not None and _has_breaking_market_content(breaking):
            previous[locale] = breaking
    return previous


def _published_home_snapshots() -> list[tuple[str, dict[str, Any]]]:
    manifest_path = PUBLISHED_ROOT / LATEST_MANIFEST_PATH
    if not manifest_path.exists():
        return []
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError:
        return []
    home_paths = manifest.get("objects", {}).get("home", {})
    if not isinstance(home_paths, dict):
        return []
    snapshots: list[tuple[str, dict[str, Any]]] = []
    for locale, home_path in home_paths.items():
        if not isinstance(home_path, str):
            continue
        snapshot_path = _public_snapshot_path(PUBLISHED_ROOT, home_path)
        if not snapshot_path.exists():
            continue
        try:
            snapshot = json.loads(snapshot_path.read_text())
        except json.JSONDecodeError:
            continue
        if isinstance(snapshot, dict):
            snapshots.append((str(locale), snapshot))
    return snapshots


def _home_breaking_market(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    data = snapshot.get("data", {})
    if not isinstance(data, dict):
        return None
    breaking = data.get("breaking_market_map")
    if not isinstance(breaking, dict):
        return None
    if not isinstance(breaking.get("events"), list) and isinstance(data.get("breaking_market_events"), list):
        return {**breaking, "events": data["breaking_market_events"]}
    return breaking


def _apply_refresh_deltas(tiles: list[Any], previous_tiles: dict[str, dict[str, Any]]) -> None:
    if not previous_tiles:
        return
    for tile in tiles:
        if not isinstance(tile, dict):
            continue
        key = tile.get("key")
        if not isinstance(key, str):
            continue
        current = _metric_tile_number(tile)
        previous = _metric_tile_number(previous_tiles.get(key, {}))
        if current is None or previous is None:
            continue
        delta = current - previous
        tile["refresh_delta"] = delta
        if abs(previous) > 1e-12:
            tile["refresh_delta_percent"] = (delta / abs(previous)) * 100


def _metric_tile_number(tile: dict[str, Any]) -> float | None:
    value = tile.get("value")
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = _NUMBER_RE.search(value.replace("−", "-"))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _public_events(db: Session) -> dict[str, list[dict[str, Any]]]:
    rows = db.execute(
        text(
            """
            select e.id, e.event_key, e.event_type, e.severity, e.confidence, e.source_strength,
                   e.review_status, e.occurred_at, e.published_at, e.correction_status,
                   c.object_key as canonical_key,
                   s.locale, s.title, s.summary, s.why_it_matters, s.source_policy_versions
            from geo_event e
            join canonical_object c on c.id = e.canonical_object_id
            join content_summary s on s.source_object_id = e.canonical_object_id
            where e.public_status in ('public_candidate','published')
              and s.public_allowed = true
              and s.stale = false
              and s.review_status in ('approved','quality_gate_passed','editor_approved','owner_approved')
            order by coalesce(e.published_at, e.discovered_at) desc
            limit 100
            """
        )
    ).mappings().all()
    events: dict[str, list[dict[str, Any]]] = {"en": [], "ko": []}
    for row in rows:
        source_versions = row["source_policy_versions"] or []
        if isinstance(source_versions, str):
            source_versions = json.loads(source_versions)
        source_links = [
            {
                "label": item.get("source_key", "source"),
                "url": f"/{row['locale']}/source-policy",
                "source_key": item.get("source_key", "unknown"),
                "policy_version": item.get("policy_version", 1),
            }
            for item in source_versions
        ] or [{"label": "Source policy", "url": f"/{row['locale']}/source-policy", "source_key": "manual", "policy_version": 1}]
        events.setdefault(row["locale"], []).append(
            {
                "id": str(row["id"]),
                "title": row["title"],
                "summary": row["summary"],
                "why_it_matters": row["why_it_matters"],
                "occurred_at": _iso(row["occurred_at"] or datetime.now(timezone.utc)),
                "published_at": _iso(row["published_at"] or datetime.now(timezone.utc)),
                "country_region_keys": [],
                "sector_keys": [],
                "event_type": row["event_type"],
                "severity": row["severity"],
                "confidence": float(row["confidence"]),
                "source_strength": row["source_strength"],
                "freshness": "fresh",
                "evidence_count": 1,
                "latitude": 0,
                "longitude": 0,
                "affected_objects": [row["canonical_key"]],
                "source_links": source_links,
                "correction_status": row["correction_status"],
            }
        )
    return events


def _calendar_items(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select release_key, release_type, scheduled_at, scheduled_local_date,
                   timezone, time_precision, status
            from economic_release
            where status in ('scheduled','released','estimated')
              and (
                scheduled_local_date is null
                or scheduled_local_date >= current_date
              )
            order by scheduled_local_date nulls last, scheduled_at nulls last
            limit 200
            """
        )
    ).mappings().all()
    return [
        {
            "id": row["release_key"],
            "title": row["release_key"].replace("_", " "),
            "country_region_key": "unknown",
            "release_type": row["release_type"],
            "scheduled_at": _iso(row["scheduled_at"]) if row["scheduled_at"] else None,
            "scheduled_local_date": str(row["scheduled_local_date"] or datetime.now(timezone.utc).date()),
            "timezone": row["timezone"],
            "time_precision": row["time_precision"],
            "status": row["status"],
            "expectation_type": "unknown",
            "expectation_value": None,
            "actual_value": None,
            "previous_value": None,
            "surprise": None,
            "source": "canonical_db",
            "freshness": "fresh",
        }
        for row in rows
    ]


def _sort_calendar_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=_calendar_sort_key)


def _calendar_sort_key(item: dict[str, Any]) -> tuple[str, str]:
    date_text = str(item.get("scheduled_local_date") or "")
    if not date_text and isinstance(item.get("scheduled_at"), str):
        date_text = str(item["scheduled_at"])[:10]
    scheduled_at = str(item.get("scheduled_at") or "")
    time_text = scheduled_at[11:19] if "T" in scheduled_at else ""
    return (date_text or "9999-12-31", time_text or "23:59:59", str(item.get("id") or ""))


def _source_status_data(db: Session, *, seed_status: dict[str, Any] | None = None) -> dict[str, Any]:
    providers_by_key = _provider_status_rows(db)
    for provider in (seed_status or {}).get("providers", []):
        _merge_seed_provider_status(providers_by_key, provider)
    providers = sorted(providers_by_key.values(), key=lambda provider: provider["provider_key"])
    operations = _operation_status_rows(db)
    return {
        "snapshot_age_minutes": 0,
        "degraded_mode": any(value in {"critical_warning", "degraded_read_only", "failed"} for value in operations.values()),
        "backend_required_for_public_pages": False,
        "providers": providers,
        "operations": {
            "disk_watermark": operations.get("disk_watermark", "unknown_until_monitor_runs"),
            "snapshot_storage_status": operations.get("snapshot_storage", "local_oci"),
            "backup_status": operations.get("backup", "local_encrypted_backups_not_configured"),
            "restore_drill_at": operations.get("restore_drill_at"),
        },
    }


def _provider_status_rows(db: Session) -> dict[str, dict[str, Any]]:
    rows = db.execute(
        text(
            """
            select provider_key, provider_type, routing_mode, kill_switch_enabled,
                   current_period_usage, hard_limit, last_verified_at
            from provider_budget
            order by provider_key
            """
        )
    ).mappings().all()
    return {
        row["provider_key"]: {
            "provider_key": row["provider_key"],
            "provider_type": row["provider_type"],
            "status": "kill_switch" if row["kill_switch_enabled"] else "ready",
            "mode": row["routing_mode"],
            "last_verified_at": _iso(row["last_verified_at"]) if row["last_verified_at"] else None,
            "warning": _provider_warning(row),
        }
        for row in rows
    }


def _merge_seed_provider_status(
    providers_by_key: dict[str, dict[str, Any]], provider: Any
) -> None:
    if not isinstance(provider, dict) or not isinstance(provider.get("provider_key"), str):
        return
    key = provider["provider_key"]
    existing = providers_by_key.get(key)
    if existing is None:
        providers_by_key[key] = _seed_provider_status(provider)
        return
    if provider.get("status") and provider.get("status") != "ready":
        existing["status"] = provider["status"]
    if provider.get("warning") and not existing.get("warning"):
        existing["warning"] = provider["warning"]
    if provider.get("provider_type") and existing.get("provider_type") in {None, "market_data"}:
        existing["provider_type"] = provider["provider_type"]


def _seed_provider_status(provider: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_key": provider["provider_key"],
        "provider_type": provider.get("provider_type", "unknown"),
        "status": provider.get("status", "ready"),
        "mode": provider.get("mode", "FREE_ONLY"),
        "last_verified_at": provider.get("last_verified_at"),
        "warning": provider.get("warning"),
    }


def _operation_status_rows(db: Session) -> dict[str, str]:
    return {
        row["status_key"]: row["status_value"]
        for row in db.execute(text("select status_key, status_value from operation_status")).mappings().all()
    }


def _corrections(db: Session) -> list[dict[str, Any]]:
    return [
        {
            "id": str(row["id"]),
            "title": row["title"],
            "status": row["status"],
            "published_at": _iso(row["published_at"]),
            "summary": row["summary"],
        }
        for row in db.execute(
            text(
                """
                select id, title, status, published_at, summary
                from correction_log
                order by published_at desc
                limit 200
                """
            )
        ).mappings().all()
    ]


def _assert_publication_gates(db: Session) -> None:
    stale = db.execute(
        text("select count(*) from content_translation where public_allowed = true and stale = true")
    ).scalar_one()
    if int(stale or 0):
        raise ValueError("Public snapshot rejected: stale translations cannot publish")
    bad_summaries = db.execute(
        text(
            """
            select count(*) from content_summary
            where public_allowed = true
              and (stale = true or jsonb_array_length(source_policy_versions) = 0)
            """
        )
    ).scalar_one()
    if int(bad_summaries or 0):
        raise ValueError("Public snapshot rejected: summaries must be fresh and source-policy bound")
    rows = db.execute(
        text(
            """
            select e.id, e.severity, e.source_strength, e.review_status,
                   bool_or(s.locale = 'en' and s.public_allowed and not s.stale) as has_en,
                   bool_or(s.locale = 'ko' and s.public_allowed and not s.stale) as has_ko
            from geo_event e
            left join content_summary s on s.source_object_id = e.canonical_object_id
            where e.public_status in ('public_candidate','published')
            group by e.id, e.severity, e.source_strength, e.review_status
            """
        )
    ).mappings().all()
    for row in rows:
        allowed, reason = can_publish_event(
            EventGateInput(
                severity=row["severity"],
                source_strength=row["source_strength"],
                review_status=row["review_status"],
                has_en_summary=bool(row["has_en"]),
                has_ko_summary=bool(row["has_ko"]),
                source_keys=["gdelt"] if row["source_strength"] in {"single_discovery", "weak"} else ["canonical"],
            )
        )
        if not allowed:
            raise ValueError(f"Public snapshot rejected for event {row['id']}: {reason}")


def _record_manifest(
    db: Session,
    manifest: dict[str, Any],
    manifest_path: Path,
    version: int,
    status: str,
    generated_by: str | None,
) -> None:
    db.execute(
        text(
            """
            insert into publication_manifest(
              snapshot_version, manifest_json, storage_object_key, content_hash,
              byte_size, generated_at, publication_status, generated_by
            )
            values (
              :snapshot_version, cast(:manifest_json as jsonb), :storage_object_key,
              :content_hash, :byte_size, :generated_at, :publication_status, :generated_by
            )
            on conflict (snapshot_version) do update
            set manifest_json = excluded.manifest_json,
                content_hash = excluded.content_hash,
                byte_size = excluded.byte_size,
                generated_at = excluded.generated_at,
                publication_status = excluded.publication_status,
                generated_by = excluded.generated_by
            """
        ),
        {
            "snapshot_version": version,
            "manifest_json": json.dumps(manifest),
            "storage_object_key": PUBLIC_LATEST_MANIFEST_KEY,
            "content_hash": _content_hash(manifest_path),
            "byte_size": manifest_path.stat().st_size,
            "generated_at": manifest["generated_at"],
            "publication_status": status,
            "generated_by": generated_by,
        },
    )


def _record_publication_rows(
    db: Session,
    files: list[Path],
    root: Path,
    generated_by: str | None,
    status: str,
) -> None:
    for file_path in files:
        if file_path.name == MANIFEST_FILENAME:
            continue
        data: dict[str, Any] = json.loads(file_path.read_text())
        db.execute(
            text(
                """
                insert into publication_snapshot(
                  snapshot_version, locale, object_type, object_key, schema_version,
                  storage_object_key, content_hash, byte_size, generated_at, stale_after,
                  hard_expires_at, source_policy_versions, publication_status, generated_by
                )
                values (
                  :snapshot_version, :locale, :object_type, :object_key, :schema_version,
                  :storage_object_key, :content_hash, :byte_size, :generated_at, :stale_after,
                  :hard_expires_at, cast(:source_policy_versions as jsonb), :publication_status, :generated_by
                )
                on conflict (snapshot_version, locale, object_type, object_key)
                do update set publication_status = excluded.publication_status,
                              content_hash = excluded.content_hash,
                              byte_size = excluded.byte_size
                """
            ),
            {
                "snapshot_version": data["snapshot_version"],
                "locale": data["locale"],
                "object_type": data["object_type"],
                "object_key": data["object_key"],
                "schema_version": data["schema_version"],
                "storage_object_key": f"public/{file_path.relative_to(root).as_posix()}",
                "content_hash": _content_hash(file_path),
                "byte_size": file_path.stat().st_size,
                "generated_at": data["generated_at"],
                "stale_after": data["stale_after"],
                "hard_expires_at": data["hard_expires_at"],
                "source_policy_versions": json.dumps(data.get("source_policy_versions", [])),
                "publication_status": status,
                "generated_by": generated_by,
            },
        )


def _publish_files_locally(files: list[Path], root: Path) -> None:
    PUBLISHED_ROOT.mkdir(parents=True, exist_ok=True)
    for file_path in sorted(files, key=lambda path: path.name == MANIFEST_FILENAME):
        rel = file_path.relative_to(root).as_posix()
        _copy_file_atomic(file_path, PUBLISHED_ROOT / rel)


def _copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_destination = destination.with_name(f".{destination.name}.tmp")
    shutil.copy2(source, temp_destination)
    temp_destination.replace(destination)


def _validate_snapshot_file(file_path: Path) -> None:
    if file_path.name == MANIFEST_FILENAME:
        return
    data = json.loads(file_path.read_text())
    schema_name = {
        "home": "home_snapshot.schema.json",
        "map_events": "map_events_snapshot.schema.json",
        "calendar_upcoming": "calendar_snapshot.schema.json",
        "country_region": "country_region_snapshot.schema.json",
        "sector_page": "sector_snapshot.schema.json",
        "scenario_basket": "scenario_basket_snapshot.schema.json",
        "source_status": "source_status_snapshot.schema.json",
        "correction_log": "correction_log_snapshot.schema.json",
        "news_index": "news_index_snapshot.schema.json",
        "news_event": "news_event_snapshot.schema.json",
        "news_ticker": "news_ticker_snapshot.schema.json",
        "news_region": "news_region_snapshot.schema.json",
        "news_topic": "news_topic_snapshot.schema.json",
        "reference_entity": "reference_entity_snapshot.schema.json",
        "fund_portfolio": "fund_portfolio_snapshot.schema.json",
    }.get(data.get("object_type"))
    if schema_name is None:
        raise ValueError(f"Unknown snapshot object_type: {data.get('object_type')}")
    schema_path = SCHEMA_DIR / schema_name
    schema = json.loads(schema_path.read_text())
    schema.setdefault("$id", schema_path.resolve().as_uri())
    Draft202012Validator(schema, registry=_snapshot_schema_registry()).validate(data)
    _assert_no_public_raw_private(data)


def _assert_no_public_raw_private(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in PROHIBITED_PUBLIC_FIELDS:
                raise ValueError(f"Public snapshot contains prohibited field {key}")
            _assert_no_public_raw_private(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_public_raw_private(nested)


def _snapshot_schema_registry() -> Registry:
    resources = []
    for path in SCHEMA_DIR.glob(JSON_FILE_GLOB):
        schema = json.loads(path.read_text())
        resources.append((path.resolve().as_uri(), Resource.from_contents(schema, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


def _manifest_row(
    db: Session,
    snapshot_version: int,
    allowed_status: tuple[str, ...] = ("candidate", "published"),
) -> dict[str, Any]:
    row = db.execute(
        text(
            """
            select *
            from publication_manifest
            where snapshot_version = :snapshot_version
            """
        ),
        {"snapshot_version": snapshot_version},
    ).mappings().first()
    if not row or row["publication_status"] not in allowed_status:
        raise ValueError(f"Snapshot version {snapshot_version} is not available for this operation")
    return dict(row)


def _next_snapshot_version(db: Session) -> int:
    return int(db.execute(text("select coalesce(max(snapshot_version), 0) + 1 from publication_manifest")).scalar_one())


def _map_filters(events: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "countries_regions": sorted({key for event in events for key in event.get("country_region_keys", [])}),
        "sectors": sorted({key for event in events for key in event.get("sector_keys", [])}),
        "severities": sorted({event["severity"] for event in events}),
        "event_types": sorted({event["event_type"] for event in events}),
    }


def _provider_warning(row: dict[str, Any]) -> str | None:
    if row["kill_switch_enabled"]:
        return "kill switch enabled"
    if row["hard_limit"] is not None and row["current_period_usage"] >= row["hard_limit"]:
        return "hard limit reached"
    return None


def _iso(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, datetime):
        value = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _payload_hash(payload: Any) -> str:
    return SHA256_PREFIX + hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _content_hash(file_path: Path) -> str:
    return SHA256_PREFIX + hashlib.sha256(file_path.read_bytes()).hexdigest()
