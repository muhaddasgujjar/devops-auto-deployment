"""Opt-in check against the named local k3d lab; removes only its own namespace."""
import argparse
import json
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--context", required=True, choices=["k3d-release-lab"])
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
report_path = root / "docs/evidence/kubernetes-validation.json"
report_path.unlink(missing_ok=True)  # Never present a prior pass as evidence of a failed rerun.
namespace = "release-foundation"


def kubectl(*arguments):
    return subprocess.check_output(
        ["kubectl", "--context", args.context, *arguments], text=True, timeout=150
    ).strip()


# Refuse to adopt or modify a namespace that existed before this invocation.
existing = kubectl("get", "namespace", namespace, "--ignore-not-found", "-o", "name")
if existing:
    raise SystemExit("release-foundation already exists; inspect it before using this disposable check")

subprocess.run(["k3d", "image", "import", "release-foundation:milestone-1",
                "--cluster", "release-lab"], check=True, timeout=150)
kubectl("create", "-f", str(root / "demo/k8s/namespace.yaml"))
owned_uid = json.loads(kubectl("get", "namespace", namespace, "-o", "json"))["metadata"]["uid"]
forward = None
try:
    kubectl("apply", "-f", str(root / "demo/k8s/deployment.yaml"))
    kubectl("rollout", "status", "deployment/release-demo", "-n", namespace, "--timeout=120s")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryFile(mode="w+") as log:
        forward = subprocess.Popen(
            ["kubectl", "--context", args.context, "port-forward", "-n", namespace,
             "service/release-demo", f"{port}:80", "--address=127.0.0.1"],
            stdout=log, stderr=log,
        )
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            if forward.poll() is not None:
                log.seek(0)
                raise RuntimeError(log.read())
            try:
                with urlopen(base + "/readyz", timeout=2) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError, ConnectionError):
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("Port-forward did not become ready")
        responses = {}
        for path in ("/healthz", "/readyz", "/api/work", "/version", "/metrics"):
            with urlopen(base + path, timeout=3) as response:
                responses[path] = {"status": response.status, "body": response.read().decode()}
                assert response.status == 200
        pods = json.loads(kubectl("get", "pods", "-n", namespace, "-o", "json"))["items"]
        assert len(pods) == 2
        assert all(pod["status"]["containerStatuses"][0]["ready"] for pod in pods)
        report = {
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "context": args.context, "namespace": namespace, "passed": True,
            "ready_pods": len(pods), "responses": responses,
            "image_ids": [pod["status"]["containerStatuses"][0]["imageID"] for pod in pods],
            "scope": "Manual healthy rolling baseline; no fault recovery or automated GitOps claim",
        }
finally:
    if forward:
        forward.terminate()
        forward.wait(timeout=10)
    current_uid = json.loads(kubectl("get", "namespace", namespace, "-o", "json"))["metadata"]["uid"]
    if current_uid != owned_uid:
        raise RuntimeError("Namespace identity changed; refusing cleanup")
    kubectl("delete", "namespace", namespace, "--wait=true", "--timeout=60s")

report["temporary_namespace_removed"] = True
report_path.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
