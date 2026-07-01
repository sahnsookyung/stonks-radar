from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping


@dataclass(frozen=True)
class RegionClassification:
    key: str
    relation: str
    confidence: float


REGION_KEYWORDS = {
    "USA": ("united states", "u.s.", "us ", "federal reserve", "washington", "sec"),
    "CAN": ("canada", "canadian", "ottawa", "bank of canada", "alberta oil sands", "tsx"),
    "KOR": ("south korea", "korea", "seoul", "bank of korea", "samsung", "sk hynix"),
    "JPN": ("japan", "tokyo", "boj", "bank of japan"),
    "BRA": ("brazil", "brasil", "banco central do brasil", "copom"),
    "ZAF": ("south africa", "south african", "pretoria", "johannesburg", "eskom", "rand"),
    "EU": ("europe", "european union", "eurozone", "ecb"),
    "GBR": ("united kingdom", "uk ", "britain", "london", "bank of england"),
    "DEU": ("germany", "german", "berlin", "bundesbank", "ifo"),
    "FRA": ("france", "french", "paris", "bank of france", "edf"),
    "ITA": ("italy", "italian", "rome", "bank of italy"),
    "MEX": ("mexico", "mexican", "mexico city", "banxico"),
    "NOR": ("norway", "norwegian", "oslo", "norges bank", "equinor"),
    "IND": ("india", "indian", "new delhi", "mumbai", "reserve bank of india", "rbi"),
    "CHN": ("china", "beijing", "shanghai", "chinese"),
    "RUS": ("russia", "russian", "moscow", "kremlin", "putin"),
    "AUS": ("australia", "australian", "canberra", "sydney", "reserve bank of australia", "rba"),
    "ESP": ("spain", "spanish", "madrid", "bank of spain"),
    "IDN": ("indonesia", "indonesian", "jakarta", "bank indonesia"),
    "TUR": ("turkiye", "turkey", "turkish", "ankara", "central bank of turkey"),
    "SAU": ("saudi arabia", "saudi", "riyadh", "aramco", "opec"),
    "NLD": ("netherlands", "dutch", "amsterdam", "rotterdam"),
    "CHE": ("switzerland", "swiss", "zurich", "snb", "swiss national bank"),
    "POL": ("poland", "polish", "warsaw", "nbp", "national bank of poland"),
    "BEL": ("belgium", "belgian", "brussels"),
    "ARG": ("argentina", "argentine", "buenos aires", "milei"),
    "IRL": ("ireland", "irish", "dublin"),
    "SWE": ("sweden", "swedish", "stockholm", "riksbank"),
    "ARE": ("united arab emirates", "uae", "abu dhabi", "dubai"),
    "SGP": ("singapore", "mas", "monetary authority of singapore"),
    "ISR": ("israel", "israeli", "jerusalem", "tel aviv"),
    "AUT": ("austria", "austrian", "vienna"),
    "THA": ("thailand", "thai", "bangkok", "bank of thailand"),
}


def classify_regions(document: Mapping[str, object]) -> list[RegionClassification]:
    text = " ".join(str(document.get(key) or "") for key in ("title", "snippet", "summary", "body")).lower()
    classifications: dict[tuple[str, str], RegionClassification] = {}
    source_region = str(document.get("source_region") or "").upper()
    if source_region:
        classifications[(source_region, "source_region")] = RegionClassification(source_region, "source_region", 0.9)

    for key, keywords in REGION_KEYWORDS.items():
        if any(_keyword_matches(text, keyword) for keyword in keywords):
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


def _keyword_matches(text: str, keyword: str) -> bool:
    clean = keyword.strip().lower()
    if not clean:
        return False
    compact = clean.replace(".", "")
    if re.fullmatch(r"[a-z0-9.]+", clean) and len(compact) <= 4:
        return re.search(rf"(?<![a-z0-9]){re.escape(clean)}(?![a-z0-9])", text) is not None
    return clean in text
