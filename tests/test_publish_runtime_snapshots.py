from __future__ import annotations

from scripts.publish_runtime_snapshots import _generated_by_uuid


def test_generated_by_uuid_accepts_uuid_only() -> None:
    assert _generated_by_uuid("550e8400-e29b-41d4-a716-446655440000") == "550e8400-e29b-41d4-a716-446655440000"
    assert _generated_by_uuid("direct-oci-deploy") is None
    assert _generated_by_uuid("") is None
