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
    allow_http_hosts: set[str] | frozenset[str] | None = None,
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
            decision = evaluate_url(current_url, allow_http_hosts=allow_http_hosts)
            if not decision.allowed:
                raise SafeFetchError(decision.reason)
            all_resolved_ips.update(decision.resolved_ips)
            validated_url = str(httpx.URL(current_url))
            # evaluate_url, redirect_url, and _validate_peer_ip enforce the SSRF boundary here.
            async with client.stream("GET", validated_url) as response:  # NOSONAR
                _validate_peer_ip(response, require_peer_ip=transport is None)
                if response.is_redirect:
                    redirects += 1
                    current_url = _next_redirect_url(response, current_url, redirects)
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
    headers = httpx.Headers(response.headers)
    for decoded_header in ("content-encoding", "content-length"):
        if decoded_header in headers:
            del headers[decoded_header]
    return httpx.Response(
        response.status_code,
        headers=headers,
        content=body,
        request=response.request,
        extensions=response.extensions,
    )


def _validate_peer_ip(response: httpx.Response, *, require_peer_ip: bool = False) -> None:
    peer_ip = _peer_ip(response.extensions)
    if require_peer_ip and not peer_ip:
        raise SafeFetchError("Unable to validate peer IP for safe fetch")
    if peer_ip and is_blocked_ip(peer_ip):
        raise SafeFetchError(f"Private or metadata peer IP blocked: {peer_ip}")


def _next_redirect_url(response: httpx.Response, current_url: str, redirects: int) -> str:
    if redirects > MAX_REDIRECTS:
        raise SafeFetchError("Too many redirects")
    location = response.headers.get("location")
    if not location:
        raise SafeFetchError("Redirect response missing Location header")
    return redirect_url(current_url, location)


def _peer_ip(extensions: dict[str, Any]) -> str | None:
    explicit = extensions.get("peer_ip")
    if isinstance(explicit, str):
        return explicit
    peername = extensions.get("peername")
    if peer_ip := _tuple_peer_ip(peername):
        return peer_ip
    stream = extensions.get("network_stream")
    getter = getattr(stream, "get_extra_info", None)
    if callable(getter) and (peer_ip := _peer_ip_from_getter(getter)):
        return peer_ip
    return None


def _peer_ip_from_getter(getter: Any) -> str | None:
    for key in ("peername", "server_addr", "socket"):
        try:
            value = getter(key)
        except Exception:  # noqa: BLE001 - transport-specific introspection is best effort
            continue
        if peer_ip := _tuple_peer_ip(value):
            return peer_ip
        if peer_ip := _socket_peer_ip(value):
            return peer_ip
    return None


def _tuple_peer_ip(value: Any) -> str | None:
    return str(value[0]) if isinstance(value, tuple) and value else None


def _socket_peer_ip(value: Any) -> str | None:
    getpeername = getattr(value, "getpeername", None)
    if not callable(getpeername):
        return None
    try:
        return _tuple_peer_ip(getpeername())
    except Exception:  # noqa: BLE001 - transport-specific introspection is best effort
        return None
