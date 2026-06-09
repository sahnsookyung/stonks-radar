from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EventGateInput:
    severity: str
    source_strength: str
    review_status: str
    has_en_summary: bool
    has_ko_summary: bool
    source_keys: list[str]
    emergency_override: bool = False


def can_publish_event(event: EventGateInput) -> tuple[bool, str]:
    if "gdelt" in {key.lower() for key in event.source_keys} and event.source_strength in {
        "single_discovery",
        "weak",
    }:
        return False, "GDELT-style discovery cannot publish high-confidence events alone"
    if (
        event.severity in ("medium", "high", "critical")
        and not (event.has_en_summary and event.has_ko_summary)
        and not event.emergency_override
    ):
        return False, "Medium/high/critical events require EN/KO summaries"
    if event.severity == "low":
        return event.review_status in ("approved", "auto_official"), "Low event gate"
    if event.severity == "medium":
        return event.review_status == "approved", "Medium event gate"
    if event.severity == "high":
        return (
            event.review_status == "editor_approved" and event.source_strength in ("strong", "multi_source")
        ), "High event gate"
    if event.severity == "critical":
        return (
            event.review_status == "owner_approved" and event.source_strength in ("strong", "multi_source")
        ), "Critical event gate"
    return False, "Unknown severity"
