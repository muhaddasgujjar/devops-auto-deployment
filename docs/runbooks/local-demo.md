# Foundation workload runbook

This is the retained isolated foundation fixture. The main project uses `demo/app.py`
and [the canonical lab runbook](../lab.md). Foundation application and manifest paths
in this guide now live under `examples/foundation/`.

## Native Windows execution

```powershell
python scripts/validate.py
$env:APP_REVISION = 'healthy-1'
$env:DEMO_MODE = 'healthy'
python examples/foundation/app/server.py
```

Use a second shell for `curl.exe http://127.0.0.1:8080/api/work`. Stop the server with Ctrl+C. Set `DEMO_MODE` to `errors`, `unready`, or `latency` before restarting for a controlled fault. The service has no runtime fault mutation endpoint. `DEMO_LATENCY_SECONDS` defaults to 0.25 and must be between zero and five seconds. Unready mode represents a failed readiness check, not process failure.

The Python standard-library server is deliberately a small trusted-lab workload. It is not an internet-facing product API. Request counters include `/api/work` only. Duration measures handler execution, not client-observed network latency. Metrics reset on restart and carry revision labels; no Prometheus server is required for native checks.

## Docker in Ubuntu/WSL

From this checkout in WSL (typically `/mnt/c/Users/hasnat/OneDrive/Documents/ChatGPT/Deveops`):

```bash
PYTHON_IMAGE=$(python3 -c 'import json; print(json.load(open("versions.json"))["foundation_python_image"])')
docker build --build-arg "PYTHON_IMAGE=$PYTHON_IMAGE" -t release-foundation:milestone-1 examples/foundation/app
python3 scripts/verify_container.py
```

The verification script creates three short-lived containers with dynamically assigned loopback ports, validates health/fault behavior and non-root execution, then stops/removes only those containers. It records the local image ID; this is not a pushed registry manifest digest or a vulnerability scan.

## Manual Kubernetes baseline

For the opt-in disposable check, first generate/select the lab kubeconfig as shown below, then run `python3 scripts/verify_kubernetes.py --context k3d-release-lab`. The script imports the built image, refuses an existing `release-foundation` namespace, starts two replicas, checks the service through a loopback forward, records evidence, and removes its own namespace. Do not separately apply the namespace before using that script. Keep WSL active during the check and wait for the API readiness endpoint after WSL resumes.

Use an explicitly selected local lab context. Do not apply to a shared or production context. The dedicated namespace is `release-foundation`; existing `demo-dev` workloads are not targets of these files.

For an existing k3d cluster named `release-lab`:

```bash
mkdir -p tmp
k3d kubeconfig get release-lab > tmp/foundation.kubeconfig
export KUBECONFIG="$PWD/tmp/foundation.kubeconfig"
k3d image import release-foundation:milestone-1 --cluster release-lab
kubectl apply -f examples/foundation/k8s/namespace.yaml
kubectl apply -f examples/foundation/k8s/deployment.yaml
kubectl rollout status deployment/release-demo -n release-foundation --timeout=120s
kubectl port-forward -n release-foundation service/release-demo 8085:80 --address=127.0.0.1
```

In a second Linux shell, request `http://127.0.0.1:8085/api/work` and `/metrics`. Stop forwarding with Ctrl+C. The starter uses an imported local tag; registry delivery must replace it with an immutable registry digest in the CI/GitOps milestone. This baseline does not configure auto-rollback or Prometheus scraping. Do not use successful readiness as proof of application correctness.

No kubeconfig or secret belongs in Git. The sample does not require Kubernetes API credentials in its pods. To free resources after a disposable check, delete only the explicitly created `release-foundation` namespace; do not remove the existing cluster or unrelated namespaces.

## Technical references

- [Kubernetes health and readiness probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/)
- [Prometheus text exposition](https://prometheus.io/docs/instrumenting/exposition_formats/)
- [Dockerfile instructions](https://docs.docker.com/reference/dockerfile/)
