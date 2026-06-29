# Elixir Backend Compatibility Matrix

This matrix is the implementation gate for the Phoenix rewrite. React/Vite stays
unchanged until cutover, and the Python API remains the default production
backend unless Compose is run with the `elixir-backend` profile and Caddy is
explicitly retargeted in a later cutover change.

## Contract Levels

| Level | Gate | Purpose |
| --- | --- | --- |
| L0 DB-free smoke | `npm run backend:test:contract` or `cd apps/backend_elixir && mix test.contract` | Proves HTTP-observable route contracts that do not need persisted state. |
| L1 fixture-backed contracts | Phoenix tests using sanitized fixtures under `apps/backend_elixir/test/support/fixtures/` | Proves JSON shapes, status codes, cache headers, cookies, and validation failures without a live DB. |
| L2 staging cutover | Staging Compose with `--profile elixir-backend`, production secrets, and unchanged React build | Proves the big-bang cutover path before Caddy points at Phoenix. |

## Common HTTP Guardrails

All `/api/*` Phoenix responses must keep FastAPI-compatible security and CORS
behavior unless a route row says otherwise:

| Concern | Required behavior |
| --- | --- |
| Security headers | `x-content-type-options=nosniff`, `x-frame-options=DENY`, `referrer-policy=strict-origin-when-cross-origin`, and a restrictive `permissions-policy`. |
| CORS | Credentials enabled, origins limited to configured frontend origins, methods `GET,POST,PATCH,DELETE,OPTIONS`, and allow headers `Content-Type,x-csrf-token,x-stonks-timestamp,x-stonks-nonce,x-stonks-email-signature`. |
| Public cookies | Public and instrument discovery routes must not set `frw_session` or `frw_csrf`. |
| Session cookie | Password login and Google OAuth success set `frw_session`, `HttpOnly`, `SameSite=Lax`, `Max-Age=43200`, `path=/`, and `Secure` only in production. |
| CSRF token | Password login returns `csrf_token` in JSON. Google OAuth callback success also sets a short-lived non-HttpOnly `frw_csrf`, `Max-Age=300`; React copies that into `sessionStorage` and deletes the cookie. |
| Auth failures | Missing or invalid session returns `401` with `detail` text. Insufficient role returns `403`. Invalid CSRF returns `403` with `Invalid CSRF token`. |
| Market cache | `/api/public/market/history` returns public cache headers only for `status=ok`; license-limited and non-public payloads are `Cache-Control: no-store`. |
| Static snapshots | `/public/latest/manifest.json` stays Caddy/static-volume owned, `Cache-Control: no-cache, max-age=0, must-revalidate`; other `/public/*` snapshot files keep short public cache. |

## React Caller Notes

| React caller | Routes that must remain compatible |
| --- | --- |
| `AdminLogin` | `GET /api/auth/google/config`, `POST /api/auth/login`; reads `csrf_token` from JSON and stores it in `sessionStorage`. |
| `AdminDashboard` | `GET /api/admin/dashboard`, provider budgets, snapshots, jobs, facts/events, instruments, source docs, corrections, and audit routes; sends `x-csrf-token` from `syncCsrfTokenFromCookie()`. |
| `PortfolioLabPage` | `GET /api/auth/me`, `GET /api/instruments/search`, `POST /api/instruments/review-requests`, `GET /api/public/market/history`. |
| `TickerDetailPage` | `GET /api/public/market/history`, `GET /api/public/filings`, `GET /api/public/transactions`, `GET /api/public/entities/:ticker/insiders`. |
| `FundsTrackerPage` and `TrumpFilingsPage` | `GET /api/public/trump-disclosures/summary`. |
| Public snapshot app shell | `/public/latest/manifest.json` and `/public/v*/...` are served by Caddy, not Phoenix. |

## Endpoint Contract Rows

`Fixture tier` values: `L0` means DB-free Phoenix contract tests can run now;
`L1` means fixture/mocked data is required before the row is accepted; `L2`
means staging/prod deployment behavior is part of acceptance.

| ID | Method and path | React callers | Status and body contract | Header, cookie, and cache contract | Fixture tier |
| --- | --- | --- | --- | --- | --- |
| `public.health` | `GET /api/public/health` | deploy smoke | `200`; JSON includes `status=ok`, `service=stonks-radar-api`, `public_read_path=snapshot-first`, ISO `time`. | JSON, common security/CORS headers, no cookies. | L0 |
| `public.status` | `GET /api/public/status` | source/status ops | `200`; JSON includes `public_pages_depend_on_backend=false`, `snapshot_storage=local_oci`, `metrics` keys for snapshot age, dead letters, quotas, circuits, stale series, conflicts. | JSON, common headers, no cookies; fixture must cover missing manifest and present manifest. | L1 |
| `public.provider_status` | `GET /api/public/provider-status` | public diagnostics | `200`; JSON includes only public market-data provider entries. | JSON, common headers, no cookies; no private provider secrets. | L1 |
| `public.snapshot_manifest_proxy` | `GET /api/public/snapshot-manifest-proxy` | deploy smoke | `200`; JSON exactly identifies `/public/latest/manifest.json` and `local_oci`. | JSON, common headers, no cookies. | L0 |
| `public.trump_disclosures_summary` | `GET /api/public/trump-disclosures/summary?limit=80` | `FundsTrackerPage`, `TrumpFilingsPage` | `200`; preserves disclosure summary envelope and limit bounds `1..250`; validation errors remain `422` FastAPI-compatible until a Phoenix validation mapping is accepted. | JSON, common headers, no cookies. | L1 |
| `public.filings` | `GET /api/public/filings` | `TickerDetailPage` | `200`; supports `person`, `ticker`, `source=OGE|SEC`, `limit=1..250`; returns filings envelope. | JSON, common headers, no cookies. | L1 |
| `public.transactions` | `GET /api/public/transactions` | `TickerDetailPage` | `200`; supports `person`, `ticker`, `source=OGE|SEC`, `limit=1..500`; returns transactions envelope. | JSON, common headers, no cookies. | L1 |
| `public.entity_insiders` | `GET /api/public/entities/:ticker/insiders` | `TickerDetailPage` | `200`; strict ticker pattern `^[A-Za-z0-9.-]{1,16}$`; `limit=1..500`; returns insiders envelope. | JSON, common headers, no cookies. | L1 |
| `public.market_history` | `GET /api/public/market/history` | `PortfolioLabPage`, `TickerDetailPage` | `200` with stored public payload or `license_limited` fallback when approved historical data is unavailable; `400` for input errors such as malformed symbols, oversized symbol lists, and reversed dates. | `status=ok`: public cache, `ETag`, `Vary=Accept-Encoding`, `X-Market-Data-Source=stored-snapshot`; `license_limited` and validation errors: `Cache-Control=no-store`; no cookies. | L1 |
| `public.search` | `GET /api/public/search?q=` | global search/future | `200`; `q` length `2..80`; body includes `results`. | JSON, common headers, no cookies. | L1 |
| `auth.google_config` | `GET /api/auth/google/config` | `AdminLogin` | `200`; JSON includes `enabled`, `recommended`, `start_url`, `fallback_password_login`, `private_yahoo_admin_eligible`, `allowed_hint`. | JSON, common headers, no cookies. | L1 |
| `auth.google_start` | `GET /api/auth/google/start?redirect_to=` | OAuth button | `302` to Google when configured; `404` text when disabled; redirect target must be safe `/admin...`. | Common headers; no session cookies; writes only OAuth state/audit fixture rows. | L1 |
| `auth.google_callback` | `GET /api/auth/google/callback` | Google OAuth return | `302` to `/admin/login?oauth_error=...` on provider error; `400` missing or invalid state; `404` disabled; `403` unauthorized account; `302` to safe admin path on success. | Success sets `frw_session` and short-lived `frw_csrf`; failures do not set session cookies. | L1 |
| `auth.login` | `POST /api/auth/login` | `AdminLogin` | `200` `{"status":"ok","csrf_token":...}` on success; `200` `totp_required`; `401` text `Invalid credentials` or `Invalid TOTP code`. | Success sets only `frw_session`; no `frw_csrf` cookie; common headers. | L1 |
| `auth.logout` | `POST /api/auth/logout` | admin shell | `200` `{"status":"ok"}` with session; `401` without session. | Deletes `frw_session` and `frw_csrf`; common headers. | L1 |
| `auth.me` | `GET /api/auth/me` | `PortfolioLabPage`, admin shell | `200` with `id`, `email`, `role`; `401` `Not authenticated` or `Invalid session`. | Reads `frw_session`; sets no cookies. | L1 |
| `admin.dashboard` | `GET /api/admin/dashboard` | `AdminDashboard` | `200`; body includes `user`, `metrics`, `provider_budgets`, `dead_letter_jobs`, `source_health`, `candidate_facts`, `candidate_events`, `snapshot_candidates`; `401/403` auth failures. | Session required; no-store/admin-only cache policy; no new cookies. | L1 |
| `admin.provider_budgets` | `GET /api/admin/provider-budgets` | `AdminDashboard` | `200` `items`; `401/403` auth failures. | Viewer roles allowed; no-store/admin-only cache policy. | L1 |
| `admin.kill_switch` | `POST /api/admin/provider-budgets/:id/kill-switch` | `AdminDashboard` | `200` `{"status":"ok","enabled":bool}`; `401/403` auth/role/CSRF failures. | Owner/admin plus `x-csrf-token`; audit write required. | L1 |
| `admin.sources` | `GET /api/admin/sources` | admin source ops | `200` `items`; `401/403` auth failures. | Viewer roles; no-store/admin-only cache policy. | L1 |
| `admin.create_source` | `POST /api/admin/sources` | admin source ops | `200` `{"id":uuid}`; validation failures preserve existing detail shape. | Owner/admin plus CSRF; audit write required. | L1 |
| `admin.instrument_search` | `GET /api/admin/instruments/search` | `AdminDashboard` | `200`; empty `q` defaults to `A`; includes advanced/inactive results for import reconciliation. | Viewer roles; no-store/admin-only cache policy. | L1 |
| `admin.instrument_review_requests` | `GET /api/admin/instruments/review-requests` | `AdminDashboard` | `200` `items` capped at 200. | Viewer roles; no-store/admin-only cache policy. | L1 |
| `admin.update_instrument_review_request` | `POST /api/admin/instruments/review-requests/:id` | `AdminDashboard` | `200` `{"status":"ok"}`; `400` invalid status; `404` missing request. | Owner/admin/editor plus CSRF; audit write required. | L1 |
| `admin.instrument_detail` | `GET /api/admin/instruments/:id` | admin detail | `200` detail or `404` `Instrument not found`; supports `listing_id`. | Viewer roles; no-store/admin-only cache policy. | L1 |
| `admin.refresh_instruments` | `POST /api/admin/instruments/refresh` | `AdminDashboard` | `200` `{"status":"refreshed","job_id":...,"refresh":...}`; Elixir job IDs use `oban:<id>` after cutover. | Owner/admin plus CSRF; audit write required; Oban enqueue fixture required. | L1 |
| `admin.ingest_url` | `POST /api/admin/ingest/url` | admin source ops | `200` document `id`; `400` SafeFetch/source ingestion error detail. | Owner/admin/editor plus CSRF; must use fetch-sandbox in production. | L1 |
| `admin.summaries_url` | `POST /api/admin/summaries/url` | admin source ops | `200` summary payload; `400` invalid URL/content; `403` budget disabled/exceeded. | Owner/admin plus CSRF; LLM budget/audit fixture required. | L1 |
| `admin.ingest_file` | `POST /api/admin/ingest/file` | admin source ops | `200` `manual_file_ingestion_requires_private_storage_policy`. | Owner/admin/editor plus CSRF; no external storage dependency. | L1 |
| `admin.source_document` | `GET /api/admin/source-documents/:id` | admin source ops | `200` row or `404` `Document not found`. | Viewer roles; no-store/admin-only cache policy. | L1 |
| `admin.review_fact` | `POST /api/admin/source-facts/:id/review` | `AdminDashboard` | `200` `{"status":"ok"}`; `400` publication gate failure; `404` missing fact. | Owner/admin/editor plus CSRF; audit write required. | L1 |
| `admin.event_candidates` | `GET /api/admin/events/candidates` | `AdminDashboard` | `200` `items` capped at 100. | Viewer roles; no-store/admin-only cache policy. | L1 |
| `admin.review_event` | `POST /api/admin/events/:id/review` | `AdminDashboard` | `200` `{"status":"ok"}`; `400` publication gate reason; `404` missing event. | Owner/admin/editor plus CSRF; audit write required. | L1 |
| `admin.snapshots_build` | `POST /api/admin/snapshots/build` | `AdminDashboard` | `200` `{"status":"queued","job_id":...}`; Elixir job IDs use `oban:<id>`. | Owner/admin/editor plus CSRF; Oban enqueue fixture required. | L1 |
| `admin.snapshots_candidates` | `GET /api/admin/snapshots/candidates` | `AdminDashboard` | `200` `items`. | Viewer roles; no-store/admin-only cache policy. | L1 |
| `admin.snapshots_publish` | `POST /api/admin/snapshots/publish` | `AdminDashboard` | `200` build result; `400` invalid version/error detail. | Owner/admin plus CSRF; published snapshot volume fixture required. | L1 |
| `admin.snapshots_rollback` | `POST /api/admin/snapshots/rollback` | `AdminDashboard` | `200` build result; `400` invalid version/error detail. | Owner/admin plus CSRF; published snapshot volume fixture required. | L1 |
| `admin.replay_job` | `POST /api/admin/jobs/:id/replay` | `AdminDashboard` | `200` `{"status":"ok","job_id":...}` for `oban:<id>`; `404` invalid/missing legacy job; accepts `legacy:<uuid>` during migration readback. | Owner/admin plus CSRF; Oban/legacy fixture required. | L1 |
| `admin.create_correction` | `POST /api/admin/corrections` | `AdminDashboard` | `200` `{"id":uuid}`; `400` invalid status. | Owner/admin/editor plus CSRF; audit write required. | L1 |
| `admin.audit_log` | `GET /api/admin/audit-log` | `AdminDashboard` | `200` `items` capped at 200. | Viewer roles; no-store/admin-only cache policy. | L1 |
| `admin.snapshots_build_now_local` | `POST /api/admin/snapshots/build-now-local` | `AdminDashboard` | `200` synchronous candidate build result. | Owner/admin/editor plus CSRF; local artifacts fixture required. | L1 |
| `admin.snapshots_build_seed_local` | `POST /api/admin/snapshots/build-seed-local` | `AdminDashboard` | `200` seed/public snapshot build result. | Owner/admin/editor plus CSRF; must not mutate production volume in tests. | L1 |
| `instruments.search` | `GET /api/instruments/search` | `PortfolioLabPage` | `200`; supports trimmed `q`, `limit=1..25`, country/exchange/asset filters, advanced/inactive flags, and context; `422` FastAPI-compatible validation errors. | Public route; JSON, common headers, `Cache-Control=no-store`, no cookies; rate limit policy preserved. | L1 |
| `instruments.resolve` | `POST /api/instruments/resolve` | import/reconciliation | `200`; returns resolved symbol/name/exchange/currency/ISIN candidate payload; `422` for blank or malformed symbols. | Public route; JSON, common headers, `Cache-Control=no-store`, no cookies. | L1 |
| `instruments.detail` | `GET /api/instruments/:id` | future detail | `200` detail, `404` `Instrument not found`, or `422` for malformed instrument/listing IDs; supports `listing_id`. | Public route; JSON, common headers, `Cache-Control=no-store`, no cookies. | L1 |
| `instruments.review_requests` | `POST /api/instruments/review-requests` | `PortfolioLabPage` | `200` `{"id":...,"status":"queued"}` or deduped `{"id":...,"status":...,"deduped":true}`. | Public route; no cookies; per-IP/query/context one-day dedupe and rate limit preserved. | L1 |
| `internal.news_email_alerts` | `POST /api/internal/news/email-alerts` | webhook only | `200` accepted result; `401` invalid/missing/stale/replayed signature; `403` recipient not allowed; `400` malformed payload; `503` disabled. | Requires `x-stonks-timestamp`, `x-stonks-nonce`, `x-stonks-email-signature`; no browser cookies. | L1 |
| `static.latest_manifest` | `GET /public/latest/manifest.json` | React public snapshot loader | `200` static manifest from published snapshot volume. Phoenix must not own this route before cutover. | Caddy-owned `Cache-Control=no-cache, max-age=0, must-revalidate`; `/public/*` keeps short public cache. | L2 |

## Fixture Capture Strategy

Do not capture from live services in CI. Fixture capture is a local, explicit
developer task:

1. Start the current Python API against a seeded local database or test fixture
   database, never production.
2. Exercise each matrix row with deterministic inputs from this file.
3. Store only sanitized request/response pairs under
   `apps/backend_elixir/test/support/fixtures/compatibility/<row-id>.json`.
4. Include status, selected response headers, response cookies metadata, and
   body shape. Redact bearer tokens, session values, OAuth state, emails, IPs,
   provider keys that are secrets, and any personal data.
5. Phoenix contract tests should load fixtures with
   `StonksBackendWeb.ContractCase.load_fixture/1` and assert subsets plus
   route-specific invariants, not byte-for-byte timestamps or UUIDs.
6. Rows involving Oban, snapshot files, SafeFetch, OAuth, or email webhooks must
   use mocks/fixtures. They must not call external networks, Google, market data
   providers, LLM providers, or live email services.

## NPM, Mix, and Compose Alignment

| Surface | Guardrail |
| --- | --- |
| npm | `backend:test:contract` runs the Mix contract alias from repo root. `backend:check` fetches Elixir deps, compiles Phoenix, and runs the contract gate. Root `test` stays Python/React-only while Elixir is optional; `test:all` may include `backend:check`, but it does not imply production cutover. |
| Mix | `mix test.contract` runs only tests tagged `:contract`, including DB-free and fixture-backed HTTP contracts. Non-contract Phoenix controller/domain tests remain under `backend:test`. |
| Compose dev | `api` remains Python on port `8000`; `api-elixir` is available on host `8001` only when `--profile elixir-backend` is used. |
| Compose prod | `api-elixir` inherits the `elixir-backend` profile from `compose.yaml`; Caddy still proxies `/api/*` to `api:8000` until a deliberate cutover patch changes it. The profile service must expose a container healthcheck on `/api/public/health`. |
| Published snapshots | `published-snapshots` volume remains shared read/write by backend workers and read-only by Caddy. Contract tests must use temp fixtures, not the real production volume. |

## Operations Validation

Run these checks before staging an Elixir backend cutover:

1. `docker compose -f compose.yaml -f infra/docker-compose.prod.yml config --services`
   must list `api` and must not list `api-elixir`.
2. `docker compose --profile elixir-backend -f compose.yaml -f infra/docker-compose.prod.yml config --services`
   must list both `api` and `api-elixir`; Caddy still depends on `api`.
3. Production `api-elixir` requires real `PHX_SECRET_KEY_BASE`,
   `SESSION_SECRET`, and `PASSWORD_PEPPER` values from the production secret
   file or environment whenever the release runs with `MIX_ENV=prod` or
   `APP_ENV=production|prod`. Base Compose must not provide development
   fallbacks for those secrets.
4. With the profile enabled, `api-elixir` must report healthy through
   `/api/public/health` before any proxy retargeting is considered.
5. Queue and snapshot readiness remain acceptance checks through
   `/api/public/status`: snapshot age, dead-letter jobs, quota-wait jobs, open
   provider circuits, stale series, and conflicts must be reviewed during
   staging and production go/no-go.

## Cutover Acceptance Criteria

- Every matrix row has at least one Phoenix contract test at L0 or L1.
- React/Vite source and generated public snapshots are unchanged by the backend
  rewrite, except for separately approved generated fixture updates.
- Caddy continues to point at Python `api:8000` until the final big-bang patch;
  the Elixir service must not replace Python unless the `elixir-backend` profile
  is enabled and the proxy target is intentionally changed.
- Oban is the only durable executor after cutover; legacy `job_queue` rows are
  frozen after migration and surfaced only through admin projections/replay
  compatibility.
- SafeFetch uses the fetch-sandbox in production until explicit SSRF and
  resource-limit signoff.
- Staging proves unchanged admin login, CSRF, source admin, portfolio lookup,
  market history, snapshot publish/rollback, email webhook, and public static
  manifest flows.
- Production go/no-go requires `docker compose config` verification showing
  Python remains default without the profile, `mix test.contract`,
  `backend:check`, Python `api:test`, deploy preflight, and a live smoke that
  checks `/api/public/health`, `/api/auth/google/config`, and
  `/public/latest/manifest.json`.
