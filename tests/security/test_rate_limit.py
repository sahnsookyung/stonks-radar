from types import SimpleNamespace

from frw_api.services.rate_limit import _allow_memory, _client_identity


def test_memory_rate_limit_blocks_after_limit():
    key = "unit-test-rate-limit"
    assert _allow_memory(key, 2)
    assert _allow_memory(key, 2)
    assert not _allow_memory(key, 2)


def test_client_identity_prefers_cloudflare_connecting_ip():
    request = SimpleNamespace(
        headers={"cf-connecting-ip": "203.0.113.10", "x-forwarded-for": "198.51.100.20"},
        client=SimpleNamespace(host="172.18.0.8"),
    )

    assert _client_identity(request) == "203.0.113.10"


def test_client_identity_uses_first_valid_forwarded_for():
    request = SimpleNamespace(
        headers={"x-forwarded-for": "bad-value, 198.51.100.20, 172.18.0.8"},
        client=SimpleNamespace(host="172.18.0.8"),
    )

    assert _client_identity(request) == "198.51.100.20"


def test_client_identity_falls_back_to_socket_peer():
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="172.18.0.8"))

    assert _client_identity(request) == "172.18.0.8"
