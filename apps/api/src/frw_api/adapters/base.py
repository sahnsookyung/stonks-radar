from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AdapterResult:
    source_key: str
    object_key: str
    observations: list[dict[str, Any]]
    releases: list[dict[str, Any]]
    documents: list[dict[str, Any]]
    unsupported: list[str]


class SourceAdapter(Protocol):
    source_key: str

    async def fetch(self, **kwargs: Any) -> AdapterResult:
        ...


def empty_result(source_key: str, object_key: str, unsupported: list[str] | None = None) -> AdapterResult:
    return AdapterResult(
        source_key=source_key,
        object_key=object_key,
        observations=[],
        releases=[],
        documents=[],
        unsupported=unsupported or [],
    )
