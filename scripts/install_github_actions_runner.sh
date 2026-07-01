#!/usr/bin/env bash
set -euo pipefail

repo_url="${GITHUB_RUNNER_REPO_URL:-https://github.com/${GITHUB_REPOSITORY:-sahnsookyung/stonks-radar}}"
runner_token="${GITHUB_RUNNER_TOKEN:-}"
runner_name="${GITHUB_RUNNER_NAME:-stonks-radar-$(hostname -s)}"
runner_labels="${GITHUB_RUNNER_LABELS:-stonks-radar-deploy}"
runner_user="${RUNNER_USER:-ubuntu}"
install_dir="${RUNNER_DIR:-/opt/actions-runner/stonks-radar}"
work_dir="${RUNNER_WORK_DIR:-_work}"

if [[ -z "$runner_token" ]]; then
  echo "GITHUB_RUNNER_TOKEN is required. Generate one with:" >&2
  echo "  gh api -X POST repos/sahnsookyung/stonks-radar/actions/runners/registration-token --jq .token" >&2
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  exec sudo -n env \
    GITHUB_RUNNER_REPO_URL="$repo_url" \
    GITHUB_RUNNER_TOKEN="$runner_token" \
    GITHUB_RUNNER_NAME="$runner_name" \
    GITHUB_RUNNER_LABELS="$runner_labels" \
    RUNNER_USER="$runner_user" \
    RUNNER_DIR="$install_dir" \
    RUNNER_WORK_DIR="$work_dir" \
    bash "$0"
fi

if ! id "$runner_user" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$runner_user"
fi

if getent group docker >/dev/null 2>&1; then
  usermod -aG docker "$runner_user"
fi

mkdir -p "$install_dir"
chown "$runner_user:$runner_user" "$install_dir"

arch="$(uname -m)"
case "$arch" in
  aarch64 | arm64) runner_arch="arm64" ;;
  x86_64 | amd64) runner_arch="x64" ;;
  *)
    echo "Unsupported runner architecture: $arch" >&2
    exit 1
    ;;
esac

runner_version="${GITHUB_RUNNER_VERSION:-}"
if [[ -z "$runner_version" ]]; then
  runner_version="$(
    curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \
      | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\([^"]*\)".*/\1/p' \
      | head -n 1
  )"
fi

archive="actions-runner-linux-${runner_arch}-${runner_version}.tar.gz"
download_url="https://github.com/actions/runner/releases/download/v${runner_version}/${archive}"

if [[ ! -x "$install_dir/config.sh" ]]; then
  tmp_dir="$(mktemp -d)"
  cleanup() {
    rm -rf "$tmp_dir"
  }
  trap cleanup EXIT
  curl -fsSL "$download_url" -o "$tmp_dir/$archive"
  tar -xzf "$tmp_dir/$archive" -C "$install_dir"
  chown -R "$runner_user:$runner_user" "$install_dir"
fi

cd "$install_dir"

if [[ -x bin/installdependencies.sh ]]; then
  ./bin/installdependencies.sh
fi

if [[ -f .runner ]]; then
  ./svc.sh stop || true
  sudo -u "$runner_user" ./config.sh remove --token "$runner_token" || true
fi

sudo -u "$runner_user" ./config.sh \
  --url "$repo_url" \
  --token "$runner_token" \
  --name "$runner_name" \
  --labels "$runner_labels" \
  --work "$work_dir" \
  --unattended \
  --replace

./svc.sh install "$runner_user"
./svc.sh start
./svc.sh status
