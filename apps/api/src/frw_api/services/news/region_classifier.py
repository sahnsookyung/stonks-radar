from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RegionClassification:
    key: str
    relation: str
    confidence: float


REGION_KEYWORDS = {
    "USA": ("united states", "u.s.", "us ", "federal reserve", "washington", "sec"),
    "KOR": ("south korea", "korea", "seoul", "bank of korea", "samsung", "sk hynix"),
    "JPN": ("japan", "tokyo", "boj", "bank of japan"),
    "BRA": ("brazil", "brasil", "banco central do brasil", "copom"),
    "EU": ("europe", "european union", "eurozone", "ecb"),
    "CHN": ("china", "beijing", "shanghai", "chinese"),
}


def classify_regions(document: Mapping[str, object]) -> list[RegionClassification]:
    text = " ".join(str(document.get(key) or "") for key in ("title", "snippet", "summary", "body")).lower()
    classifications: dict[tuple[str, str], RegionClassification] = {}
    source_region = str(document.get("source_region") or "").upper()
    if source_region:
        classifications[(source_region, "source_region")] = RegionClassification(source_region, "source_region", 0.9)

    for key, keywords in REGION_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            relation = "event_region"
            confidence = 0.72
            if any(term in text for term in ("affect", "impact", "supply chain", "exports", "sanctions")):
                relation = "affected_region"
                confidence = 0.68
            classifications[(key, relation)] = RegionClassification(key, relation, confidence)
            classifications.setdefault((key, "mentioned_region"), RegionClassification(key, "mentioned_region", 0.5))

    market_region = str(document.get("market_region") or "").upper()
    if market_region:
        classifications[(market_region, "market_region")] = RegionClassification(market_region, "market_region", 0.86)
    return sorted(classifications.values(), key=lambda item: (item.key, item.relation))
