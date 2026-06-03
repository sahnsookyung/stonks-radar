from types import SimpleNamespace

import pytest

from frw_api.core.settings import get_settings
from frw_api.services import rate_limit
from frw_api.services.rate_limit import _allow_memory, _client_identity, _limit_for_request


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    rate_limit._memory_buckets.clear()
    yield
    rate_limit._memory_buckets.clear()
    get_settings.cache_clear()


def test_memory_rate_limit_blocks_after_limit():
    key = "unit-test-rate-limit"
    assert _allow_memory(key, 2)
    assert _allow_memory(key, 2)
    assert not _allow_memory(key, 2)


def test_memory_rate_limit_fallback_is_bounded(monkeypatch):
    monkeypatch.setattr(rate_limit, "MAX_MEMORY_BUCKETS", 2)
    monkeypatch.setattr(rate_limit, "_last_memory_cleanup_at", 0.0)

    assert _allow_memory("bucket-a", 1)
    assert _allow_memory("bucket-b", 1)
    assert len(rate_limit._memory_buckets) == 2
    assert _allow_memory("bucket-c", 1)

    assert len(rate_limit._memory_buckets) == 2
    assert "bucket-c" in rate_limit._memory_buckets


def test_instrument_autocomplete_has_dedicated_rate_limit(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "instrument_autocomplete_ip_rate_limit_per_minute", 17)
    request = SimpleNamespace(url=SimpleNamespace(path="/api/instruments/search"))

    limit = _limit_for_request(request)

    assert limit is not None
    assert limit.key == "instrument-autocomplete"
    assert limit.limit == 17


def test_client_identity_uses_rightmost_untrusted_forwarded_for():
    request = SimpleNamespace(
        headers={"cf-connecting-ip": "203.0.113.10", "x-forwarded-for": "198.51.100.20, 203.0.113.30"},
        client=SimpleNamespace(host="172.18.0.8"),
    )

    assert _client_identity(request) == "203.0.113.30"


def test_client_identity_ignores_forwarded_headers_from_untrusted_peer(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "127.0.0.1/32")
    request = SimpleNamespace(
        headers={"cf-connecting-ip": "203.0.113.10", "x-forwarded-for": "198.51.100.20"},
        client=SimpleNamespace(host="198.51.100.77"),
    )

    assert _client_identity(request) == "198.51.100.77"


def test_client_identity_falls_back_to_cloudflare_header_when_forwarded_for_missing():
    request = SimpleNamespace(
        headers={"cf-connecting-ip": "203.0.113.10"},
        client=SimpleNamespace(host="172.18.0.8"),
    )

    assert _client_identity(request) == "203.0.113.10"


def test_client_identity_falls_back_to_socket_peer():
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="172.18.0.8"))

    assert _client_identity(request) == "172.18.0.8"
