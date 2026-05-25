# Observability And Anonymous Usage

Default policy: do not inject third-party analytics JavaScript. Cloudflare Web Analytics auto-install stays disabled in Terraform, and the app CSP does not allow `static.cloudflareinsights.com`.

Use these layers instead:

1. Cloudflare edge analytics

   Use Cloudflare's aggregated zone analytics for request volume, cache ratio, status codes, and security events. This requires no browser JavaScript and no application cookie.

2. Caddy and API logs

   Keep origin request logs structured and rotate them aggressively on the 50 GB OCI boot volume. Logs should include route, method, status, latency, response size, and request ID. Do not log raw query payloads, authorization headers, cookies, or source-document bodies.

3. First-party RUM, opt-in implementation

   If browser performance data is needed, add a same-origin endpoint such as `POST /api/public/rum` and send only sampled Web Vitals:

   - route template, not full URL
   - locale
   - device class and viewport bucket
   - connection `effectiveType` when available
   - CLS, LCP, INP, FCP, TTFB
   - build version

   Do not use cookies, localStorage IDs, fingerprinting fields, exact IP addresses, user-agent strings, or account identifiers. Aggregate server-side into hourly buckets and drop raw events after a short retention window.

4. Operations status

   Publish non-sensitive health summaries through the existing status snapshot path so admins and users can see stale data, degraded providers, disk pressure, queue health, and budget warnings.

If Cloudflare Web Analytics is intentionally enabled later, it must be represented in `infra/cloudflare/terraform`, reviewed against CSP, and validated for beacon behavior before deploy.

