from __future__ import annotations

import os
import json
from typing import Any

from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://frw:frw@localhost:5432/frw")

DATA_SOURCES = [
    ("bls", "U.S. Bureau of Labor Statistics", "official_api", "https://api.bls.gov/publicAPI/v2", "structured_fact_only", "low"),
    ("fred", "FRED/ALFRED", "official_api", "https://api.stlouisfed.org/fred", "structured_fact_only", "low"),
    ("federal_reserve", "Federal Reserve", "official_page", "https://www.federalreserve.gov", "full_text_open", "low"),
    ("sec_edgar", "SEC EDGAR", "filing", "https://data.sec.gov", "full_text_open", "low"),
    ("trump_filings", "Trump-related public filings", "filing", "https://data.sec.gov", "structured_fact_only", "medium"),
    ("oge_disclosures", "U.S. Office of Government Ethics public disclosures", "filing", "https://www.oge.gov", "structured_fact_only", "medium"),
    ("eia", "U.S. Energy Information Administration", "official_api", "https://api.eia.gov", "structured_fact_only", "low"),
    ("ecb", "ECB Data Portal", "official_api", "https://data-api.ecb.europa.eu", "structured_fact_only", "low"),
    ("world_bank", "World Bank", "official_api", "https://api.worldbank.org/v2", "structured_fact_only", "low"),
    ("gdelt", "GDELT", "aggregator", "https://api.gdeltproject.org", "metadata_only", "medium"),
    ("google_news_rss", "Google News RSS", "news_metadata", "https://news.google.com/rss", "metadata_only", "medium"),
    ("yahoo_finance_rss", "Yahoo Finance RSS", "news_metadata", "https://feeds.finance.yahoo.com/rss/2.0/headline", "metadata_only", "medium"),
    ("who", "World Health Organization", "official_page", "https://www.who.int", "structured_fact_only", "low"),
    ("natural_earth", "Natural Earth", "public_web", "https://www.naturalearthdata.com", "full_text_open", "low"),
    ("finra_short_interest", "FINRA Short Interest", "official_api", "https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest", "structured_fact_only", "low"),
    ("finra_reg_sho_short_volume", "FINRA Reg SHO Daily Short Sale Volume", "official_api", "https://api.finra.org", "structured_fact_only", "low"),
    ("twelve_data", "Twelve Data", "market_data", "https://api.twelvedata.com", "structured_fact_only", "medium"),
    ("alpha_vantage", "Alpha Vantage", "market_data", "https://www.alphavantage.co", "structured_fact_only", "medium"),
    ("fmp", "Financial Modeling Prep", "market_data", "https://financialmodelingprep.com", "structured_fact_only", "medium"),
    ("public_short_research", "Public short-research publishers", "public_web", "https://muddywatersresearch.com/research/", "metadata_only", "medium"),
    ("pentagon_pizza", "Pentagon.Pizza", "public_web", "https://pentagon.pizza", "metadata_only", "high"),
    ("defense_contracts", "U.S. Defense contract announcements", "official_page", "https://www.defense.gov/News/Contracts/", "structured_fact_only", "low"),
    ("nasa_firms", "NASA FIRMS", "official_api", "https://firms.modaps.eosdis.nasa.gov", "structured_fact_only", "low"),
]

PROVIDERS = [
    ("local", "llm_provider", "always_free", "LOCAL_ONLY", False),
    ("gemini", "llm_provider", "free_quota", "FREE_ONLY", False),
    ("groq", "llm_provider", "free_quota", "FREE_ONLY", False),
    ("cerebras", "llm_provider", "free_quota", "FREE_ONLY", False),
    ("mistral", "llm_provider", "free_quota", "FREE_ONLY", False),
    ("openrouter", "llm_provider", "free_quota", "FREE_ONLY", False),
    ("huggingface_hub", "llm_provider", "free_quota", "FREE_ONLY", False),
    ("huggingface_inference", "llm_provider", "free_quota", "FREE_ONLY", False),
    ("fred", "official_api", "free_quota", "FREE_ONLY", False),
    ("bls", "official_api", "free_quota", "FREE_ONLY", False),
    ("eia", "official_api", "free_quota", "FREE_ONLY", False),
    ("ecb", "official_api", "always_free", "FREE_ONLY", False),
    ("world_bank", "official_api", "always_free", "FREE_ONLY", False),
    ("gdelt", "aggregator", "always_free", "FREE_ONLY", False),
    ("google_news_rss", "rss_metadata", "always_free", "FREE_ONLY", False),
    ("yahoo_finance_rss", "rss_metadata", "always_free", "FREE_ONLY", False),
    ("who", "official_page", "always_free", "FREE_ONLY", False),
    ("federal_reserve", "official_page", "always_free", "FREE_ONLY", False),
    ("sec_edgar", "filing", "always_free", "FREE_ONLY", False),
    ("twelve_data", "market_data", "free_quota", "FREE_ONLY", False),
    ("alpha_vantage", "market_data", "free_quota", "FREE_ONLY", False),
    ("fmp", "market_data", "free_quota", "FREE_ONLY", False),
    ("finnhub", "market_data", "free_quota", "FREE_ONLY", False),
    ("nasdaq_data_link", "market_data", "free_quota", "FREE_ONLY", False),
    ("finra", "official_api", "always_free", "FREE_ONLY", False),
]

FACT_TYPES: list[tuple[str, str, str, dict[str, Any], list[str], bool]] = [
    (
        "central_bank_decision",
        "Central bank decision",
        "중앙은행 결정",
        {
            "type": "object",
            "required": ["country_region", "bank", "decision_date", "source"],
            "properties": {
                "country_region": {"type": "string"},
                "bank": {"type": "string"},
                "decision_date": {"type": "string"},
                "rate_before": {"type": ["number", "null"]},
                "rate_after": {"type": ["number", "null"]},
                "unit": {"type": ["string", "null"]},
                "source": {"type": "string"},
            },
            "additionalProperties": False,
        },
        ["decided", "scheduled"],
        True,
    ),
    (
        "macro_release_actual",
        "Macro release actual",
        "거시지표 실제치",
        {
            "type": "object",
            "required": ["release", "period", "actual", "unit", "source", "release_time"],
            "properties": {
                "release": {"type": "string"},
                "period": {"type": "string"},
                "actual": {"type": ["number", "string"]},
                "unit": {"type": "string"},
                "source": {"type": "string"},
                "release_time": {"type": "string"},
            },
            "additionalProperties": False,
        },
        ["released"],
        True,
    ),
    (
        "company_earnings_event",
        "Company earnings event",
        "기업 실적 이벤트",
        {"type": "object", "required": ["company", "period", "source"], "properties": {"company": {"type": "string"}, "period": {"type": "string"}, "source": {"type": "string"}}, "additionalProperties": True},
        ["reported", "guided"],
        False,
    ),
    (
        "government_contract_award",
        "Government contract award",
        "정부 계약 수주",
        {"type": "object", "required": ["issuer", "recipient", "date", "source"], "properties": {"issuer": {"type": "string"}, "recipient": {"type": "string"}, "amount": {"type": ["number", "null"]}, "currency": {"type": ["string", "null"]}, "date": {"type": "string"}, "source": {"type": "string"}}, "additionalProperties": False},
        ["awarded"],
        False,
    ),
    (
        "geopolitical_event",
        "Geopolitical event",
        "지정학 이벤트",
        {"type": "object", "required": ["region", "event_subtype", "occurred_at", "severity_basis", "sources"], "properties": {"region": {"type": "string"}, "event_subtype": {"type": "string"}, "occurred_at": {"type": "string"}, "severity_basis": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}}, "additionalProperties": False},
        ["occurred", "escalated", "deescalated"],
        False,
    ),
    (
        "news_document_metadata",
        "News document metadata",
        "뉴스 문서 메타데이터",
        {
            "type": "object",
            "required": ["title", "source_url", "source_key", "trust_tier"],
            "properties": {
                "title": {"type": "string"},
                "snippet": {"type": ["string", "null"]},
                "published_at": {"type": ["string", "null"]},
                "source_url": {"type": "string"},
                "source_key": {"type": "string"},
                "trust_tier": {"type": "string"},
            },
            "additionalProperties": False,
        },
        ["states"],
        False,
    ),
    (
        "news_event_link",
        "News event link",
        "뉴스 이벤트 연결",
        {
            "type": "object",
            "required": ["event_id", "document_id", "relationship"],
            "properties": {
                "event_id": {"type": "string"},
                "document_id": {"type": "string"},
                "relationship": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "additionalProperties": False,
        },
        ["supports"],
        False,
    ),
    (
        "news_entity_mention",
        "News entity mention",
        "뉴스 엔티티 언급",
        {
            "type": "object",
            "required": ["entity_key", "entity_type", "relationship"],
            "properties": {
                "entity_key": {"type": "string"},
                "entity_type": {"type": "string"},
                "relationship": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "additionalProperties": False,
        },
        ["mentions"],
        False,
    ),
    (
        "news_market_relevance",
        "News market relevance",
        "뉴스 시장 관련성",
        {
            "type": "object",
            "required": ["direction", "confidence", "reasoning"],
            "properties": {
                "direction": {"type": "string"},
                "confidence": {"type": "string"},
                "reasoning": {"type": "string"},
            },
            "additionalProperties": False,
        },
        ["suggests"],
        False,
    ),
]


def main() -> None:
    engine = create_engine(DATABASE_URL, future=True)
    with engine.begin() as conn:
        for source in DATA_SOURCES:
            llm_classes = (
                ["PUBLIC_FACTS_ONLY"]
                if source[2] in {"rss", "news_metadata", "aggregator"} or source[4] == "metadata_only"
                else ["PUBLIC_FACTS_ONLY", "PUBLIC_SOURCE_TEXT"]
            )
            source_id = conn.execute(
                text(
                    """
                    insert into data_source(source_key, display_name, source_type, base_url, raw_retention_policy, redistribution_risk)
                    values (:key, :name, :type, :base_url, :retention, :risk)
                    on conflict (source_key) do update
                    set display_name = excluded.display_name,
                        source_type = excluded.source_type,
                        base_url = excluded.base_url,
                        raw_retention_policy = excluded.raw_retention_policy,
                        redistribution_risk = excluded.redistribution_risk
                    returning id
                    """
                ),
                {
                    "key": source[0],
                    "name": source[1],
                    "type": source[2],
                    "base_url": source[3],
                    "retention": source[4],
                    "risk": source[5],
                },
            ).scalar_one()
            conn.execute(
                text(
                    """
                    insert into source_policy_decision(
                      source_id, policy_version, allowed_acquisition_modes,
                      allowed_retention_classes, public_display_policy, llm_allowed_classes,
                      redistribution_notes, active
                    )
                    values (
                      :source_id, 1, :modes, :retention_classes, 'facts_with_attribution',
                      :llm_classes, 'Seeded v8 public-source policy', true
                    )
                    on conflict (source_id, policy_version) do update set active = true
                    """
                ),
                {
                    "source_id": source_id,
                    "modes": ["official_api", "official_page", "filing", "rss_metadata", "public_web_fetch"],
                    "retention_classes": ["metadata_only", "structured_fact_only", source[4]],
                    "llm_classes": llm_classes,
                },
            )
        for key, typ, billing, mode, paid in PROVIDERS:
            conn.execute(
                text(
                    """
                    insert into provider_budget(provider_key, provider_type, billing_mode, routing_mode, paid_allowed)
                    values (:key, :type, :billing, :mode, :paid)
                    on conflict (provider_key) do update set routing_mode = excluded.routing_mode
                    """
                ),
                {"key": key, "type": typ, "billing": billing, "mode": mode, "paid": paid},
            )
            if typ == "llm_provider":
                conn.execute(
                    text(
                        """
                        insert into llm_model_profile(
                          provider_key, model_key, structured_output_support,
                          privacy_class, data_use_policy, billing_mode, enabled
                        )
                        values (:provider_key, :model_key, true, :privacy_class, 'free_or_local_review_required', :billing_mode, :enabled)
                        on conflict (provider_key, model_key) do update
                        set privacy_class = excluded.privacy_class,
                            billing_mode = excluded.billing_mode,
                            enabled = excluded.enabled
                        """
                    ),
                    {
                        "provider_key": key,
                        "model_key": {
                            "local": "llama3.1-json",
                            "gemini": "gemini-1.5-flash",
                            "groq": "llama-3.1-8b-instant",
                            "cerebras": "llama3.1-8b",
                            "mistral": "mistral-small-latest",
                            "openrouter": "openrouter/free",
                        }.get(key, key),
                        "privacy_class": "LOCAL_ONLY" if key == "local" else "PUBLIC_FACTS_ONLY",
                        "billing_mode": billing,
                        "enabled": key == "local",
                    },
                )
        for fact_type, en, ko, schema, predicates, public_default in FACT_TYPES:
            conn.execute(
                text(
                    """
                    insert into fact_type_registry(fact_type, display_name_en, display_name_ko, json_schema, allowed_predicates, public_allowed_default)
                    values (:fact_type, :en, :ko, cast(:schema as jsonb), :predicates, :public_default)
                    on conflict (fact_type) do update set json_schema = excluded.json_schema
                    """
                ),
                {"fact_type": fact_type, "en": en, "ko": ko, "schema": json.dumps(schema), "predicates": predicates, "public_default": public_default},
            )
        for key, value, severity in [
            ("disk_watermark", "unknown_until_monitor_runs", "warning"),
            ("snapshot_storage", "local_oci", "info"),
            ("backup", "local_encrypted_backups_not_configured", "warning"),
        ]:
            conn.execute(
                text(
                    """
                    insert into operation_status(status_key, status_value, severity)
                    values (:key, :value, :severity)
                    on conflict (status_key) do nothing
                    """
                ),
                {"key": key, "value": value, "severity": severity},
            )
        for scope_type, scope_key, max_running in [
            ("job_type", "public_js_render", 1),
            ("job_type", "snapshot_refresh", 1),
            ("job_type", "snapshot_publish", 1),
            ("job_type", "backup", 1),
            ("provider", "local", 1),
            ("provider", "google_news_rss", 1),
            ("provider", "yahoo_finance_rss", 1),
            ("provider", "company_ir", 1),
            ("provider", "sec_edgar", 2),
            ("job_group", "news", 2),
            ("global", "global", 8),
        ]:
            conn.execute(
                text(
                    """
                    insert into job_concurrency_limit(scope_type, scope_key, max_running)
                    values (:scope_type, :scope_key, :max_running)
                    on conflict (scope_type, scope_key) do update set max_running = excluded.max_running
                    """
                ),
                {"scope_type": scope_type, "scope_key": scope_key, "max_running": max_running},
            )
    print("Seeded database reference data")


if __name__ == "__main__":
    main()
