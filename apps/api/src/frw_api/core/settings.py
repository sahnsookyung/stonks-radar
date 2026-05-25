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
    hf_token: str | None = None
    local_llm_base_url: str | None = "http://host.docker.internal:11434"

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
    short_research_sources: str = "hindenburg,muddy_waters,viceroy,spruce_point,kerrisdale,culper,blue_orca,grizzly"
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
    alternative_signal_refresh_seconds: int = Field(default=900, ge=60)

    public_api_rate_limit_per_minute: int = 60
    admin_api_rate_limit_per_minute: int = 120
    source_fetch_max_bytes: int = Field(default=5_000_000, ge=1000)
    source_fetch_timeout_seconds: int = Field(default=20, ge=1)
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
