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

Production deploys are handled by two workflows:

- `.github/workflows/production-autodeploy.yml`: watches `ci` and `sonarqube`
  workflow completions on `main`, verifies both are green for the same current
  commit SHA, then dispatches the deploy workflow once for that SHA.
- `.github/workflows/deploy.yml`: performs the OCI deployment and remains
  manually dispatchable for recovery, clean deploys, or explicit verification
  runs.

Default execution path: `github-hosted`.
Default deployment mode: `fast`.

The default GitHub-hosted path connects to OCI over SSH. It checks out the
repository, builds the web assets, syncs the checked-out release into
`/opt/stonks-radar`, writes the production env file, pulls the selected Elixir
API image for fast deploys, runs Docker Compose, refreshes the published
snapshot volume, and verifies local origin health.

The optional self-hosted path runs the same deployment script on the OCI
instance with runner labels `self-hosted`, `linux`, and
`stonks-radar-deploy`. Use it only after that runner is registered and visible in
GitHub repository settings; otherwise the job will queue indefinitely.

Deployment modes:

- `fast`: normal production path. Requires green CI and SonarQube for the target
  SHA, skips redundant Playwright/full test verification inside the deploy job,
  pulls the selected `ghcr.io/<owner>/stonks-radar-api-elixir:<tag>`, preserves
  Docker builder cache and Elixir build cache, and runs production smoke checks
  after start.
- `clean`: recovery path for disk pressure, suspected stale build state, or
  dependency weirdness. It reruns the full deploy verification gate and performs
  aggressive cache/image cleanup before rebuilding the API image on the OCI
  host.

The `ci.yml` ARM64 API-image job runs only when files that can affect the Elixir
API image change. When it runs on pushes to `main`, it publishes these tags:

- `ghcr.io/sahnsookyung/stonks-radar-api-elixir:<commit-sha>`
- `ghcr.io/sahnsookyung/stonks-radar-api-elixir:main`

Automatic production deploys use the immutable commit-SHA tag when the API image
changed. For web-only, content-only, or docs-only commits, autodeploy reuses the
existing `main` API image tag and avoids waiting for an unnecessary ARM64 image
build. Manual workflow dispatches can override this behavior with
`api_image_ref`; leave it blank for the current SHA or set it to `main` for a
known frontend/content-only redeploy.

Manual host deploys can pass the selected image explicitly:

```bash
STONKS_DEPLOY_MODE=fast \
  STONKS_API_IMAGE=ghcr.io/sahnsookyung/stonks-radar-api-elixir:<tag> \
  scripts/deploy.sh
```

Set `verify=true` on a manual dispatch to run the full in-deploy verification
without switching to clean mode. This is useful when you want fast-mode cache
preservation but still want the extra test gate.

Every deploy emits phase timings for `prepare-host`, `sync-release`,
`build-or-pull-api`, `migrate`, `start`, `refresh-snapshots`, and `smoke` in the
GitHub job summary.

Required repository or environment secrets:

- `STONKS_PRODUCTION_ENV_B64`: base64 encoding of the production env file

Additional secrets required for the default `github-hosted` SSH path:

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

Use the `self-hosted` workflow input only when the OCI runner is online. Normal
production deploys are automatic after green `main` CI and SonarQube gates. Use
manual dispatch when you need `clean` mode, `verify=true`, or an explicit
redeploy of a known-good SHA.

Manual host deploys use the same mode names:

```bash
STONKS_DEPLOY_MODE=fast scripts/deploy.sh
STONKS_DEPLOY_MODE=clean STONKS_DEPLOY_VERIFY=true scripts/deploy.sh
```

If `STONKS_API_IMAGE` is omitted, fast mode falls back to a local Compose build.
That fallback is useful for emergency host-only releases, but the normal path is
to let CI publish the ARM64 image first and then deploy the exact published SHA.

## GitHub Actions Terraform Plans

The Terraform workflow is manual-only: `.github/workflows/infra-plan.yml`.

Default execution path: `self-hosted`.

This workflow performs `terraform fmt`, `validate`, and `plan` for Cloudflare
and/or OCI without consuming GitHub-hosted minutes. It does not apply Terraform.
OCI apply remains intentionally manual until the existing instance is imported
into Terraform state and state storage is explicitly decided.
