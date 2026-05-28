from __future__ import annotations

from typing import Final

TRUST_TIERS: Final[tuple[str, ...]] = (
    "T0_OFFICIAL",
    "T1_REGULATED_FILING",
    "T2_REPUTABLE_MEDIA",
    "T3_REVIEWED_PUBLIC_SOURCE",
    "T4_WEAK_SIGNAL",
    "T5_UNREVIEWED",
    "T6_BLOCKED",
)

REGION_RELATIONS: Final[tuple[str, ...]] = (
    "source_region",
    "event_region",
    "company_region",
    "affected_region",
    "market_region",
    "mentioned_region",
)

TOPICS: Final[tuple[str, ...]] = (
    "stocks",
    "earnings",
    "filings",
    "macro",
    "central_banks",
    "rates",
    "inflation",
    "jobs",
    "energy",
    "geopolitics",
    "trade_policy",
    "sanctions",
    "public_health",
    "pandemic",
    "supply_chain",
    "semiconductors",
    "space",
    "quantum",
)

AMBIGUOUS_TICKERS: Final[set[str]] = {"AI", "ON", "U", "CAT", "ARE", "NOW", "IT"}

TRUST_WEIGHTS: Final[dict[str, int]] = {
    "T0_OFFICIAL": 100,
    "T1_REGULATED_FILING": 95,
    "T2_REPUTABLE_MEDIA": 78,
    "T3_REVIEWED_PUBLIC_SOURCE": 62,
    "T4_WEAK_SIGNAL": 35,
    "T5_UNREVIEWED": 0,
    "T6_BLOCKED": 0,
}


def can_publish_trust_tiers(trust_tiers: list[str], *, confidence: float) -> tuple[bool, str]:
    if not trust_tiers:
        return False, "no_source_trust_tier"
    if any(tier == "T6_BLOCKED" for tier in trust_tiers):
        return False, "blocked_source"
    if any(tier == "T5_UNREVIEWED" for tier in trust_tiers):
        return False, "unreviewed_source"
    if set(trust_tiers) <= {"T4_WEAK_SIGNAL"} and confidence > 0.55:
        return False, "weak_signal_cannot_support_high_confidence_claim"
    return True, "publishable"
