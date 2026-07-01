from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx
from selectolax.parser import HTMLParser

from fetch_sandbox.policy import assert_url_allowed, resolve_redirect

MAX_BYTES = int(os.getenv("SOURCE_FETCH_MAX_BYTES", "5000000"))
TIMEOUT = int(os.getenv("SOURCE_FETCH_TIMEOUT_SECONDS", "20"))
MAX_REDIRECTS = 5
SERVER_HOST = os.getenv("FETCH_SANDBOX_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("FETCH_SANDBOX_PORT", "8080"))


async def fetch(url: str) -> dict[str, Any]:
    current = url
    resolved_ips: set[str] = set()
    redirects = 0
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, trust_env=False) as client:
        while True:
            resolved_ips.update(assert_url_allowed(current))
            validated_url = str(httpx.URL(current))
            # assert_url_allowed and resolve_redirect enforce the SSRF boundary here.
            response = await client.get(validated_url, headers={"User-Agent": "FRWFetchSandbox/1.0"})  # NOSONAR
            if response.is_redirect:
                redirects += 1
                if redirects > MAX_REDIRECTS:
                    raise ValueError("Too many redirects")
                current = resolve_redirect(current, response.headers["location"])
                continue
            response.raise_for_status()
            body = await _read_capped(response)
            content_type = response.headers.get("content-type", "")
            extracted = _extract_document(body, content_type)
            return {
                "url": url,
                "final_url": str(response.url),
                "resolved_ips": sorted(resolved_ips),
                "status_code": response.status_code,
                "content_type": content_type,
                "content_hash": "sha256:" + hashlib.sha256(body).hexdigest(),
                "title": extracted["title"],
                "text": extracted["text"][:20_000],
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


def _extract_document(body: bytes, content_type: str) -> dict[str, str | None]:
    if "html" not in content_type:
        return {"title": None, "text": body[:20_000].decode(errors="replace")}

    parser = HTMLParser(body)
    title = _extract_title(parser)

    for node in parser.css("script,style,noscript,svg"):
        node.decompose()

    text = parser.body.text(separator=" ", strip=True) if parser.body else parser.text(separator=" ", strip=True)
    return {"title": title, "text": text}


def _extract_title(parser: HTMLParser) -> str | None:
    selectors = (
        'meta[property="og:title"]',
        'meta[name="twitter:title"]',
        "title",
        "h1",
    )

    for selector in selectors:
        node = parser.css_first(selector)
        if not node:
            continue
        value = node.attributes.get("content") if selector.startswith("meta") else node.text(strip=True)
        value = (value or "").strip()
        if value:
            return value[:500]

    return None


def main() -> None:
    if len(sys.argv) > 1:
        print(json.dumps(asyncio.run(fetch(sys.argv[1])), ensure_ascii=False))
        return
    server = ThreadingHTTPServer((SERVER_HOST, SERVER_PORT), FetchSandboxHandler)
    print(f"fetch-sandbox ready on {SERVER_HOST}:{SERVER_PORT}")
    server.serve_forever()


class FetchSandboxHandler(BaseHTTPRequestHandler):
    server_version = "FRWFetchSandbox/1.0"

    def do_GET(self) -> None:
        if self.path != "/health":
            self._write_json(404, {"detail": "not found"})
            return
        self._write_json(200, {"status": "ok", "service": "fetch-sandbox"})

    def do_POST(self) -> None:
        if self.path != "/fetch":
            self._write_json(404, {"detail": "not found"})
            return
        try:
            payload = self._read_json_body()
            url = str(payload.get("url") or "").strip()
            if not url:
                self._write_json(400, {"detail": "url is required"})
                return
            self._write_json(200, asyncio.run(fetch(url)))
        except Exception as exc:  # noqa: BLE001 - sandbox boundary returns denial details.
            self._write_json(400, {"detail": str(exc), "error_type": exc.__class__.__name__})

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length") or "0")
        if length <= 0 or length > 8192:
            raise ValueError("invalid request body")
        body = self.rfile.read(length)
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    main()
