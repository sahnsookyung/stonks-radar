from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from fetch_sandbox import server
from fetch_sandbox.policy import FetchDenied


def _install_mock_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
) -> dict[str, Any]:
    client_kwargs: dict[str, Any] = {}
    real_async_client = httpx.AsyncClient

    def client_factory(**kwargs: Any) -> httpx.AsyncClient:
        client_kwargs.update(kwargs)
        return real_async_client(**kwargs, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(server.httpx, "AsyncClient", client_factory)
    return client_kwargs


def test_fetch_validates_and_normalizes_url_before_request(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, str]] = []

    def fake_assert_url_allowed(url: str) -> list[str]:
        events.append(("validate", url))
        return ["93.184.216.34"]

    async def handler(request: httpx.Request) -> httpx.Response:
        events.append(("request", str(request.url)))
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/plain"},
            content=b"ok",
        )

    monkeypatch.setattr(server, "assert_url_allowed", fake_assert_url_allowed)
    client_kwargs = _install_mock_client(monkeypatch, handler)

    result = asyncio.run(server.fetch("https://example.com:443/path"))

    assert events == [
        ("validate", "https://example.com:443/path"),
        ("request", "https://example.com/path"),
    ]
    assert client_kwargs["trust_env"] is False
    assert result["resolved_ips"] == ["93.184.216.34"]


def test_fetch_returns_title_metadata_without_raw_html(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_assert_url_allowed(url: str) -> list[str]:
        assert url == "https://example.com/story"
        return ["93.184.216.34"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"""
            <html>
              <head>
                <title>Fallback title</title>
                <meta property="og:title" content="Source Linked Story">
              </head>
              <body>
                <script>window.secret = "not retained";</script>
                <h1>Visible headline</h1>
                <p>Visible story text</p>
              </body>
            </html>
            """,
        )

    monkeypatch.setattr(server, "assert_url_allowed", fake_assert_url_allowed)
    _install_mock_client(monkeypatch, handler)

    result = asyncio.run(server.fetch("https://example.com/story"))

    assert result["title"] == "Source Linked Story"
    assert result["raw_html_returned"] is False
    assert "Visible story text" in result["text"]
    assert "window.secret" not in result["text"]


def test_fetch_revalidates_redirect_target_before_request(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_urls: list[str] = []

    def fake_assert_url_allowed(url: str) -> list[str]:
        if "blocked.example" in url:
            raise FetchDenied("blocked redirect target")
        return ["93.184.216.34"]

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            request=request,
            headers={"location": "https://blocked.example/private"},
        )

    monkeypatch.setattr(server, "assert_url_allowed", fake_assert_url_allowed)
    monkeypatch.setattr(server, "resolve_redirect", lambda _base, location: location)
    _install_mock_client(monkeypatch, handler)

    with pytest.raises(FetchDenied, match="blocked redirect target"):
        asyncio.run(server.fetch("https://example.com/start"))

    assert requested_urls == ["https://example.com/start"]


def test_http_handler_exposes_health_and_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    writes: list[bytes] = []

    class DummyHandler(server.FetchSandboxHandler):
        def __init__(self, method: str, path: str, body: bytes = b"") -> None:
            self.command = method
            self.path = path
            self.request_version = "HTTP/1.1"
            self.headers = {"content-length": str(len(body))}
            self.rfile = type("Reader", (), {"read": lambda _reader, _length: body})()
            self.wfile = type("Writer", (), {"write": lambda _writer, chunk: writes.append(chunk)})()
            self.responses: list[int] = []
            self.response_headers: list[tuple[str, str]] = []

        def send_response(self, code: int, message: str | None = None) -> None:
            self.responses.append(code)

        def send_header(self, keyword: str, value: str) -> None:
            self.response_headers.append((keyword.lower(), value))

        def end_headers(self) -> None:
            return

    async def fake_fetch(url: str) -> dict[str, Any]:
        assert url == "https://example.com/story"
        return {
            "url": url,
            "final_url": url,
            "resolved_ips": ["93.184.216.34"],
            "status_code": 200,
            "content_type": "text/html",
            "content_hash": "sha256:test",
            "title": "Example Story",
            "text": "Example Story",
            "raw_html_returned": False,
        }

    monkeypatch.setattr(server, "fetch", fake_fetch)

    health = DummyHandler("GET", "/health")
    health.do_GET()
    assert health.responses == [200]

    request = json.dumps({"url": "https://example.com/story"}).encode()
    handler = DummyHandler("POST", "/fetch", request)
    handler.do_POST()

    assert handler.responses == [200]
    assert json.loads(writes[-1])["text"] == "Example Story"
