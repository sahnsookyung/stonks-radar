from __future__ import annotations

import hashlib
import ipaddress
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import redis.asyncio as redis
from fastapi import Request, Response

from frw_api.core.settings import get_settings

WINDOW_SECONDS = 60
MAX_MEMORY_BUCKETS = 10_000
MEMORY_BUCKET_CLEANUP_INTERVAL_SECONDS = 30
_memory_buckets: dict[str, tuple[int, float]] = {}
_last_memory_cleanup_at = 0.0
_redis_client: redis.Redis | None = None


@dataclass(frozen=True)
class RateLimit:
    key: str
    limit: int


async def rate_limit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    limit = _limit_for_request(request)
    if limit is not None and not await _allow(limit, request):
        return Response("Rate limit exceeded", status_code=429)
    return await call_next(request)


def _limit_for_request(request: Request) -> RateLimit | None:
    settings = get_settings()
    path = request.url.path
    if path == "/api/auth/login":
        return RateLimit("auth-login", max(5, settings.admin_api_rate_limit_per_minute // 4))
    if path == "/api/instruments/review-requests" and request.method.upper() == "POST":
        return RateLimit("instrument-review-request", settings.instrument_review_ip_rate_limit_per_minute)
    if path.startswith("/api/instruments"):
        return RateLimit("instrument-autocomplete", settings.instrument_autocomplete_ip_rate_limit_per_minute)
    if path.startswith(("/api/admin", "/api/auth")):
        return RateLimit("admin", settings.admin_api_rate_limit_per_minute)
    if path.startswith("/api/public"):
        return RateLimit("public", settings.public_api_rate_limit_per_minute)
    return None


async def _allow(limit: RateLimit, request: Request) -> bool:
    client_host = _client_identity(request)
    identity = hashlib.sha256(f"{limit.key}:{client_host}".encode()).hexdigest()
    bucket_key = f"frw:rate:{identity}:{int(time.time() // WINDOW_SECONDS)}"
    try:
        client = _get_redis_client()
        count = await client.incr(bucket_key)
        if count == 1:
            await client.expire(bucket_key, WINDOW_SECONDS)
        return int(count) <= limit.limit
    except Exception:
        return _allow_memory(bucket_key, limit.limit)


def _get_redis_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(get_settings().redis_url, encoding="utf-8", decode_responses=True)
    return _redis_client


def _client_identity(request: Request) -> str:
    peer = _valid_ip(request.client.host if request.client else None)
    if not peer or not _trusted_proxy_peer(peer):
        return peer or "unknown"

    trusted_networks = _trusted_proxy_networks()
    forwarded_for = request.headers.get("x-forwarded-for", "")
    for candidate in reversed([item.strip() for item in forwarded_for.split(",") if item.strip()]):
        forwarded_ip = _valid_ip(candidate)
        if forwarded_ip and not _ip_in_networks(forwarded_ip, trusted_networks):
            return forwarded_ip

    cf_ip = _valid_ip(request.headers.get("cf-connecting-ip"))
    if cf_ip and not _ip_in_networks(cf_ip, trusted_networks):
        return cf_ip

    return peer


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _trusted_proxy_peer(value: str) -> bool:
    return _ip_in_networks(value, _trusted_proxy_networks())


def _trusted_proxy_networks() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for raw_value in get_settings().trusted_proxy_cidrs.split(","):
        value = raw_value.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return networks


def _ip_in_networks(
    value: str,
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(ip in network for network in networks)


def _allow_memory(bucket_key: str, limit: int) -> bool:
    global _last_memory_cleanup_at
    now = time.time()
    if now - _last_memory_cleanup_at >= MEMORY_BUCKET_CLEANUP_INTERVAL_SECONDS:
        _cleanup_memory_buckets(now)
        _last_memory_cleanup_at = now
    if len(_memory_buckets) >= MAX_MEMORY_BUCKETS and bucket_key not in _memory_buckets:
        _evict_oldest_memory_bucket()
    count, expires_at = _memory_buckets.get(bucket_key, (0, now + WINDOW_SECONDS))
    if expires_at < now:
        count, expires_at = 0, now + WINDOW_SECONDS
    count += 1
    _memory_buckets[bucket_key] = (count, expires_at)
    return count <= limit


def _cleanup_memory_buckets(now: float) -> None:
    expired = [key for key, (_count, expires_at) in _memory_buckets.items() if expires_at < now]
    for key in expired:
        _memory_buckets.pop(key, None)


def _evict_oldest_memory_bucket() -> None:
    if not _memory_buckets:
        return
    oldest_key = min(_memory_buckets, key=lambda key: _memory_buckets[key][1])
    _memory_buckets.pop(oldest_key, None)
