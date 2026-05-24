from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import redis.asyncio as redis
from fastapi import Request, Response

from frw_api.core.settings import get_settings

WINDOW_SECONDS = 60
_memory_buckets: dict[str, tuple[int, float]] = {}


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
    if path.startswith("/api/admin") or path.startswith("/api/auth"):
        return RateLimit("admin", settings.admin_api_rate_limit_per_minute)
    if path.startswith("/api/public"):
        return RateLimit("public", settings.public_api_rate_limit_per_minute)
    return None


async def _allow(limit: RateLimit, request: Request) -> bool:
    client_host = request.client.host if request.client else "unknown"
    identity = hashlib.sha256(f"{limit.key}:{client_host}".encode()).hexdigest()
    bucket_key = f"frw:rate:{identity}:{int(time.time() // WINDOW_SECONDS)}"
    try:
        client = redis.from_url(get_settings().redis_url, encoding="utf-8", decode_responses=True)
        count = await client.incr(bucket_key)
        if count == 1:
            await client.expire(bucket_key, WINDOW_SECONDS)
        await client.aclose()
        return int(count) <= limit.limit
    except Exception:
        return _allow_memory(bucket_key, limit.limit)


def _allow_memory(bucket_key: str, limit: int) -> bool:
    now = time.time()
    count, expires_at = _memory_buckets.get(bucket_key, (0, now + WINDOW_SECONDS))
    if expires_at < now:
        count, expires_at = 0, now + WINDOW_SECONDS
    count += 1
    _memory_buckets[bucket_key] = (count, expires_at)
    return count <= limit
