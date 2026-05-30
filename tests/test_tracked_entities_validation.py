from __future__ import annotations

import copy

from scripts import validate_tracked_entities


def test_tracked_entity_registry_validation_passes_for_current_config():
    assert validate_tracked_entities.validate_registry() == []


def test_tracked_entity_registry_rejects_non_https_source(monkeypatch):
    payload = copy.deepcopy(validate_tracked_entities._load_json(validate_tracked_entities.REGISTRY_PATH, []))
    payload["entities"][0]["sources"][0]["feed_url"] = "http://data.sec.gov/submissions/CIK0001849635.json"
    monkeypatch.setattr(validate_tracked_entities, "_load_json", lambda _path, _errors: payload)

    errors = validate_tracked_entities.validate_registry()

    assert any("invalid feed_url" in error for error in errors)


def test_tracked_entity_registry_rejects_unofficial_source_host(monkeypatch):
    payload = copy.deepcopy(validate_tracked_entities._load_json(validate_tracked_entities.REGISTRY_PATH, []))
    payload["entities"][1]["sources"][1]["feed_url"] = "https://example.com/press"
    monkeypatch.setattr(validate_tracked_entities, "_load_json", lambda _path, _errors: payload)

    errors = validate_tracked_entities.validate_registry()

    assert any("host is not in official domains" in error for error in errors)
