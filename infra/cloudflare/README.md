# Cloudflare

Cloudflare is used for DNS/proxy/TLS in front of the OCI Caddy origin. The application and snapshot JSON are served by OCI; object storage is not part of the production path.

Authoritative configuration lives in `infra/cloudflare/terraform`. Apply Cloudflare changes through Terraform so DNS, HTTPS posture, Rocket Loader, and Web Analytics/RUM behavior do not drift from code.

Cache rules:

- static app assets: long TTL
- immutable snapshots: long TTL, immutable
- latest manifest: short TTL, ETag required
- correction/status snapshots: short TTL

CORS should allow only configured public origins. Never expose private source caches, database backups, or admin paths through public cache rules.

## Email alerts

`infra/cloudflare/email-worker.js` is the always-free inbound email bridge for company IR/news alerts. It only accepts configured recipients, rejects oversize messages, signs the JSON payload with `NEWS_EMAIL_WEBHOOK_SECRET`, and posts to `/api/internal/news/email-alerts`.

Recommended Cloudflare Worker secrets/vars:

- `NEWS_EMAIL_WEBHOOK_URL=https://stonks.sookyungahn.com/api/internal/news/email-alerts`
- `NEWS_EMAIL_WEBHOOK_SECRET`
- `NEWS_EMAIL_ALLOWED_RECIPIENTS`
- `NEWS_EMAIL_MAX_RAW_BYTES=1048576`
- optional `NEWS_EMAIL_FORWARD_TO` for a private audit mailbox copy
