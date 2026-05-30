from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_base_url: str = "http://localhost:8000"
    public_base_url: str = "http://localhost:5173"
    dev_cors_origins: str = "http://localhost:5173"
    default_locale: Literal["en", "ko"] = "en"
    supported_locales: str = "en,ko"

    database_url: str = "postgresql+psycopg://frw:frw@localhost:5432/frw"
    redis_url: str = "redis://localhost:6379/0"

    session_secret: str = "dev-session-secret-change-me"
    password_pepper: str = "dev-password-pepper-change-me"
    totp_issuer: str = "StonksRadar"
    admin_email: str = "owner@example.com"
    admin_bootstrap_password: str | None = None
    admin_totp_secret: str | None = None

    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    cerebras_api_key: str | None = None
    mistral_api_key: str | None = None
    openrouter_api_key: str | None = None
    nvidia_api_key: str | None = None
    nvidia_nim_api_key: str | None = None
    nvidia_nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_nim_model_key: str = "minimaxai/minimax-m2.7"
    nvidia_nim_rate_limit_per_minute: int = Field(default=40, ge=1, le=120)
    hf_token: str | None = None

    fred_api_key: str | None = None
    bls_api_key: str | None = None
    sec_user_agent: str = "StonksRadar contact@example.com"
    eia_api_key: str | None = None
    worldbank_base_url: str = "https://api.worldbank.org/v2"
    imf_base_url: str | None = None
    oecd_base_url: str | None = None
    ecb_base_url: str = "https://data-api.ecb.europa.eu/service/data"
    boj_base_url: str | None = None
    bok_base_url: str | None = None
    bcb_base_url: str | None = None
    market_data_api_key: str | None = None
    market_data_provider: str | None = None
    market_data_base_url: str | None = None
    market_data_provider_order: str = "twelve_data,alpha_vantage,fmp"
    market_data_display_mode: Literal["auto", "public", "private"] = "auto"
    market_data_public_display_allowlist: str = ""
    market_data_cache_ttl_seconds: int = Field(default=900, ge=60)
    market_data_cache_max_entries: int = Field(default=512, ge=1, le=10000)
    market_data_timeout_seconds: int = Field(default=12, ge=1)
    market_data_max_symbols: int = Field(default=8, ge=1, le=30)
    market_data_max_history_days: int = Field(default=756, ge=30, le=3650)
    twelve_data_api_key: str | None = None
    alpha_vantage_api_key: str | None = None
    fmp_api_key: str | None = None
    finnhub_api_key: str | None = None
    nasdaq_data_link_api_key: str | None = None
    finra_api_base_url: str = "https://api.finra.org"
    finra_oauth_token_url: str = "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token?grant_type=client_credentials"
    finra_api_client_id: str | None = None
    finra_api_client_secret: str | None = None
    finra_api_token: str | None = None
    short_volume_monitored_tickers: str = "DJT,TSLA,NVDA"
    short_research_sources: str = "muddy_waters,viceroy,spruce_point,kerrisdale,culper,blue_orca,grizzly"
    pentagon_pizza_base_url: str | None = "https://pentagon.pizza"
    pentagon_pizza_function_url: str | None = None
    pentagon_pizza_supabase_anon_key: str | None = None
    trump_filing_monitored_entities: str = "DJT,Donald J. Trump Revocable Trust"
    oge_disclosure_api_base_url: str = "https://extapps2.oge.gov/201/Presiden.nsf/API.xsp/v2/rest"
    oge_disclosure_search_url: str = "https://www.oge.gov/web/oge.nsf/Officials%20Individual%20Disclosures%20Search%20Collection?OpenForm="
    oge_disclosure_page_size: int = Field(default=1000, ge=100, le=1000)
    oge_disclosure_max_index_records: int = Field(default=5000, ge=1000, le=20000)
    trump_disclosure_oge_pdf_limit: int = Field(default=12, ge=0, le=100)
    trump_disclosure_sec_filing_limit: int = Field(default=50, ge=1, le=250)
    trump_disclosure_sec_poll_seconds: int = Field(default=1800, ge=900)
    trump_disclosure_oge_poll_seconds: int = Field(default=86400, ge=21600)
    worker_scheduler_enabled: bool = True
    worker_scheduler_tick_seconds: int = Field(default=60, ge=10, le=3600)
    worker_job_lease_seconds: int = Field(default=900, ge=60, le=3600)
    snapshot_refresh_seconds: int = Field(default=900, ge=300)
    alternative_signal_refresh_seconds: int = Field(default=900, ge=60)
    news_rss_enabled: bool = True
    news_gdelt_enabled: bool = False
    news_public_health_enabled: bool = True
    news_source_refresh_seconds: int = Field(default=900, ge=300)
    news_publication_interval_seconds: int = Field(default=300, ge=60)
    news_max_documents_per_source_per_run: int = Field(default=100, ge=1, le=1000)
    news_processing_batch_limit: int = Field(default=500, ge=1, le=5000)
    news_page_read_batch_limit: int = Field(default=25, ge=1, le=250)
    news_event_cluster_min_confidence: float = Field(default=0.55, ge=0, le=1)
    news_ticker_watchlist: str = "DJT,TSLA,NVDA,RKLB,IONQ,RGTI,QBTS,QUANTINUUM,LUNR,ASTS,RDW,AMD,AAPL,MSFT,TLT,005930.KS"
    news_summary_input_max_chars: int = Field(default=120_000, ge=1_000, le=1_000_000)
    news_summary_llm_enabled: bool = False
    news_summary_max_events_per_run: int = Field(default=20, ge=0, le=200)
    admin_url_summary_daily_limit: int = Field(default=20, ge=0, le=200)
    news_email_webhook_secret: str | None = None
    news_email_allowed_recipients: str = ""
    news_email_raw_retention_days: int = Field(default=30, ge=1, le=365)
    news_email_dead_letter_retention_days: int = Field(default=14, ge=1, le=90)
    news_email_max_raw_bytes: int = Field(default=1_048_576, ge=1024, le=5_000_000)
    news_email_archive_dir: str = "/var/lib/stonks-radar/email-archive"
    news_email_signature_max_skew_seconds: int = Field(default=300, ge=30, le=3600)
    news_auto_review_trusted_events: bool = True

    public_api_rate_limit_per_minute: int = 60
    admin_api_rate_limit_per_minute: int = 120
    trusted_proxy_cidrs: str = "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    source_fetch_max_bytes: int = Field(default=5_000_000, ge=1000)
    source_fetch_timeout_seconds: int = Field(default=20, ge=1)
    source_fetch_allow_http: bool = False
    playwright_concurrency: int = 1
    llm_global_daily_soft_limit: int = 0
    llm_global_daily_hard_limit: int = 0
    paid_usage_allowed: bool = False

    @property
    def locale_list(self) -> list[str]:
        return [value.strip() for value in self.supported_locales.split(",") if value.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        origins = [self.public_base_url]
        if self.app_env != "production":
            origins.extend(value.strip() for value in self.dev_cors_origins.split(",") if value.strip())
        return list(dict.fromkeys(origins))

    @property
    def resolved_market_data_display_mode(self) -> Literal["public", "private"]:
        if self.market_data_display_mode != "auto":
            return self.market_data_display_mode
        return "public" if self.app_env.lower() in {"production", "prod"} else "private"

    @property
    def market_data_public_display_allowlist_values(self) -> set[str]:
        return {
            value.strip().lower()
            for value in self.market_data_public_display_allowlist.split(",")
            if value.strip()
        }

    @property
    def news_email_allowed_recipient_list(self) -> list[str]:
        return [value.strip().lower() for value in self.news_email_allowed_recipients.split(",") if value.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
