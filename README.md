# Stonks Radar | 스톡스 레이더

Global market intelligence dashboard. A public, bilingual Korean/English financial and geopolitical intelligence workbench built from immutable public snapshots, with authenticated research/admin surfaces behind FastAPI.

The implementation follows `/Users/sookyungahn/Downloads/financial_research_workbench_public_global_one_shot_v8.md`:

- public routes read static JSON snapshots from `/public/latest/manifest.json` and `/public/v{n}/...`
- FastAPI owns auth, RBAC, audit, source review, ingestion, provider budgets, jobs, and publication
- PostgreSQL is canonical state; Valkey/Redis is cache/locks/rate counters only
- external credentials are optional at boot and required only for their matching providers
- local publisher mode can generate snapshots without OCI

## Quick Start

```bash
npm install
npm run build:map-assets
npm run seed:snapshots
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
- provider keys: `FRED_API_KEY`, `BLS_API_KEY`, `EIA_API_KEY`, `FINRA_API_TOKEN`, plus optional market-data and LLM keys
- `SEC_USER_AGENT` with a real contact
- Cloudflare DNS is optional if records are managed manually; object storage is not required

Missing credentials are reported through provider budgets/status and keep the public snapshot app usable.

## Main Commands

```bash
npm run web:build          # static public/admin web build
npm run web:test           # frontend unit tests
npm run web:e2e            # Playwright smoke tests
npm run api:compile        # Python syntax check without importing dependencies
npm run api:test           # pytest suite through uv
npm run seed:snapshots     # rebuild public seed snapshots
npm run check:schemas      # validate seed snapshots against checked-in schemas
npm run test:all           # schemas + unit + API + e2e + compile
npm run deploy:preflight   # OCI capacity + schemas + compose + migration SQL
```

Deployment remains approval-gated. `npm run deploy:preflight` must report at
least `2` A1 OCPUs, `12 GB` A1 memory, and `50 GB` storage headroom before the
guarded hosted target is eligible for an OCI run.

Production target domain: `https://stonks.sookyungahn.com`.

## Layout

```text
apps/web                  React/Vite public + admin UI
apps/api                  FastAPI app, SQL, auth, services, adapters
apps/worker               Postgres-backed worker entrypoints
apps/fetch-sandbox        isolated URL fetcher with SSRF guards
packages/schemas          public snapshot and LLM JSON schemas
packages/i18n             UI locale/glossary assets
seeds                     source, geography, sector, scenario seeds
scripts                   local publisher, partitions, budgets, storage monitors, backups
infra                     Docker, Caddy, systemd, Cloudflare/OCI notes
docs                      architecture, policies, runbooks, data dictionary
tests                     API/db/ingestion/LLM/publication/security tests
```
