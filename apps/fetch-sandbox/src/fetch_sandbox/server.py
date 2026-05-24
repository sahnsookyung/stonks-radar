from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from typing import Any

import httpx
from selectolax.parser import HTMLParser

from fetch_sandbox.policy import assert_url_allowed, resolve_redirect

MAX_BYTES = int(os.getenv("SOURCE_FETCH_MAX_BYTES", "5000000"))
TIMEOUT = int(os.getenv("SOURCE_FETCH_TIMEOUT_SECONDS", "20"))
MAX_REDIRECTS = 5


async def fetch(url: str) -> dict[str, Any]:
    resolved_ips = assert_url_allowed(url)
    current = url
    redirects = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
        while True:
            response = await client.get(current, headers={"User-Agent": "FRWFetchSandbox/1.0"})
            if response.is_redirect:
                redirects += 1
                if redirects > MAX_REDIRECTS:
                    raise ValueError("Too many redirects")
                current = resolve_redirect(current, response.headers["location"])
                continue
            response.raise_for_status()
            body = await _read_capped(response)
            content_type = response.headers.get("content-type", "")
            text = _extract_text(body, content_type)
            return {
                "url": url,
                "final_url": str(response.url),
                "resolved_ips": resolved_ips,
                "status_code": response.status_code,
                "content_type": content_type,
                "content_hash": "sha256:" + hashlib.sha256(body).hexdigest(),
                "text": text[:20_000],
                "raw_html_returned": False,
            }


async def _read_capped(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > MAX_BYTES:
            raise ValueError("Response exceeded byte cap")
        chunks.append(chunk)
    return b"".join(chunks)


def _extract_text(body: bytes, content_type: str) -> str:
    if "html" not in content_type:
        return body[:20_000].decode(errors="replace")
    parser = HTMLParser(body)
    for node in parser.css("script,style,noscript,svg"):
        node.decompose()
    return parser.body.text(separator=" ", strip=True) if parser.body else parser.text(separator=" ", strip=True)


def main() -> None:
    if len(sys.argv) > 1:
        print(json.dumps(asyncio.run(fetch(sys.argv[1])), ensure_ascii=False))
        return
    print("fetch-sandbox ready; pass a URL argument for CLI fetch")


if __name__ == "__main__":
    main()
