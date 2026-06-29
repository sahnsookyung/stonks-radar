from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "config" / "geopolitical_watch_registry.json").is_file():
            return parent
    return current.parents[5]


REGISTRY_PATH = _repo_root() / "config" / "geopolitical_watch_registry.json"
MIN_GEO_CONFIDENCE = 0.7


@lru_cache(maxsize=1)
def registry_payload() -> dict[str, Any]:
    try:
        payload = json.loads(REGISTRY_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return _empty_registry()
    return _validate_registry(payload)


def registry_version() -> int:
    return int(registry_payload().get("version") or 1)


def registry_scoring_version() -> str:
    return str(registry_payload().get("scoring_version") or "geo-priority-v1")


def registry_thinning_version() -> str:
    return str(registry_payload().get("thinning_version") or "freshness-area-cap-v1")


def match_geo_points(
    *,
    texts: Iterable[str],
    region_keys: Iterable[str] = (),
    topic_keys: Iterable[str] = (),
    max_points: int = 4,
) -> list[dict[str, Any]]:
    normalized_text = " ".join(text.lower() for text in texts if text).strip()
    explicit_region_keys = {str(key).upper() for key in region_keys if str(key).strip()}
    topics = {str(key).lower() for key in topic_keys if str(key).strip()}
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for area in registry_payload()["areas"]:
        score, reason_codes = _area_score(area, normalized_text, explicit_region_keys, topics)
        if score < MIN_GEO_CONFIDENCE or area["key"] in seen:
            continue
        seen.add(area["key"])
        matches.append(
            {
                "point_id": f"geo_{area['key'].lower()}",
                "area_key": area["key"],
                "area_label": area["name"],
                "relation": "chokepoint" if area["kind"] == "chokepoint" else "event_location",
                "latitude": area["latitude"],
                "longitude": area["longitude"],
                "geo_confidence": round(score, 3),
                "market_themes": area["market_themes"],
                "area_priority": int(area["base_market_weight"]),
                "score_reason_codes": reason_codes,
            }
        )
    matches.sort(key=lambda item: (item["area_priority"], item["geo_confidence"], item["area_key"]), reverse=True)
    return matches[:max_points]


def _area_score(area: dict[str, Any], text: str, region_keys: set[str], topics: set[str]) -> tuple[float, list[str]]:
    score = 0.0
    reason_codes: list[str] = []
    if area["key"] in region_keys:
        score += 0.85
        reason_codes.append("explicit_region")
    for alias in area["aliases"]:
        if _alias_matches(text, alias):
            score += 0.82 if area["kind"] == "chokepoint" else 0.72
            reason_codes.append("alias_match")
            break
    theme_hits = {theme for theme in area["market_themes"] if theme.lower() in topics or theme.lower() in text}
    if theme_hits:
        score += min(0.18, 0.06 * len(theme_hits))
        reason_codes.append("market_theme")
    if area["kind"] == "chokepoint" and any(term in text for term in ("shipping", "oil", "lng", "freight", "strait", "canal")):
        score += 0.08
        reason_codes.append("chokepoint_context")
    return min(1.0, score), reason_codes


def _alias_matches(text: str, alias: str) -> bool:
    if not alias:
        return False
    if re.fullmatch(r"[a-z0-9 ]+", alias):
        return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text) is not None
    return alias in text


def _validate_registry(payload: dict[str, Any]) -> dict[str, Any]:
    areas = []
    for raw in payload.get("areas", []):
        area = _validated_registry_area(raw)
        if area is not None:
            areas.append(area)
    return {
        "version": int(payload.get("version") or 1),
        "scoring_version": str(payload.get("scoring_version") or "geo-priority-v1"),
        "thinning_version": str(payload.get("thinning_version") or "freshness-area-cap-v1"),
        "areas": areas,
        "query_packs": payload.get("query_packs", []),
    }


def _validated_registry_area(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or "").upper().strip()
    name = str(raw.get("name") or "").strip()
    aliases = [str(alias).lower().strip() for alias in raw.get("aliases", []) if str(alias).strip()]
    if not key or not name or not aliases:
        return None
    coordinates = _registry_coordinates(raw)
    if coordinates is None:
        return None
    latitude, longitude, weight = coordinates
    return {
        "key": key,
        "kind": "chokepoint" if str(raw.get("kind") or "country") == "chokepoint" else "country",
        "name": name,
        "aliases": aliases,
        "latitude": latitude,
        "longitude": longitude,
        "base_market_weight": max(0, min(100, weight)),
        "market_themes": [str(theme).strip() for theme in raw.get("market_themes", []) if str(theme).strip()],
    }


def _registry_coordinates(raw: dict[str, Any]) -> tuple[float, float, int] | None:
    try:
        latitude = float(raw.get("latitude"))
        longitude = float(raw.get("longitude"))
        weight = int(raw.get("base_market_weight") or 50)
    except (TypeError, ValueError):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    if abs(latitude) < 0.0001 and abs(longitude) < 0.0001:
        return None
    return latitude, longitude, weight


def _empty_registry() -> dict[str, Any]:
    return {
        "version": 1,
        "scoring_version": "geo-priority-v1",
        "thinning_version": "freshness-area-cap-v1",
        "areas": [],
        "query_packs": [],
    }
