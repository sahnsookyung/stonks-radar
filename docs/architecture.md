# Architecture

The public app is snapshot-first. Anonymous users fetch static assets from the OCI-hosted Caddy origin:

- `/public/latest/manifest.json`
- `/public/v{version}/{locale}/home.json`
- object snapshots for map, calendar, countries/regions, sectors, scenarios, status, and corrections

Phoenix/Ecto/Oban is used for authenticated owner/admin/editor workflows: ingestion, review, source policy, durable jobs, publication, quotas, and audit. PostgreSQL is canonical. Valkey/Redis is only for cache, locks, or rate counters.

Durable work uses Oban queues with runtime locks, retry backoff, dead-letter visibility, replay, and concurrency caps. The legacy `job_queue` table is read-only history after cutover.

Near-realtime watch signals use the same ingestion/review/publication pattern, but
with shorter refresh classes. FINRA daily short sale volume, short-research
publisher pages, SEC EDGAR filing monitors, and weak OSINT sources such as the
Pentagon pizza index should write candidate observations first, then publish only
source-labeled snapshot fields. Public pages still read immutable JSON snapshots;
the faster path is frequent signal snapshot publication, not direct anonymous
reads from live providers. Source policy must keep weak OSINT and daily short
sale volume distinct from stronger position/filing evidence.

Portfolio analytics are user-triggered rather than dashboard-hot. The browser
calls a fixed `/api/public/market/history` endpoint with symbols and dates; the
API validates ticker syntax, rate-limits the caller, fetches from an ordered
provider stack, caches results, and returns only daily closes. Provider keys stay
server-side. When no keys are configured the page still renders and uses
explicitly labeled sample data, preserving limited-capability hosting.

Snapshot publication is local to the OCI host. The Elixir backend writes validated candidate and published JSON into Docker volumes, and Caddy serves the published volume at `/public/...`.

Deployment uses a guarded production compose profile: only Caddy publishes host
ports `80/443`; Postgres, Valkey, the Elixir API, and web build services stay on
internal Docker networks. Local development adds `compose.dev.yaml` to expose
`5432`, `6379`, `8000`, and `5173`.
