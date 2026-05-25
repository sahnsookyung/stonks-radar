# Cloudflare

Cloudflare is used for DNS/proxy/TLS in front of the OCI Caddy origin. The application and snapshot JSON are served by OCI; object storage is not part of the production path.

Authoritative configuration lives in `infra/cloudflare/terraform`. Apply Cloudflare changes through Terraform so DNS, HTTPS posture, Rocket Loader, and Web Analytics/RUM behavior do not drift from code.

Cache rules:

- static app assets: long TTL
- immutable snapshots: long TTL, immutable
- latest manifest: short TTL, ETag required
- correction/status snapshots: short TTL

CORS should allow only configured public origins. Never expose private source caches, database backups, or admin paths through public cache rules.
