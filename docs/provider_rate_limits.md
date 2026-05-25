# Provider Rate Limits And Refresh Schedule

This project must run with `PAID_USAGE_ALLOWED=false`. Paid-only endpoints,
premium market feeds, and pay-as-you-go LLM calls stay disabled unless that
policy changes explicitly.

## Financial Data

| Provider | Env vars | Free / public limit | Stonks Radar schedule |
| --- | --- | --- | --- |
| FRED | `FRED_API_KEY` | 2 requests/second; excess returns 429 | Public macro tiles every 4 hours on weekdays, daily on weekends; monthly/quarterly series daily. |
| BLS | `BLS_API_KEY` | 500 queries/day for registered API users; up to 50 series and 20 years/query | Release-day checks hourly around CPI/jobs/PPI windows; otherwise daily. |
| EIA | `EIA_API_KEY` | EIA does not publish exact firewall rules; guidance says stay below ~9,000/hour sustained and 5/second burst | Oil/energy reference refresh every 6 hours; weekly inventory releases hourly around scheduled publication. |
| SEC EDGAR | `SEC_USER_AGENT` | 10 requests/second maximum | Watched CIK checks every 15 minutes with conditional caching; broader scans daily. |
| FINRA Query API | `FINRA_API_CLIENT_ID`, `FINRA_API_CLIENT_SECRET`, optional `FINRA_API_TOKEN` | Synchronous: 1,200 requests/minute/IP; async: 20 requests/minute/dataset/API account; 5,000 sync records/request | Reg SHO once after 6:00 p.m. ET and once next morning; short interest twice monthly plus one daily retry window after release dates. |
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
| Cerebras | `CEREBRAS_API_KEY` | Free API access exists; exact numeric free limit is not published on pricing page | Disabled until key is present; use only manual/offline public-fact tasks. |
| Mistral | `MISTRAL_API_KEY` | Free API tier exists; limits vary by subscription tier and model, exposed via response headers | Disabled until key is present; use only manual/offline public-fact tasks. |
| OpenRouter | `OPENROUTER_API_KEY` | Free models: 20 RPM and 50 requests/day before $10 credits; 1,000/day after $10 credits | Disabled while `PAID_USAGE_ALLOWED=false` unless using zero-credit free models under 25/day. |
| Hugging Face | `HF_TOKEN` | Hub free-user bucket: 1,000 API calls/5 minutes; Inference Providers include $0.10 monthly free credits | Disabled until token is present; embeddings/classification only, no paid overflow. |
