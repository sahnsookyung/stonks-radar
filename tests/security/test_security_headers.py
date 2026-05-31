from __future__ import annotations

import asyncio

from starlette.requests import Request
from starlette.responses import Response

from frw_api.core.security_headers import security_headers_middleware


def test_security_headers_include_hsts_for_api_responses() -> None:
    request = Request(
        {"type": "http", "method": "GET", "path": "/api/public/health", "headers": []}
    )

    async def call_next(_request: Request) -> Response:
        return Response("ok")

    response = asyncio.run(security_headers_middleware(request, call_next))

    assert (
        response.headers["Strict-Transport-Security"]
        == "max-age=31536000; includeSubDomains; preload"
    )
    assert response.headers["X-Content-Type-Options"] == "nosniff"
