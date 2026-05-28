from __future__ import annotations

import re
from typing import Any, Mapping


def build_summary(event: Mapping[str, Any], *, llm_enabled: bool = False) -> dict[str, Any]:
    title = _sanitize(str(event.get("title") or "News event"))
    facts = [_sanitize(str(item)) for item in event.get("known_facts", []) if str(item).strip()]
    tickers = [str(item) for item in event.get("affected_tickers", [])]
    regions = [str(item) for item in event.get("affected_regions", [])]
    summary = _template_summary(title, facts)
    return {
        "headline": title[:160],
        "one_sentence_summary": summary,
        "what_happened": facts[:3] or [title],
        "why_it_matters": [_sanitize(str(item)) for item in event.get("why_it_matters", [])][:3],
        "affected_tickers": tickers,
        "affected_regions": regions,
        "market_relevance": {
            "direction": str(event.get("market_direction") or "unclear"),
            "confidence": str(event.get("market_confidence") or "low"),
            "reasoning": _sanitize(str(event.get("market_reasoning") or "Insufficient evidence for directional market inference.")),
        },
        "known_facts": facts,
        "uncertainties": [_sanitize(str(item)) for item in event.get("uncertainties", [])][:5],
        "conflicting_reports": [_sanitize(str(item)) for item in event.get("conflicting_reports", [])][:5],
        "source_ids": [str(item) for item in event.get("source_ids", [])],
        "confidence": str(event.get("confidence_label") or "low"),
        "last_updated": str(event.get("last_updated") or ""),
        "summary_mode": "llm_disabled_fallback" if not llm_enabled else "llm_requested_not_run_in_public_path",
    }


def _template_summary(title: str, facts: list[str]) -> str:
    if facts:
        return f"{title}: {facts[0]}"
    return f"{title}: source-linked metadata is available, but no approved fact rows were supplied."


def _sanitize(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    text = re.sub(r"(?i)ignore previous instructions", "source text says: ignore previous instructions", text)
    text = re.sub(r"(?i)reveal (the )?system prompt", "mentions revealing a system prompt", text)
    return text
