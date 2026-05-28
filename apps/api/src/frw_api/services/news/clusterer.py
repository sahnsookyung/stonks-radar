from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


def cluster_documents(documents: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for document in documents:
        groups[_cluster_key(document)].append(document)
    clusters: list[dict[str, Any]] = []
    for key, rows in groups.items():
        timestamps = [_published_at(row) for row in rows]
        timestamps = [value for value in timestamps if value is not None]
        clusters.append(
            {
                "id": f"news_{hashlib.sha1(key.encode()).hexdigest()[:16]}",
                "document_count": len(rows),
                "documents": list(rows),
                "first_seen_at": min(timestamps).isoformat() if timestamps else None,
                "last_seen_at": max(timestamps).isoformat() if timestamps else None,
            }
        )
    return sorted(clusters, key=lambda cluster: cluster["document_count"], reverse=True)


def _cluster_key(document: Mapping[str, Any]) -> str:
    title = _normalized_title(str(document.get("title") or ""))
    event_type = str(document.get("event_type") or "").lower()
    region = str(document.get("event_region") or document.get("source_region") or "").upper()
    entities = _entity_key(document)
    published = _published_at(document)
    date_bucket = published.date().isoformat() if published else ""
    if event_type or region or entities:
        return f"event:{event_type}|{region}|{entities}|{date_bucket}|{_title_signature(title)}"
    canonical_url = str(document.get("canonical_url") or document.get("url") or "").strip().lower()
    if canonical_url:
        return f"url:{canonical_url}"
    return f"title:{title}"


def _normalized_title(title: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", title.lower())
    stop = {"the", "a", "an", "to", "of", "and", "for", "in", "on", "with"}
    return " ".join(token for token in tokens if token not in stop)[:120]


def _title_signature(title: str) -> str:
    tokens = title.split()
    if len(tokens) <= 3:
        return title
    return " ".join(sorted(set(tokens))[:8])


def _entity_key(document: Mapping[str, Any]) -> str:
    raw_values = document.get("entities") or document.get("affected_tickers") or ()
    if not isinstance(raw_values, (list, tuple, set)):
        return ""
    values: list[str] = []
    for value in raw_values:
        if isinstance(value, Mapping):
            symbol = value.get("symbol") or value.get("entity_key")
        else:
            symbol = value
        normalized = str(symbol or "").strip().upper()
        if normalized:
            values.append(normalized)
    return ",".join(sorted(set(values)))


def _published_at(document: Mapping[str, Any]) -> datetime | None:
    value = document.get("published_at")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
