from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse

from frw_api.services.news.taxonomy import AMBIGUOUS_TICKERS


@dataclass(frozen=True)
class EntityProfile:
    symbol: str
    legal_name: str
    aliases: tuple[str, ...] = ()
    official_domains: tuple[str, ...] = ()
    sector_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class EntityMatch:
    symbol: str
    relationship: str
    confidence: float
    reason: str


def match_entities(document: Mapping[str, object], profiles: list[EntityProfile]) -> list[EntityMatch]:
    text = " ".join(str(document.get(key) or "") for key in ("title", "snippet", "summary", "body")).lower()
    raw_text = " ".join(str(document.get(key) or "") for key in ("title", "snippet", "summary", "body"))
    host = urlparse(str(document.get("url") or "")).netloc.lower()
    matches: list[EntityMatch] = []
    for profile in profiles:
        symbol = profile.symbol.upper()
        official = any(domain.lower() in host for domain in profile.official_domains)
        company_name = _contains_phrase(text, profile.legal_name) or any(_contains_phrase(text, alias) for alias in profile.aliases)
        ticker_with_dollar = re.search(rf"(?<![A-Z0-9])\${re.escape(symbol)}(?![A-Z0-9])", raw_text, flags=re.IGNORECASE)
        bare_ticker = re.search(rf"(?<![A-Z0-9]){re.escape(symbol)}(?![A-Z0-9])", raw_text)
        sector_context = any(_contains_phrase(text, term) for term in profile.sector_terms)

        if official:
            matches.append(EntityMatch(symbol=symbol, relationship="direct_subject", confidence=0.96, reason="official_source"))
            continue
        if company_name:
            matches.append(EntityMatch(symbol=symbol, relationship="direct_subject", confidence=0.9, reason="company_name_or_alias"))
            continue
        if symbol in AMBIGUOUS_TICKERS:
            if ticker_with_dollar and sector_context:
                matches.append(EntityMatch(symbol=symbol, relationship="direct_subject", confidence=0.72, reason="ambiguous_ticker_with_sector_context"))
            continue
        if ticker_with_dollar:
            matches.append(EntityMatch(symbol=symbol, relationship="direct_subject", confidence=0.78, reason="cashtag"))
        elif bare_ticker and sector_context:
            matches.append(EntityMatch(symbol=symbol, relationship="affected_company", confidence=0.68, reason="ticker_with_sector_context"))
    return matches


def _contains_phrase(text: str, phrase: str) -> bool:
    phrase = phrase.strip().lower()
    if not phrase:
        return False
    return phrase in text
