import gzip

from frw_api.services.fetch_policy import evaluate_url
from frw_api.services.safe_fetch import SafeFetchError, safe_fetch_bytes
from frw_api.services.source_ingestion import SourceIngestionError, fetch_source_bytes

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
