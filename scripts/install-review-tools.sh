#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $EUID == 0 ]] || { echo 'Run with sudo inside the lab Ubuntu distribution.' >&2; exit 1; }
[[ $(uname -m) == x86_64 ]] || { echo 'This installer supports amd64 only.' >&2; exit 1; }
version=$(python3 -c 'import json; print(json.load(open("versions.json"))["argo_rollouts"])')
expected=$(python3 -c 'import json; print(json.load(open("versions.json"))["argo_rollouts_cli_sha256"])')
cache=/var/cache/release-lab
mkdir -p "$cache" output/install
binary="$cache/kubectl-argo-rollouts-linux-amd64"
curl --fail --silent --show-error --location --connect-timeout 15 --max-time 300 --retry 3 \
  "https://github.com/argoproj/argo-rollouts/releases/download/$version/kubectl-argo-rollouts-linux-amd64" -o "$binary"
printf '%s  %s\n' "$expected" "$binary" | sha256sum --check -
install -m 0755 "$binary" /usr/local/bin/kubectl-argo-rollouts
printf '%s  kubectl-argo-rollouts-linux-amd64\n' "$expected" > output/install/argo-rollouts-cli.sha256
kubectl argo rollouts version
