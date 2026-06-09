import gzip

from frw_api.services.fetch_policy import evaluate_url
from frw_api.services.safe_fetch import (
    MAX_REDIRECTS,
    SafeFetchError,
    _next_redirect_url,
    _peer_ip,
    _validate_peer_ip,
    safe_fetch_bytes,
)
from frw_api.services.source_ingestion import SourceIngestionError, _mode_for_url, fetch_source_bytes

import httpx
import pytest


def test_blocks_localhost():
    decision = evaluate_url("http://127.0.0.1:8000/private")
    assert not decision.allowed


def test_blocks_file_protocol():
    decision = evaluate_url("file:///etc/passwd")
    assert not decision.allowed


def test_blocks_metadata_ip():
    decision = evaluate_url("http://169.254.169.254/latest/meta-data")
    assert not decision.allowed


def test_sec_mode_requires_exact_sec_domain():
    assert _mode_for_url("https://data.sec.gov/submissions/CIK0000320193.json", "application/json") == "filing"
    assert _mode_for_url("https://www.sec.gov/Archives/edgar/data/1/doc.htm", "text/html") == "filing"
    assert _mode_for_url("https://sec.gov.evil.example/Archives/edgar/data/1/doc.htm", "text/html") == "public_web_fetch"
    assert _mode_for_url("https://user@sec.gov.evil.example/Archives/edgar/data/1/doc.htm", "text/html") == "public_web_fetch"


def test_blocks_multicast_ip():
    decision = evaluate_url("http://224.0.0.1/")
    assert not decision.allowed


def test_controlled_redirect_rechecks_target(monkeypatch):
    def fake_evaluate(url: str):
        if "private.local" in url:
            return type("Decision", (), {"allowed": False, "reason": "blocked private", "resolved_ips": ["10.0.0.1"]})()
        return type("Decision", (), {"allowed": True, "reason": "allowed", "resolved_ips": ["93.184.216.34"]})()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://private.local/secret"})

    monkeypatch.setattr("frw_api.services.safe_fetch.evaluate_url", fake_evaluate)
    with pytest.raises(SourceIngestionError, match="blocked private"):
        import asyncio

        asyncio.run(fetch_source_bytes("http://example.com", transport=httpx.MockTransport(handler)))


def test_safe_fetch_blocks_private_peer_ip(monkeypatch):
    def fake_evaluate(url: str):
        return type("Decision", (), {"allowed": True, "reason": "allowed", "resolved_ips": ["93.184.216.34"]})()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            content=b"blocked",
            extensions={"peer_ip": "127.0.0.1"},
        )

    monkeypatch.setattr("frw_api.services.safe_fetch.evaluate_url", fake_evaluate)
    with pytest.raises(SafeFetchError, match="Private or metadata peer IP blocked"):
        import asyncio

        asyncio.run(safe_fetch_bytes("https://example.com", transport=httpx.MockTransport(handler)))


def test_safe_fetch_requires_peer_ip_when_requested():
    response = httpx.Response(200, request=httpx.Request("GET", "https://example.com"))

    with pytest.raises(SafeFetchError, match="Unable to validate peer IP"):
        _validate_peer_ip(response, require_peer_ip=True)


def test_safe_fetch_accepts_server_addr_peer_extension():
    class FakeStream:
        def get_extra_info(self, key):
            if key == "server_addr":
                return ("93.184.216.34", 443)
            return None

    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com"),
        extensions={"network_stream": FakeStream()},
    )

    _validate_peer_ip(response, require_peer_ip=True)


def test_safe_fetch_accepts_peername_tuple_extension():
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com"),
        extensions={"peername": ("93.184.216.34", 443)},
    )

    _validate_peer_ip(response, require_peer_ip=True)


def test_safe_fetch_blocks_oversized_responses(monkeypatch):
    def fake_evaluate(url: str):
        return type("Decision", (), {"allowed": True, "reason": "allowed", "resolved_ips": ["93.184.216.34"]})()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, content=b"too large")

    monkeypatch.setattr("frw_api.services.safe_fetch.evaluate_url", fake_evaluate)

    import asyncio

    with pytest.raises(SafeFetchError, match="SOURCE_FETCH_MAX_BYTES"):
        asyncio.run(
            safe_fetch_bytes(
                "https://example.com",
                transport=httpx.MockTransport(handler),
                max_bytes=3,
            )
        )


def test_redirect_helper_rejects_loops_and_missing_location():
    response = httpx.Response(302, request=httpx.Request("GET", "https://example.com"))

    with pytest.raises(SafeFetchError, match="Too many redirects"):
        _next_redirect_url(response, "https://example.com", MAX_REDIRECTS + 1)
    with pytest.raises(SafeFetchError, match="missing Location"):
        _next_redirect_url(response, "https://example.com", 1)


def test_peer_ip_introspection_handles_socket_and_transport_errors():
    class ExplodingGetter:
        def getpeername(self):
            raise OSError("socket closed")

    class GetterStream:
        def __init__(self, value):
            self.value = value

        def get_extra_info(self, key):
            if key == "peername":
                raise RuntimeError("transport changed")
            if key == "socket":
                return self.value
            return None

    class SocketLike:
        def getpeername(self):
            return ("93.184.216.34", 443)

    assert _peer_ip({"network_stream": GetterStream(SocketLike())}) == "93.184.216.34"
    assert _peer_ip({"network_stream": GetterStream(ExplodingGetter())}) is None


def test_safe_fetch_materializes_decoded_response_without_double_decode(monkeypatch):
    def fake_evaluate(url: str):
        return type("Decision", (), {"allowed": True, "reason": "allowed", "resolved_ips": ["93.184.216.34"]})()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            headers={"content-encoding": "gzip", "content-length": "999"},
            content=gzip.compress(b"decoded body"),
        )

    monkeypatch.setattr("frw_api.services.safe_fetch.evaluate_url", fake_evaluate)

    import asyncio

    result = asyncio.run(safe_fetch_bytes("https://example.com", transport=httpx.MockTransport(handler)))

    assert result.body == b"decoded body"
    assert result.response.text == "decoded body"
    assert "content-encoding" not in result.response.headers
    assert result.response.headers["content-length"] == str(len(b"decoded body"))
