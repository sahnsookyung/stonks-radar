from __future__ import annotations

from frw_api.services.news.taxonomy import TRUST_WEIGHTS


def clamp_score(value: float) -> int:
    return int(max(0, min(100, round(value))))


def trust_score(trust_tiers: list[str]) -> int:
    if not trust_tiers:
        return 0
    return clamp_score(max(TRUST_WEIGHTS.get(tier, 0) for tier in trust_tiers))


def breaking_score(
    *,
    recency_score: float,
    source_trust_score: float,
    source_velocity_score: float,
    novelty_score: float,
    affected_entity_importance_score: float,
    topic_severity_score: float,
    cross_region_impact_score: float,
) -> int:
    return clamp_score(
        recency_score * 0.22
        + source_trust_score * 0.18
        + source_velocity_score * 0.14
        + novelty_score * 0.12
        + affected_entity_importance_score * 0.14
        + topic_severity_score * 0.12
        + cross_region_impact_score * 0.08
    )


def classify_provider_error(status_code: int | None, message: str = "") -> str:
    text = message.lower()
    if status_code == 429 or "rate limit" in text:
        return "quota_or_rate_limit"
    if status_code in {401, 403}:
        if "quota" in text or "limit" in text:
            return "quota_or_entitlement"
        return "auth_or_entitlement"
    if status_code and status_code >= 500:
        return "provider_transient"
    if status_code and status_code >= 400:
        return "provider_rejected_request"
    return "unknown"
