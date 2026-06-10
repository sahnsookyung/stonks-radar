from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

from frw_api.services import snapshot_service


def test_snapshot_service_resolves_repo_assets() -> None:
    assert (snapshot_service.SCHEMA_DIR / "home_snapshot.schema.json").exists()
    assert (snapshot_service.WEB_PUBLIC / "latest" / "manifest.json").exists()
    assert str(snapshot_service.ROOT) in sys.path


def test_runtime_seed_preserves_fresh_packaged_breaking_market_when_runtime_is_empty(
    tmp_path: Path, monkeypatch
) -> None:
    now = datetime(2026, 6, 10, 6, 0, tzinfo=timezone.utc)
    event_time = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    packaged_root = tmp_path / "packaged" / "public"
    runtime_root = tmp_path / "runtime" / "public"
    for root in (packaged_root, runtime_root):
        (root / "latest").mkdir(parents=True)
        (root / "v1" / "en").mkdir(parents=True)
        manifest = {
            "locales": ["en"],
            "objects": {
                "home": {"en": "public/v1/en/home.json"},
                "map_events": {"en": "public/v1/en/map.json"},
            },
        }
        (root / "latest" / "manifest.json").write_text(json.dumps(manifest))
        empty = {"data": {"breaking_market_events": [], "breaking_market_map": {"events": [], "map_points": []}}}
        (root / "v1" / "en" / "home.json").write_text(json.dumps(empty))
        (root / "v1" / "en" / "map.json").write_text(json.dumps(empty))

    packaged_breaking = {
        "events": [{"event_id": "packaged-event", "source_published_at": event_time}],
        "map_points": [
            {
                "point_id": "packaged-point",
                "event_ids": ["packaged-event"],
                "latitude": 26.57,
                "longitude": 56.25,
                "source_published_at": event_time,
            }
        ],
        "shown_count": 1,
        "total_count": 1,
        "registry_version": 1,
        "scoring_version": "test",
        "thinning_version": "test",
    }
    packaged_home = json.loads((packaged_root / "v1" / "en" / "home.json").read_text())
    packaged_home["data"]["breaking_market_events"] = packaged_breaking["events"]
    packaged_home["data"]["breaking_market_map"] = packaged_breaking
    (packaged_root / "v1" / "en" / "home.json").write_text(json.dumps(packaged_home))

    monkeypatch.setattr(snapshot_service, "WEB_PUBLIC", packaged_root)

    snapshot_service._preserve_packaged_breaking_market_seed(runtime_root, now)

    runtime_home = json.loads((runtime_root / "v1" / "en" / "home.json").read_text())
    runtime_map = json.loads((runtime_root / "v1" / "en" / "map.json").read_text())
    assert runtime_home["data"]["breaking_market_events"][0]["event_id"] == "packaged-event"
    assert runtime_home["data"]["breaking_market_map"]["map_points"][0]["point_id"] == "packaged-point"
    assert runtime_map["data"]["breaking_market_events"][0]["event_id"] == "packaged-event"


def test_empty_runtime_breaking_market_does_not_erase_seed_projection() -> None:
    now = datetime(2026, 6, 10, 6, 0, tzinfo=timezone.utc)
    snapshot = {
        "data": {
            "breaking_market_events": [
                {
                    "event_id": "seed-event",
                    "source_published_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                }
            ],
            "breaking_market_map": {
                "events": [
                    {
                        "event_id": "seed-event",
                        "source_published_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    }
                ],
                "map_points": [
                    {
                        "point_id": "seed-point",
                        "event_ids": ["seed-event"],
                        "latitude": 26.57,
                        "longitude": 56.25,
                        "source_published_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    }
                ],
            },
        }
    }
    context = snapshot_service.SnapshotTreeContext(
        version=1,
        generated_at=now,
        corrections=[],
        db_events={},
        db_calendar=[],
        previous_macro_tiles={},
        previous_breaking_market={},
        db_news_by_locale={"en": {"breaking_market": {"events": [], "map_points": []}}},
        news_event_templates={},
    )

    snapshot_service._apply_breaking_market_data(snapshot, "en", context)

    assert snapshot["data"]["breaking_market_events"][0]["event_id"] == "seed-event"
    assert snapshot["data"]["breaking_market_map"]["map_points"][0]["point_id"] == "seed-point"


def test_populated_runtime_breaking_market_replaces_seed_projection() -> None:
    now = datetime(2026, 6, 10, 6, 0, tzinfo=timezone.utc)
    runtime_breaking = {
        "events": [
            {
                "event_id": "runtime-event",
                "source_published_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            }
        ],
        "map_points": [
            {
                "point_id": "runtime-point",
                "event_ids": ["runtime-event"],
                "latitude": 26.57,
                "longitude": 56.25,
                "source_published_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            }
        ],
        "shown_count": 1,
        "total_count": 1,
    }
    snapshot = {
        "data": {
            "breaking_market_events": [{"event_id": "seed-event"}],
            "breaking_market_map": {
                "events": [{"event_id": "seed-event"}],
                "map_points": [{"point_id": "seed-point"}],
            },
        }
    }
    context = snapshot_service.SnapshotTreeContext(
        version=1,
        generated_at=now,
        corrections=[],
        db_events={},
        db_calendar=[],
        previous_macro_tiles={},
        previous_breaking_market={},
        db_news_by_locale={"en": {"breaking_market": runtime_breaking}},
        news_event_templates={},
    )

    snapshot_service._apply_breaking_market_data(snapshot, "en", context)

    assert snapshot["data"]["breaking_market_events"][0]["event_id"] == "runtime-event"
    assert snapshot["data"]["breaking_market_map"] == runtime_breaking


def test_fresh_previous_breaking_market_fills_empty_runtime_and_seed_projection() -> None:
    now = datetime(2026, 6, 10, 6, 0, tzinfo=timezone.utc)
    previous_breaking = {
        "events": [
            {
                "event_id": "previous-event",
                "source_published_at": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            }
        ],
        "map_points": [
            {
                "point_id": "previous-point",
                "event_ids": ["previous-event"],
                "latitude": 26.57,
                "longitude": 56.25,
                "source_published_at": (now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
            }
        ],
        "shown_count": 1,
        "total_count": 1,
        "registry_version": "test",
        "scoring_version": "test",
        "thinning_version": "test",
    }
    snapshot = {"data": {"breaking_market_events": [], "breaking_market_map": {"events": [], "map_points": []}}}
    context = snapshot_service.SnapshotTreeContext(
        version=1,
        generated_at=now,
        corrections=[],
        db_events={},
        db_calendar=[],
        previous_macro_tiles={},
        previous_breaking_market={"en": previous_breaking},
        db_news_by_locale={"en": {"breaking_market": {"events": [], "map_points": []}}},
        news_event_templates={},
    )

    snapshot_service._apply_breaking_market_data(snapshot, "en", context)

    assert snapshot["data"]["breaking_market_events"][0]["event_id"] == "previous-event"
    assert snapshot["data"]["breaking_market_map"]["map_points"][0]["point_id"] == "previous-point"
    assert snapshot["data"]["breaking_market_map"]["shown_count"] == 1


def test_stale_previous_breaking_market_does_not_fill_empty_projection() -> None:
    now = datetime(2026, 6, 10, 6, 0, tzinfo=timezone.utc)
    previous_breaking = {
        "events": [
            {
                "event_id": "old-event",
                "source_published_at": (now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
            }
        ],
        "map_points": [
            {
                "point_id": "old-point",
                "event_ids": ["old-event"],
                "latitude": 26.57,
                "longitude": 56.25,
                "source_published_at": (now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
            }
        ],
    }
    snapshot = {"data": {"breaking_market_events": [], "breaking_market_map": {"events": [], "map_points": []}}}
    context = snapshot_service.SnapshotTreeContext(
        version=1,
        generated_at=now,
        corrections=[],
        db_events={},
        db_calendar=[],
        previous_macro_tiles={},
        previous_breaking_market={"en": previous_breaking},
        db_news_by_locale={"en": {"breaking_market": {"events": [], "map_points": []}}},
        news_event_templates={},
    )

    snapshot_service._apply_breaking_market_data(snapshot, "en", context)

    assert snapshot["data"]["breaking_market_events"] == []
    assert snapshot["data"]["breaking_market_map"] == {
        "events": [],
        "map_points": [],
        "shown_count": 0,
        "total_count": 0,
        "ranking_cutoff": None,
        "registry_version": 1,
        "scoring_version": "geo-priority-v1",
        "thinning_version": "freshness-area-cap-v1",
        "generated_at": "2026-06-10T06:00:00Z",
    }


def test_stale_seed_breaking_market_is_cleared_when_no_fresh_runtime_or_fallback() -> None:
    now = datetime(2026, 6, 10, 6, 0, tzinfo=timezone.utc)
    snapshot = {
        "data": {
            "breaking_market_events": [
                {
                    "event_id": "stale-seed-event",
                    "source_published_at": (now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
                }
            ],
            "breaking_market_map": {
                "events": [
                    {
                        "event_id": "stale-seed-event",
                        "source_published_at": (now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
                    }
                ],
                "map_points": [
                    {
                        "point_id": "stale-seed-point",
                        "event_ids": ["stale-seed-event"],
                        "latitude": 26.57,
                        "longitude": 56.25,
                        "source_published_at": (now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
                    }
                ],
                "registry_version": "test",
                "scoring_version": "test",
                "thinning_version": "test",
            },
        }
    }
    context = snapshot_service.SnapshotTreeContext(
        version=1,
        generated_at=now,
        corrections=[],
        db_events={},
        db_calendar=[],
        previous_macro_tiles={},
        previous_breaking_market={},
        db_news_by_locale={"en": {"breaking_market": {"events": [], "map_points": []}}},
        news_event_templates={},
    )

    snapshot_service._apply_breaking_market_data(snapshot, "en", context)

    assert snapshot["data"]["breaking_market_events"] == []
    assert snapshot["data"]["breaking_market_map"] == {
        "events": [],
        "map_points": [],
        "shown_count": 0,
        "total_count": 0,
        "registry_version": "test",
        "scoring_version": "test",
        "thinning_version": "test",
        "ranking_cutoff": None,
        "generated_at": "2026-06-10T06:00:00Z",
    }


def test_previous_breaking_market_rejects_zero_coordinate_map_points() -> None:
    now = datetime(2026, 6, 10, 6, 0, tzinfo=timezone.utc)
    previous_breaking = {
        "events": [
            {
                "event_id": "bad-geo-event",
                "source_published_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            }
        ],
        "map_points": [
            {
                "point_id": "bad-point",
                "event_ids": ["bad-geo-event"],
                "latitude": 0,
                "longitude": 0,
                "source_published_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            }
        ],
    }
    snapshot = {"data": {"breaking_market_events": [], "breaking_market_map": {"events": [], "map_points": []}}}
    context = snapshot_service.SnapshotTreeContext(
        version=1,
        generated_at=now,
        corrections=[],
        db_events={},
        db_calendar=[],
        previous_macro_tiles={},
        previous_breaking_market={"en": previous_breaking},
        db_news_by_locale={"en": {"breaking_market": {"events": [], "map_points": []}}},
        news_event_templates={},
    )

    snapshot_service._apply_breaking_market_data(snapshot, "en", context)

    assert snapshot["data"]["breaking_market_events"] == []
    assert snapshot["data"]["breaking_market_map"] == {
        "events": [],
        "map_points": [],
        "shown_count": 0,
        "total_count": 0,
        "ranking_cutoff": None,
        "registry_version": 1,
        "scoring_version": "geo-priority-v1",
        "thinning_version": "freshness-area-cap-v1",
        "generated_at": "2026-06-10T06:00:00Z",
    }
