"""Compare probe-only Deployment behavior using two already scanned trial images."""
import argparse
import json
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from scripts.live_trial import command, kube, sample
from scripts.render_release import render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--healthy-trial", type=Path, required=True)
    parser.add_argument("--error-trial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if kube("config", "current-context").strip() != "k3d-release-lab":
        parser.error("Requires disposable k3d-release-lab context")
    images = {}
    for mode, source in (("healthy", args.healthy_trial), ("error", args.error_trial)):
        scan = json.loads((source / "scan.json").read_text())
        findings = [v for r in scan.get("Results", []) for v in r.get("Vulnerabilities", [])]
        if any(v["Severity"] in {"HIGH", "CRITICAL"} for v in findings):
            parser.error(f"{mode} artifact has unresolved scan findings")
        images[mode] = json.loads((source / "image.json").read_text())["digest"]
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    commit = command("git", "rev-parse", "HEAD").strip()
    log = (folder / "proxy.log").open("w")
    proxy = subprocess.Popen(["kubectl", "proxy", "--address=127.0.0.1", "--port=18002"], stdout=log, stderr=subprocess.STDOUT)
    summary = {"images": images, "source_head": commit, "samples": {}}
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with urlopen("http://127.0.0.1:18002/version", timeout=1):
                    break
            except (URLError, OSError):
                time.sleep(0.5)
        else:
            raise TimeoutError("Proxy did not start")
        url = "http://127.0.0.1:18002/api/v1/namespaces/demo-baseline/services/demo:80/proxy/"
        for mode in ("healthy", "error"):
            render(images[mode], commit, folder / mode, baseline=True)
            kube("apply", "-f", str(folder / mode))
            kube("rollout", "status", "deployment/release-demo", "-n", "demo-baseline", "--timeout=120s")
            expected = 200 if mode == "healthy" else 500
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if sample(url)["status"] == expected:
                    break
                time.sleep(0.5)
            rows = [sample(url) for _ in range(30)]
            summary["samples"][mode] = rows
            state = json.loads(kube("get", "deployment", "release-demo", "-n", "demo-baseline", "-o", "json"))
            (folder / f"{mode}-deployment.json").write_text(json.dumps(state, indent=2))
            available = any(c["type"] == "Available" and c["status"] == "True" for c in state["status"]["conditions"])
            if not available or any(row["status"] != expected for row in rows):
                raise AssertionError(f"Expected Available Deployment and thirty HTTP {expected} responses")
        summary["verdict"] = "probes-only-deployment-available-despite-http-500"
    except Exception as exc:
        summary.update(verdict="baseline-trial-failed", error=str(exc))
        raise
    finally:
        proxy.terminate()
        try:
            proxy.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proxy.kill()
            proxy.wait()
        log.close()
        # Preserve the native Deployment for inspection while releasing pod memory.
        try:
            kube("scale", "deployment/release-demo", "--replicas=0", "-n", "demo-baseline")
        except Exception as exc:
            summary["cleanup_error"] = str(exc)
        (folder / "summary.json").write_text(json.dumps(summary, indent=2))
    print(summary.get("verdict", "baseline-trial-failed"), flush=True)


if __name__ == "__main__":
    main()
