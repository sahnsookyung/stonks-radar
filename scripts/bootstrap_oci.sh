#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -m)" != "aarch64" && "$(uname -m)" != "arm64" ]]; then
  echo "OCI Ampere target should be ARM64; continuing only for bootstrap script validation." >&2
fi

sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git rsync
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
echo "Install Caddy through Docker Compose; configure .env before first deploy."
