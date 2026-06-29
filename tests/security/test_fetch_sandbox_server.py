from __future__ import annotations

import asyncio
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
