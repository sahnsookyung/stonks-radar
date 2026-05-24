import pytest

from frw_api.services.snapshot_service import _assert_no_public_raw_private


@pytest.mark.parametrize("field", ["raw_html", "private_note", "restricted_source_text"])
def test_public_snapshot_rejects_prohibited_raw_fields(field):
    with pytest.raises(ValueError):
        _assert_no_public_raw_private({"data": [{field: "secret"}]})
