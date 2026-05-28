from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from frw_api.core.settings import get_settings
from frw_api.services.fetch_policy import evaluate_url, is_blocked_ip, redirect_url

MAX_REDIRECTS = 5


class SafeFetchError(ValueError):
    pass


@dataclass(frozen=True)
class SafeFetchResult:
    body: bytes
    response: httpx.Response
    final_url: str
    resolved_ips: list[str]


async def safe_fetch_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    max_bytes: int | None = None,
    timeout_seconds: int | None = None,
    raise_for_status: bool = True,
) -> SafeFetchResult:
    settings = get_settings()
    current_url = url
    all_resolved_ips: set[str] = set()
    redirects = 0
    async with httpx.AsyncClient(
        timeout=timeout_seconds or settings.source_fetch_timeout_seconds,
        follow_redirects=False,
        headers=headers or {"User-Agent": settings.sec_user_agent},
        trust_env=False,
        transport=transport,
    ) as client:
        while True:
            decision = evaluate_url(current_url)
            if not decision.allowed:
                raise SafeFetchError(decision.reason)
            all_resolved_ips.update(decision.resolved_ips)
            async with client.stream("GET", current_url) as response:
                _validate_peer_ip(response)
                if response.is_redirect:
                    redirects += 1
                    if redirects > MAX_REDIRECTS:
                        raise SafeFetchError("Too many redirects")
                    location = response.headers.get("location")
                    if not location:
                        raise SafeFetchError("Redirect response missing Location header")
                    current_url = redirect_url(current_url, location)
                    continue
                if raise_for_status:
                    response.raise_for_status()
                body = await _read_limited(response, max_bytes or settings.source_fetch_max_bytes)
                return SafeFetchResult(
                    body=body,
                    response=_materialized_response(response, body),
                    final_url=str(response.url or current_url),
                    resolved_ips=sorted(all_resolved_ips),
                )


async def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise SafeFetchError("Response exceeded SOURCE_FETCH_MAX_BYTES")
        chunks.append(chunk)
    return b"".join(chunks)


def _materialized_response(response: httpx.Response, body: bytes) -> httpx.Response:
    return httpx.Response(
        response.status_code,
        headers=response.headers,
        content=body,
        request=response.request,
        extensions=response.extensions,
    )


def _validate_peer_ip(response: httpx.Response) -> None:
    peer_ip = _peer_ip(response.extensions)
    if peer_ip and is_blocked_ip(peer_ip):
        raise SafeFetchError(f"Private or metadata peer IP blocked: {peer_ip}")


def _peer_ip(extensions: dict[str, Any]) -> str | None:
    explicit = extensions.get("peer_ip")
    if isinstance(explicit, str):
        return explicit
    peername = extensions.get("peername")
    if isinstance(peername, tuple) and peername:
        return str(peername[0])
    stream = extensions.get("network_stream")
    getter = getattr(stream, "get_extra_info", None)
    if callable(getter):
        for key in ("peername", "socket"):
            try:
                value = getter(key)
            except Exception:  # noqa: BLE001 - transport-specific introspection is best effort
                continue
            if isinstance(value, tuple) and value:
                return str(value[0])
            getpeername = getattr(value, "getpeername", None)
            if callable(getpeername):
                try:
                    sock_peer = getpeername()
                except Exception:  # noqa: BLE001 - transport-specific introspection is best effort
                    continue
                if isinstance(sock_peer, tuple) and sock_peer:
                    return str(sock_peer[0])
    return None
