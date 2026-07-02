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
rotated, update both locations and restart the Phoenix/Oban runtime stack.

## GitHub Actions Deploy

The deploy workflow is manual-only: `.github/workflows/deploy.yml`.

Default execution path: `self-hosted`.

The self-hosted path runs on the OCI instance with runner labels
`self-hosted`, `linux`, and `stonks-radar-deploy`. This avoids GitHub-hosted
runner minutes and keeps deploys available when GitHub-hosted jobs are blocked
by account billing/spending-limit state. It checks out the repository, runs the
normal test/build gates, syncs the checked-out release into `/opt/stonks-radar`,
writes the production env file, runs Docker Compose, refreshes the published
snapshot volume, and verifies local origin health.

Required repository or environment secrets:

- `STONKS_PRODUCTION_ENV_B64`: base64 encoding of the production env file

Additional secrets required only for the `github-hosted` SSH fallback:

- `STONKS_HOST`: OCI public IPv4 or DNS name
- `STONKS_USER`: SSH user, normally `ubuntu`
- `STONKS_DEPLOY_KEY`: private SSH key that can access the OCI host

Create `STONKS_PRODUCTION_ENV_B64` from the local secret record:

```bash
base64 -i .secrets/stonks-radar.production.env | tr -d '\n'
```

One-time OCI runner bootstrap:

```bash
RUNNER_TOKEN="$(gh api -X POST \
  repos/sahnsookyung/stonks-radar/actions/runners/registration-token \
  --jq .token)"

scp scripts/install_github_actions_runner.sh ubuntu@<oci-host>:/tmp/
printf '%s\n' "$RUNNER_TOKEN" | ssh ubuntu@<oci-host> '
  read -r GITHUB_RUNNER_TOKEN
  export GITHUB_RUNNER_TOKEN
  export GITHUB_REPOSITORY=sahnsookyung/stonks-radar
  export RUNNER_USER=ubuntu
  bash /tmp/install_github_actions_runner.sh
'
```

The runner service must have Docker access and write access to
`/opt/stonks-radar`. The installer adds the runner user to the Docker group when
that group exists; log out/in or restart the service if group membership was
changed after Docker was installed.

Use the `github-hosted` workflow input only when GitHub-hosted runner billing is
healthy. Production deploys are intentionally not scheduled; they require manual
dispatch.

## GitHub Actions Terraform Plans

The Terraform workflow is manual-only: `.github/workflows/infra-plan.yml`.

Default execution path: `self-hosted`.

This workflow performs `terraform fmt`, `validate`, and `plan` for Cloudflare
and/or OCI without consuming GitHub-hosted minutes. It does not apply Terraform.
OCI apply remains intentionally manual until the existing instance is imported
into Terraform state and state storage is explicitly decided.
