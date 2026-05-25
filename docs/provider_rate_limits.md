# Provider Rate Limits And Refresh Schedule

This project must run with `PAID_USAGE_ALLOWED=false`. Paid-only endpoints,
premium market feeds, and pay-as-you-go LLM calls stay disabled unless that
policy changes explicitly.

## Financial Data

| Provider | Env vars | Free / public limit | Stonks Radar schedule |
| --- | --- | --- | --- |
| FRED | `FRED_API_KEY` | 2 requests/second; excess returns 429 | Public macro tiles every 4 hours on weekdays, daily on weekends; monthly/quarterly series daily. |
| BLS | `BLS_API_KEY` | 500 queries/day for registered API users; up to 50 series and 20 years/query | Release-day checks hourly around CPI/jobs/PPI windows; otherwise daily. |
| EIA | `EIA_API_KEY` | 5,000 JSON rows/request; no stable public request-per-second number published | Oil/energy reference refresh every 6 hours; weekly inventory releases hourly around scheduled publication. |
| SEC EDGAR | `SEC_USER_AGENT` | 10 requests/second maximum | Trump disclosure CIK checks default to every 30 minutes (`TRUMP_DISCLOSURE_SEC_POLL_SECONDS=1800`); broader scans daily. |
| OGE public disclosures | `SEC_USER_AGENT` for contact string | Undocumented public endpoint; treat as unstable and throttle to 1 request every 2 seconds | Donald Trump OGE index/PDF checks default to daily (`TRUMP_DISCLOSURE_OGE_POLL_SECONDS=86400`). No minute-level polling because Form 278-T can be delayed up to 45 days. |
| FINRA Query API | `FINRA_API_CLIENT_ID`, `FINRA_API_CLIENT_SECRET`, optional `FINRA_API_TOKEN` | OAuth client credentials; synchronous: 1,200 requests/minute/IP, 5,000 records/request, 3 MB sync response; async: 20 requests/minute/dataset/API account; credential data limit is 10 GB/month | Reg SHO once after 6:00 p.m. ET and once next morning; short interest twice monthly plus one daily retry window after release dates. |
| Twelve Data | `TWELVE_DATA_API_KEY` | Basic plan: 8 API credits/minute and 800/day | User-triggered portfolio history with 15-minute cache; daily public refresh budget under 100 credits. |
| Alpha Vantage | `ALPHA_VANTAGE_API_KEY` | 25 requests/day | Fallback only; cap at 20/day and never poll intraday. |
| FMP | `FMP_API_KEY` | Free plan: 250 calls/day, reset at 3 p.m. ET | Disabled until key is present; if enabled, fundamentals/EOD once daily. |
| Finnhub | `FINNHUB_API_KEY` | Free plan: 60 API calls/minute | Future fallback only; user-triggered cache plus daily calendar/news reference. |
| Nasdaq Data Link | `NASDAQ_DATA_LINK_API_KEY` | Authenticated REST: 300 calls/10s, 2,000/10min, 50,000/day; concurrency 1 | Free/open datasets only, daily or lower frequency. |
| World Bank | none | No fixed public limit published | Annual/monthly macro data weekly; never high-frequency. |
| ECB Data Portal | none | No fixed public limit published | Daily FX/rates after ECB update windows; otherwise weekly metadata checks. |
| GDELT / public web | none | Rate limited, no stable public numeric quota for legacy APIs | Weak-signal discovery only; 15-minute minimum with backoff, no market claims without corroboration. |

## LLM Providers

| Provider | Env vars | Free / public limit | Stonks Radar schedule |
| --- | --- | --- | --- |
| Local LLM | `LOCAL_LLM_BASE_URL` | Local capacity only | Preferred for private research and drafts. |
| Gemini | `GEMINI_API_KEY` | Free tier is model-specific; active limits are project/model based in AI Studio. Use Flash-Lite budget as the default ceiling: 15 RPM, 250k TPM, 1,000 RPD. | Public-fact summarization only; cap at 100 requests/day and prefer batch/offline runs. |
| Groq | `GROQ_API_KEY` | Free limits vary by model; examples include 30 RPM/250 RPD for `groq/compound`, 30 RPM/1k RPD for several large text models | Low-volume fallback summaries; cap at 200 requests/day and model-specific RPM. |
| Cerebras | `CEREBRAS_API_KEY` | Free tier is model-specific; current published examples include 10-30 RPM, 100-14,400 RPD, and 60k-64k TPM depending on model | Disabled until key is present; use only manual/offline public-fact tasks. |
| Mistral | `MISTRAL_API_KEY` | Free API tier exists; limits vary by subscription tier and model, exposed via response headers | Disabled until key is present; use only manual/offline public-fact tasks. |
| OpenRouter | `OPENROUTER_API_KEY` | Free models: 20 RPM and 50 requests/day before $10 credits; 1,000/day after $10 credits | Disabled while `PAID_USAGE_ALLOWED=false` unless using zero-credit free models under 25/day. |
| Hugging Face Hub | `HF_TOKEN` | Hub free-user bucket: 1,000 API calls/5 minutes; resolver bucket is separate and higher | Hub metadata/download only; prefer resolver URLs and cache aggressively. |
| Hugging Face Inference Providers | `HF_TOKEN` | Free routed inference credits are $0.10/month for free users; no pay-as-you-go after credits unless account is paid | Disabled until token is present; embeddings/classification only, no paid overflow. |

## Runtime Behavior

The executable source of truth is `frw_api.services.provider_limits`.
Runtime provider calls must go through `provider_request`, which reserves quota
before the network call, classifies upstream failures, and records usage/audit
state when a database session is available. Production uses Valkey/Redis quota
counters and fails closed if that store is unavailable. Development and tests
use in-process counters.

Failure classes are explicit: `rate_limited`, `quota_exhausted`,
`auth_invalid`, `forbidden_scope`, `paid_not_allowed`, `upstream_5xx`,
`timeout`, `schema_changed`, `no_data`, and `unsupported`. Worker jobs that hit
`rate_limited` or `quota_exhausted` move to `quota_wait` with the provider's
retry-after/reset time when available.
