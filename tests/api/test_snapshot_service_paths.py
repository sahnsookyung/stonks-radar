from __future__ import annotations

from datetime import datetime, timezone
import sys

from frw_api.services import snapshot_service


def test_snapshot_service_resolves_repo_assets() -> None:
    assert (snapshot_service.SCHEMA_DIR / "home_snapshot.schema.json").exists()
    assert (snapshot_service.WEB_PUBLIC / "latest" / "manifest.json").exists()
    assert str(snapshot_service.ROOT) in sys.path


def test_empty_runtime_breaking_market_does_not_erase_seed_projection() -> None:
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
        generated_at=datetime.now(timezone.utc),
        corrections=[],
        db_events={},
        db_calendar=[],
        previous_macro_tiles={},
        db_news_by_locale={"en": {"breaking_market": {"events": [], "map_points": []}}},
        news_event_templates={},
    )

    snapshot_service._apply_breaking_market_data(snapshot, "en", context)

    assert snapshot["data"]["breaking_market_events"] == [{"event_id": "seed-event"}]
    assert snapshot["data"]["breaking_market_map"]["map_points"] == [{"point_id": "seed-point"}]


def test_populated_runtime_breaking_market_replaces_seed_projection() -> None:
    runtime_breaking = {
        "events": [{"event_id": "runtime-event"}],
        "map_points": [{"point_id": "runtime-point"}],
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
        generated_at=datetime.now(timezone.utc),
        corrections=[],
        db_events={},
        db_calendar=[],
        previous_macro_tiles={},
        db_news_by_locale={"en": {"breaking_market": runtime_breaking}},
        news_event_templates={},
    )

    snapshot_service._apply_breaking_market_data(snapshot, "en", context)

    assert snapshot["data"]["breaking_market_events"] == [{"event_id": "runtime-event"}]
    assert snapshot["data"]["breaking_market_map"] == runtime_breaking
