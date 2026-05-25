# Deployment

Production is hosted on the OCI `stonks-radar` instance and does not use object
storage. Cloudflare is DNS/proxy/TLS in front of the OCI Caddy origin.

## Infrastructure As Code

Cloudflare state lives in `infra/cloudflare/terraform`:

- dashboard `A` record for `stonks.sookyungahn.com`
- HTTPS/edge zone settings
- Rocket Loader disabled
- Web Analytics auto-install disabled when the Web Analytics site is imported into state

OCI state lives in `infra/oci/terraform`:

- one `VM.Standard.A1.Flex` instance
- `2 OCPU`, `12 GB RAM`, `50 GB` boot volume
- no paid load balancer, managed database, NAT gateway, or object storage

Use `.github/workflows/infra-plan.yml` for manual Terraform plans once the
required secrets are configured. Do not apply OCI changes until the existing
instance has been imported into Terraform state.

## Secret Records

Generated production environment values are stored outside git:

- local record: `.secrets/stonks-radar.production.env`
- OCI runtime copy: `/opt/stonks-radar/.env`

Both files should be mode `600`. Do not commit either file. If a secret is
rotated, update both locations and restart the API/worker stack.

## GitHub Actions Deploy

The deploy workflow is manual-only: `.github/workflows/deploy.yml`.

Required repository or environment secrets:

- `STONKS_HOST`: OCI public IPv4 or DNS name
- `STONKS_USER`: SSH user, normally `ubuntu`
- `STONKS_DEPLOY_KEY`: private SSH key that can access the OCI host
- `STONKS_PRODUCTION_ENV_B64`: base64 encoding of the production env file

Create `STONKS_PRODUCTION_ENV_B64` from the local secret record:

```bash
base64 -i .secrets/stonks-radar.production.env | tr -d '\n'
```

The workflow runs tests, builds the web assets, rsyncs the repository to
`/opt/stonks-radar`, writes `.env`, runs Docker Compose, and checks local origin
health. It is intentionally not scheduled; production deploys require a manual
dispatch.
