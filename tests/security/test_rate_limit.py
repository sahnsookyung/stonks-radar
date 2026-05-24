from frw_api.services.rate_limit import _allow_memory


def test_memory_rate_limit_blocks_after_limit():
    key = "unit-test-rate-limit"
    assert _allow_memory(key, 2)
    assert _allow_memory(key, 2)
    assert not _allow_memory(key, 2)
