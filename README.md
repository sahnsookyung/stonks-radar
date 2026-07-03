# Stonks Radar | 스톡스 레이더

Global market intelligence dashboard. A public, bilingual Korean/English financial and geopolitical intelligence workbench built from immutable public snapshots, with authenticated research/admin surfaces behind Phoenix/Ecto/Oban.

The implementation follows `/Users/sookyungahn/Downloads/financial_research_workbench_public_global_one_shot_v8.md`:

- public routes read static JSON snapshots from `/public/latest/manifest.json` and `/public/v{n}/...`
- Phoenix owns auth, RBAC, audit, source review, ingestion, provider budgets, jobs, and publication
- PostgreSQL is canonical state; Valkey/Redis is cache/locks/rate counters only
- external credentials are optional at boot and required only for their matching providers
- local publisher mode can generate snapshots without OCI
- Cloudflare and OCI deployment state is codified in Terraform under `infra/cloudflare/terraform` and `infra/oci/terraform`
- observability defaults to edge/server metrics without third-party analytics beacons; see `docs/observability.md`

## Quick Start

```bash
npm install
npm run build:map-assets
npm run web:dev
```

Open `http://localhost:5173/en`.

For the backend stack:

```bash
cp .env.example .env
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

The API health endpoint is `http://localhost:8000/api/public/health`.
The production compose path intentionally exposes only Caddy on `80/443`; use
`compose.dev.yaml` for local Postgres, Valkey, API, and web ports.

## Required Credentials For Full Operation

The app runs with seeded snapshots without provider credentials. The following are needed for live ingestion, private/admin production operation, or publication:

- `ADMIN_BOOTSTRAP_PASSWORD`, `ADMIN_TOTP_SECRET`, `SESSION_SECRET`, `PASSWORD_PEPPER`
- Google admin OAuth, optional but preferred for private/admin portfolio data: `GOOGLE_OAUTH_ADMIN_ENABLED`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_ALLOWED_EMAILS` and/or `GOOGLE_OAUTH_ALLOWED_DOMAINS`
- Private Yahoo admin mode, disabled by default and never used for public snapshots: `YAHOO_ADMIN_ENABLED`
- provider keys: `FRED_API_KEY`, `BLS_API_KEY`, `EIA_API_KEY`, FINRA OAuth credentials (`FINRA_API_CLIENT_ID` and `FINRA_API_CLIENT_SECRET`, or legacy `FINRA_API_TOKEN`), plus optional market-data and LLM keys
- `SEC_USER_AGENT` with a real contact
- Cloudflare Terraform requires `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID`, and the OCI origin IPv4; object storage is not required

Missing credentials are reported through provider budgets/status and keep the public snapshot app usable.
Provider free-tier ceilings and refresh schedules are tracked in `docs/provider_rate_limits.md`.

## OGE Public Disclosure Use Warning

OGE public financial disclosure reports may not be obtained or used for unlawful
purposes, commercial purposes other than news/media dissemination to the public,
credit-rating purposes, or solicitation purposes. The Trump-family filings tab is
designed as public-interest research, journalism, and accountability tooling, not
as a paid trading-signal or copy-trading product.

## Main Commands

```bash
npm run web:build          # static public/admin web build
npm run web:test           # frontend unit tests
npm run web:e2e            # Playwright smoke tests
npm run backend:check      # Elixir dependency, compile, and contract checks
npm run backend:test       # full Phoenix/Ecto/Oban test suite
npm run test:all           # frontend unit + backend + Playwright checks
npm run build              # map assets + static web build
```

Production deploys run automatically after `main` passes CI and SonarQube via
`.github/workflows/production-autodeploy.yml`; `.github/workflows/deploy.yml`
remains available for manual clean, verify, or redeploy runs against the OCI
Compose stack.

Production target domain: `https://stonks.sookyungahn.com`.

## Layout

```text
apps/web                  React/Vite public + admin UI
apps/backend_elixir       Phoenix/Ecto/Oban backend, workers, and SafeFetch
packages/schemas          public snapshot and LLM JSON schemas
packages/i18n             UI locale/glossary assets
seeds                     source, geography, sector, scenario seeds
scripts                   deploy, map assets, runner setup, and backup helpers
infra                     Docker, Caddy, systemd, Cloudflare/OCI notes
docs                      architecture, policies, runbooks, data dictionary
tests                     Playwright public-route tests and shared fixtures
```
