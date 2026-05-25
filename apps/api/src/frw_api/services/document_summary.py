from __future__ import annotations

import re
from typing import Any

from selectolax.parser import HTMLParser
from sqlalchemy.orm import Session

from frw_api.services.llm_router import LLMRouter, LLMTask
from frw_api.services.source_ingestion import fetch_source_bytes

DOCUMENT_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["title", "summary", "key_points", "limitations", "source_url"],
    "properties": {
        "title": {"type": "string", "maxLength": 240},
        "summary": {"type": "string", "maxLength": 1600},
        "key_points": {"type": "array", "items": {"type": "string", "maxLength": 320}, "minItems": 1, "maxItems": 6},
        "limitations": {"type": "array", "items": {"type": "string", "maxLength": 320}, "minItems": 1, "maxItems": 4},
        "source_url": {"type": "string"},
    },
    "additionalProperties": False,
}


async def summarize_public_url(db: Session, *, url: str, locale: str = "en") -> dict[str, Any]:
    fetched = await fetch_source_bytes(url)
    response = fetched["response"]
    body = fetched["body"]
    final_url = str(fetched["final_url"])
    content_type = response.headers.get("content-type", "") if hasattr(response, "headers") else ""
    title, text = _extract_document_text(body, content_type)
    if len(text) < 160:
        raise ValueError("Document text is too short to summarize")
    excerpt = text[:18_000]
    router = LLMRouter(db)
    task = LLMTask(
        task_type="document_summary",
        input_class="PUBLIC_SOURCE_TEXT",
        prompt_version="document_summary_v1",
        schema_key="document_summary",
        schema=DOCUMENT_SUMMARY_SCHEMA,
        locale=locale,
    )
    return await router.run_json(
        task,
        messages=[
            {
                "role": "system",
                "content": (
                    "Summarize only the supplied public-source document text. "
                    "Return JSON matching the schema. Do not provide financial advice, predictions, or uncited claims. "
                    "Use limitations to name missing context, weak source quality, or extraction limits."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Locale: {locale}\n"
                    f"Source URL: {final_url}\n"
                    f"Title: {title}\n\n"
                    f"Document excerpt:\n{excerpt}"
                ),
            },
        ],
    )


def _extract_document_text(body: object, content_type: str) -> tuple[str, str]:
    if isinstance(body, bytes):
        raw = body
    elif isinstance(body, str):
        raw = body.encode()
    else:
        raw = bytes(body)
    if "html" in content_type.lower():
        parser = HTMLParser(raw)
        title_node = parser.css_first("title") or parser.css_first("h1")
        title = title_node.text(strip=True) if title_node else "Source document"
        for node in parser.css("script,style,noscript,svg,nav,footer"):
            node.decompose()
        text = parser.body.text(separator=" ", strip=True) if parser.body else parser.text(separator=" ", strip=True)
        return title[:240], _clean_text(text)
    text = raw.decode("utf-8", errors="ignore")
    if "json" in content_type.lower():
        title = "JSON source document"
    elif "xml" in content_type.lower():
        title = "XML source document"
    else:
        title = "Source document"
    return title, _clean_text(text)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
