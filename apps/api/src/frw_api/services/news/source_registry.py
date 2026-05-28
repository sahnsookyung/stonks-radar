from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from frw_api.core.settings import Settings, get_settings
from frw_api.services.news.watchlist import watchlist_source_dicts


@dataclass(frozen=True)
class SourceProfile:
    source_key: str
    source_name: str
    source_type: str
    base_url: str
    trust_tier: str
    region_coverage: tuple[str, ...]
    topic_coverage: tuple[str, ...]
    rate_limit_provider_key: str
    rate_limit_endpoint_key: str
    copyright_mode: str
    enabled: bool = True
    scheduled_fetch: bool = False
    feed_url: str | None = None
    default_query: str | None = None
    fetch_kind: str = "feed"
    symbols: tuple[str, ...] = ()
    entity_type: str = "source"
    official_domains: tuple[str, ...] = ()
    fallback_source_keys: tuple[str, ...] = ()
    fetch_profile: str = "default"
    poll_seconds: int | None = None
    discovery_only: bool = False
    retention_class: str = "metadata_only"


def _watchlist_source_profiles() -> tuple[SourceProfile, ...]:
    return tuple(
        SourceProfile(
            source_key=_source_string(source, "source_key"),
            source_name=_source_string(source, "source_name"),
            source_type=_source_string(source, "source_type"),
            base_url=_source_string(source, "base_url"),
            trust_tier=_source_string(source, "trust_tier"),
            region_coverage=tuple(source.get("region_coverage") or ()),
            topic_coverage=tuple(source.get("topic_coverage") or ()),
            rate_limit_provider_key=_source_string(source, "rate_limit_provider_key"),
            rate_limit_endpoint_key=_source_string(source, "rate_limit_endpoint_key"),
            copyright_mode=_source_string(source, "copyright_mode"),
            enabled=bool(source.get("enabled", True)),
            scheduled_fetch=bool(source.get("scheduled_fetch", False)),
            feed_url=_optional_source_string(source.get("feed_url")),
            default_query=_optional_source_string(source.get("default_query")),
            fetch_kind=str(source.get("fetch_kind") or "feed"),
            symbols=tuple(source.get("symbols") or ()),
            entity_type=str(source.get("entity_type") or "source"),
            official_domains=tuple(source.get("official_domains") or ()),
            fallback_source_keys=tuple(source.get("fallback_source_keys") or ()),
            fetch_profile=str(source.get("fetch_profile") or "default"),
            poll_seconds=_optional_source_int(source.get("poll_seconds")),
            discovery_only=bool(source.get("discovery_only", False)),
            retention_class=str(source.get("retention_class") or "metadata_only"),
        )
        for source in watchlist_source_dicts()
    )


def _source_string(source: dict[str, Any], key: str) -> str:
    value = str(source.get(key) or "").strip()
    if not value:
        raise ValueError(f"ticker watchlist source missing required field: {key}")
    return value


def _optional_source_string(value: Any) -> str | None:
    clean = str(value or "").strip()
    return clean or None


def _optional_source_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


DEFAULT_NEWS_SOURCES: tuple[SourceProfile, ...] = (
    SourceProfile(
        source_key="sec_edgar",
        source_name="SEC EDGAR",
        source_type="regulated_filing",
        base_url="https://data.sec.gov",
        trust_tier="T1_REGULATED_FILING",
        region_coverage=("USA",),
        topic_coverage=("filings", "stocks"),
        rate_limit_provider_key="sec_edgar",
        rate_limit_endpoint_key="submissions",
        copyright_mode="public_filing_metadata",
        scheduled_fetch=False,
        fetch_kind="sec_atom",
        official_domains=("sec.gov",),
    ),
    SourceProfile(
        source_key="federal_reserve",
        source_name="Federal Reserve",
        source_type="official",
        base_url="https://www.federalreserve.gov",
        trust_tier="T0_OFFICIAL",
        region_coverage=("USA",),
        topic_coverage=("central_banks", "rates", "macro"),
        rate_limit_provider_key="federal_reserve",
        rate_limit_endpoint_key="public_pages",
        copyright_mode="official_public_metadata",
        scheduled_fetch=True,
        feed_url="https://www.federalreserve.gov/feeds/press_monetary.xml",
        official_domains=("federalreserve.gov",),
    ),
    SourceProfile(
        source_key="who",
        source_name="World Health Organization",
        source_type="official",
        base_url="https://www.who.int",
        trust_tier="T0_OFFICIAL",
        region_coverage=("GLOBAL",),
        topic_coverage=("public_health", "pandemic"),
        rate_limit_provider_key="who",
        rate_limit_endpoint_key="rss",
        copyright_mode="official_public_metadata",
        scheduled_fetch=True,
        feed_url="https://www.who.int/rss-feeds/news-english.xml",
        official_domains=("who.int",),
    ),
    SourceProfile(
        source_key="gdelt",
        source_name="GDELT Doc API",
        source_type="aggregator",
        base_url="https://api.gdeltproject.org/api/v2/doc/doc",
        trust_tier="T4_WEAK_SIGNAL",
        region_coverage=("GLOBAL",),
        topic_coverage=("stocks", "geopolitics", "energy", "public_health", "supply_chain"),
        rate_limit_provider_key="gdelt",
        rate_limit_endpoint_key="doc",
        copyright_mode="metadata_only",
        enabled=True,
        scheduled_fetch=True,
        default_query="(semiconductor OR central bank OR rates OR sanctions OR outbreak OR energy)",
        discovery_only=True,
    ),
    SourceProfile(
        source_key="google_news_rss",
        source_name="Google News RSS",
        source_type="rss_discovery",
        base_url="https://news.google.com/rss",
        trust_tier="T4_WEAK_SIGNAL",
        region_coverage=("GLOBAL",),
        topic_coverage=("stocks", "geopolitics", "energy", "public_health"),
        rate_limit_provider_key="google_news_rss",
        rate_limit_endpoint_key="search",
        copyright_mode="metadata_only",
        scheduled_fetch=True,
        default_query="(semiconductor OR central bank OR sanctions OR outbreak OR oil supply)",
        discovery_only=True,
    ),
    SourceProfile(
        source_key="company_email_alert",
        source_name="Company Email Alerts",
        source_type="company_email",
        base_url="mailto:news-alerts",
        trust_tier="T0_OFFICIAL",
        region_coverage=("GLOBAL",),
        topic_coverage=("stocks", "filings", "earnings", "space", "quantum"),
        rate_limit_provider_key="company_email",
        rate_limit_endpoint_key="webhook",
        copyright_mode="source_linked_metadata",
        scheduled_fetch=False,
        fetch_kind="email_webhook",
        retention_class="raw_email_30d",
    ),
    *_watchlist_source_profiles(),
)


def _all_news_sources() -> tuple[SourceProfile, ...]:
    return DEFAULT_NEWS_SOURCES


def source_registry() -> dict[str, SourceProfile]:
    return {source.source_key: source for source in _all_news_sources()}


def enabled_news_sources(*, settings: Settings | None = None) -> tuple[SourceProfile, ...]:
    settings = settings or get_settings()
    return tuple(
        source
        for source in _all_news_sources()
        if source.scheduled_fetch and _source_enabled(source, settings)
    )


def source_enabled(source: SourceProfile, settings: Settings | None = None) -> bool:
    return _source_enabled(source, settings or get_settings())


def source_profile_public_dict(source: SourceProfile) -> dict[str, Any]:
    return {
        "source_key": source.source_key,
        "source_name": source.source_name,
        "source_type": source.source_type,
        "trust_tier": source.trust_tier,
        "region_coverage": list(source.region_coverage),
        "topic_coverage": list(source.topic_coverage),
        "rate_limit_provider_key": source.rate_limit_provider_key,
        "rate_limit_endpoint_key": source.rate_limit_endpoint_key,
        "copyright_mode": source.copyright_mode,
        "enabled": source.enabled,
        "scheduled_fetch": source.scheduled_fetch,
        "fetch_kind": source.fetch_kind,
        "symbols": list(source.symbols),
        "entity_type": source.entity_type,
        "discovery_only": source.discovery_only,
        "retention_class": source.retention_class,
    }


def _source_enabled(source: SourceProfile, settings: Settings) -> bool:
    if not source.enabled:
        return False
    if source.source_key == "gdelt" and not settings.news_gdelt_enabled:
        return False
    if source.rate_limit_provider_key in {"google_news_rss", "yahoo_finance_rss"} and not settings.news_rss_enabled:
        return False
    if source.source_key == "who" and not settings.news_public_health_enabled:
        return False
    return True
