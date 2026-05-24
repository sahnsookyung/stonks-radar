from frw_api.services.publication_gate import EventGateInput, can_publish_event


def test_gdelt_discovery_cannot_publish_high_confidence_alone():
    allowed, reason = can_publish_event(
        EventGateInput(
            severity="high",
            source_strength="weak",
            review_status="editor_approved",
            has_en_summary=True,
            has_ko_summary=True,
            source_keys=["gdelt"],
        )
    )
    assert not allowed
    assert "GDELT" in reason


def test_high_event_requires_editor_and_strong_source():
    allowed, _ = can_publish_event(
        EventGateInput(
            severity="high",
            source_strength="strong",
            review_status="editor_approved",
            has_en_summary=True,
            has_ko_summary=True,
            source_keys=["sec_edgar"],
        )
    )
    assert allowed
