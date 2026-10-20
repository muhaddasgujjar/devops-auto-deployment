#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for tool in docker k3d kubectl python3; do
  command -v "$tool" >/dev/null || { echo "Missing prerequisite: $tool" >&2; exit 1; }
done
docker info >/dev/null
expected=$(python3 -c 'import json; print(json.load(open("versions.json"))["k3d"])')
[[ $(k3d version | head -n 1) == "k3d version $expected"* ]] || { echo "Install k3d $expected" >&2; exit 1; }
mkdir -p output
# Refuse reuse: never silently change an existing cluster or another kube context.
if k3d cluster list -o json | python3 -c 'import json,sys; sys.exit(0 if any(x["name"] == "release-lab" for x in json.load(sys.stdin)) else 1)'; then
  echo "release-lab already exists; use output/lab.kubeconfig to inspect it." >&2
  exit 1
fi
k3d cluster create --config platform/k3d.yaml
k3d kubeconfig get release-lab > output/lab.kubeconfig
chmod 600 output/lab.kubeconfig
export KUBECONFIG="$PWD/output/lab.kubeconfig"
kubectl apply -f templates/release/namespace.yaml
kubectl create namespace argo-rollouts --dry-run=client -o yaml | kubectl apply -f -
version=$(python3 -c 'import json; print(json.load(open("versions.json"))["argo_rollouts"])')
kubectl apply --server-side -n argo-rollouts -f "https://github.com/argoproj/argo-rollouts/releases/download/$version/install.yaml"
kubectl wait --for=condition=Established crd/rollouts.argoproj.io --timeout=120s
kubectl rollout status -n argo-rollouts deployment/argo-rollouts --timeout=180s
kubectl apply -f platform/monitoring.yaml
kubectl rollout status -n monitoring deployment/prometheus --timeout=180s
echo "Lab ready. export KUBECONFIG=$PWD/output/lab.kubeconfig"
