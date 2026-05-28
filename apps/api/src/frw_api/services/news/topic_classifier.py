from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class TopicClassification:
    key: str
    confidence: float


TOPIC_KEYWORDS = {
    "semiconductors": ("semiconductor", "chip", "ai accelerator", "memory", "foundry", "asml", "nvidia"),
    "central_banks": ("central bank", "fomc", "fed", "ecb", "boj", "bank of korea", "copom", "rate decision"),
    "rates": ("interest rate", "rate decision", "yield", "monetary policy"),
    "energy": ("oil", "brent", "wti", "opec", "eia", "lng", "gas"),
    "geopolitics": ("war", "sanction", "export control", "strait", "tariff", "geopolitical"),
    "trade_policy": ("export control", "tariff", "trade restriction", "customs"),
    "public_health": ("outbreak", "public health", "who", "cdc", "disease", "pandemic"),
    "pandemic": ("pandemic", "epidemic"),
    "supply_chain": ("supply chain", "shipment", "logistics", "chokepoint"),
    "space": ("launch", "rocket", "space", "mission"),
    "quantum": ("quantum", "qubit", "ion trap", "annealing", "superconducting", "fault-tolerant", "quantinuum", "d-wave"),
    "filings": ("form 4", "13d", "sec filing", "edgar", "prospectus"),
    "earnings": ("earnings", "revenue", "guidance"),
}


def classify_topics(document: Mapping[str, object]) -> list[TopicClassification]:
    text = " ".join(str(document.get(key) or "") for key in ("title", "snippet", "summary", "body")).lower()
    results: list[TopicClassification] = []
    for key, keywords in TOPIC_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword in text)
        if hits:
            results.append(TopicClassification(key, min(0.98, 0.45 + hits * 0.17)))
    return sorted(results, key=lambda item: item.confidence, reverse=True)
