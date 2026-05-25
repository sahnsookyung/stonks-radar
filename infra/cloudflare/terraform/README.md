# Cloudflare Terraform

This stack keeps Cloudflare DNS and zone behavior for Stonks Radar in code.

Requires Terraform `>= 1.6`.

Managed resources:

- `stonks.sookyungahn.com` proxied `A` record pointing at the OCI origin.
- Full HTTPS mode, always-use-HTTPS, automatic HTTPS rewrites, Brotli, HTTP/3, and TLS 1.2 minimum.
- Rocket Loader disabled.
- Optional Cloudflare Web Analytics site with `auto_install = false`, so Cloudflare does not inject `beacon.min.js`.

The application CSP remains managed by Caddy in `infra/Caddyfile`, because CSP needs to be versioned with the deployed web bundle.

Required Cloudflare API token permissions:

- `Zone:Read`
- `DNS:Edit`
- `Zone Settings:Edit`
- `Account Settings:Read` and `Account Settings:Edit` only if `manage_web_analytics = true`

Example:

```bash
cd infra/cloudflare/terraform
cp terraform.tfvars.example production.tfvars
terraform init
terraform plan -var-file=production.tfvars
terraform apply -var-file=production.tfvars
```

If Cloudflare already created a Web Analytics site for this zone, import it before setting `manage_web_analytics = true`:

```bash
terraform import -var-file=production.tfvars 'cloudflare_web_analytics_site.stonks_radar[0]' '<account_id>/<site_id>'
```

Use remote state before more operators share this stack. For a single-operator setup, local state is acceptable only if the state file is backed up privately and never committed.
