"""Run one controlled trial on the disposable k3d lab and retain raw evidence.

Needs docker and kubectl on PATH and KUBECONFIG pointing to release-lab.
Use only before delegating deployment ownership to Argo CD.
"""
import argparse
import hashlib
import json
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request

from scripts.render_release import ROOT, render


def command(*args, timeout=180):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{args[0]} {args[1:3]} failed: {result.stderr[-4000:]}")
    return result.stdout


def kube(*args):
    return command("kubectl", "--request-timeout=15s", *args)


def resource(kind, name=None):
    args = ["get", kind]
    if name:
        args.append(name)
    return json.loads(kube(*args, "-n", "demo-dev", "-o", "json"))


def service_hash():
    return resource("service", "demo-stable")["spec"]["selector"].get("rollouts-pod-template-hash")


def now():
    return datetime.now(timezone.utc).isoformat()


def sample(url, preview=False):
    start = time.monotonic()
    result = {"timestamp": now()}
    try:
        with urlopen(Request(url, headers={'X-Release-Preview': 'true'} if preview else {}), timeout=3) as response:
            result.update(status=response.status, response=json.loads(response.read()))
    except HTTPError as exc:
        result["status"] = exc.code
        try:
            result['response'] = json.loads(exc.read())
        except (ValueError, OSError):
            pass
        exc.close()
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        result.update(status=0, error=type(exc).__name__)
    result["duration_seconds"] = round(time.monotonic() - start, 6)
    return result


def build(mode, commit, folder):
    tag = f"localhost:5001/release-demo:trial-{folder.name}-{mode}"
    print(f"Building {mode}", flush=True)
    log = command("docker", "build", "-f", "demo/Dockerfile", "--build-arg", f"DEMO_MODE={mode}",
                  "--build-arg", f"APP_REVISION={commit}", "-t", tag, ".", timeout=600)
    (folder / "build.log").write_text(log)
    command("trivy", "image", "--quiet", "--scanners", "vuln", "--severity", "HIGH,CRITICAL",
            "--exit-code", "1", "--format", "json", "--output", str(folder / "scan.json"), tag, timeout=600)
    command("trivy", "image", "--quiet", "--format", "cyclonedx", "--output", str(folder / "sbom.json"), tag, timeout=300)
    command("docker", "push", tag, timeout=300)
    command("docker", "pull", tag, timeout=300)
    image = json.loads(command("docker", "image", "inspect", tag))[0]
    digest = next(ref for ref in image["RepoDigests"] if ref.startswith("localhost:5001/release-demo@sha256:"))
    (folder / "image.json").write_text(json.dumps({"tag": tag, "digest": digest}, indent=2))
    return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=["initial", "healthy", "error", "latency", "startup", "no-traffic", "telemetry-outage"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    context = kube("config", "current-context").strip()
    if context != "k3d-release-lab":
        parser.error(f"Requires disposable k3d-release-lab context, received {context!r}")
    existing = kube("get", "rollout", "release-demo", "-n", "demo-dev", "-o", "json", "--ignore-not-found")
    if any(key in existing for key in ("argocd.argoproj.io/instance", "argocd.argoproj.io/tracking-id")):
        parser.error("Argo CD already owns this workload; run trials through environment Git instead")
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    commit = command("git", "rev-parse", "HEAD").strip()
    files = command("git", "ls-files", "--cached", "--others", "--exclude-standard").splitlines()
    source = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files if (ROOT / name).is_file()}
    (folder / "source.json").write_text(json.dumps({"head": commit, "status": command("git", "status", "--porcelain"), "files": source}, indent=2))
    mode = args.scenario if args.scenario in {"error", "latency", "startup"} else "healthy"
    image = build(mode, commit, folder)
    if args.scenario == "initial":
        old_hash = None
    else:
        old_hash = service_hash()
        if not old_hash:
            raise RuntimeError("Establish and verify the healthy initial revision first")
    render(image, commit, folder / "desired")
    # Force a fresh pod-template hash for every trial even when source/image bytes repeat.
    rollout = folder / "desired" / "rollout.yaml"
    content = rollout.read_text()
    content = content.replace("value: \"" + commit + "\"", "value: \"" + commit + "-" + folder.name + "\"")
    rollout.write_text(content)
    stop = threading.Event()
    threads = []
    proxy_log = (folder / "proxy.log").open("w")
    proxy = subprocess.Popen(["kubectl", "proxy", "--address=127.0.0.1", "--port=18001"], stdout=proxy_log, stderr=subprocess.STDOUT)
    proxy_root = "http://127.0.0.1:18001/api/v1/namespaces/demo-dev/services/"

    def traffic(service, filename):
        with (folder / filename).open("a") as stream:
            while not stop.is_set():
                row = sample(proxy_root + service + ":80/proxy/", preview=service == 'demo-preview')
                stream.write(json.dumps(row) + "\n")
                stream.flush()
                stop.wait(0.2)

    summary = {"scenario": args.scenario, "started": now(), "previous_stable_hash": old_hash, "image": image}
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if proxy.poll() is not None:
                raise RuntimeError("kubectl proxy failed; inspect proxy.log")
            try:
                with urlopen("http://127.0.0.1:18001/version", timeout=1):
                    break
            except (URLError, OSError):
                time.sleep(0.5)
        else:
            raise TimeoutError("kubectl proxy did not become available")
        if old_hash:
            check = sample(proxy_root + "demo-stable:80/proxy/")
            if check.get("status") != 200 or check.get("response", {}).get("mode") != "healthy":
                raise RuntimeError("Existing stable service is not verified healthy")
            thread = threading.Thread(target=traffic, args=("demo-stable", "stable.jsonl"), daemon=True)
            thread.start()
            threads.append(thread)
        if args.scenario == "telemetry-outage":
            kube("scale", "deployment/prometheus", "--replicas=0", "-n", "monitoring")
            telemetry_deadline = time.monotonic() + 60
            while json.loads(kube("get", "pods", "-l", "app=prometheus", "-n", "monitoring", "-o", "json"))["items"]:
                if time.monotonic() >= telemetry_deadline:
                    raise TimeoutError("Prometheus did not stop within 60 seconds")
                time.sleep(1)
        kube("apply", "-f", str(folder / "desired"))
        if args.scenario not in {"initial", "startup", "no-traffic"}:
            for i in range(4):
                thread = threading.Thread(target=traffic, args=("demo-preview", f"preview-{i}.jsonl"), daemon=True)
                thread.start()
                threads.append(thread)
        deadline = time.monotonic() + 900
        verdict = None
        while time.monotonic() < deadline:
            obj = resource("rollout", "release-demo")
            status = obj.get("status", {})
            candidate = status.get("currentPodHash")
            current_runs = [r for r in resource("analysisrun").get("items", [])
                            if r["metadata"].get("labels", {}).get("rollouts-pod-template-hash") == candidate]
            phases = [r.get("status", {}).get("phase") for r in current_runs]
            observed = str(status.get("observedGeneration")) == str(obj["metadata"]["generation"])
            if observed and candidate and candidate != old_hash:
                if args.scenario == "initial" and status.get("phase") == "Healthy":
                    verdict = "baseline-established"
                elif args.scenario == "healthy" and status.get('phase') == 'Healthy' and "Successful" in phases and service_hash() == candidate:
                    verdict = "candidate-promoted"
                elif args.scenario in {"error", "latency"} and "Failed" in phases and status.get("abort"):
                    verdict = "candidate-rejected"
                elif args.scenario == "startup" and status.get("abort"):
                    verdict = "readiness-aborted"
                elif args.scenario == "no-traffic" and "Inconclusive" in phases:
                    verdict = "missing-traffic-inconclusive"
                elif args.scenario == "telemetry-outage" and any(p in {"Error", "Inconclusive"} for p in phases):
                    verdict = "missing-telemetry-blocked"
                if verdict:
                    if old_hash and args.scenario != "healthy" and service_hash() != old_hash:
                        raise AssertionError("Stable selector changed during a rejected candidate")
                    break
            time.sleep(3)
        if not verdict:
            raise TimeoutError("Expected controller outcome not observed within 300 seconds")
        final_response = sample(proxy_root + "demo-stable:80/proxy/")
        if final_response.get("status") != 200 or final_response.get("response", {}).get("mode") != "healthy":
            raise AssertionError("Stable service is not healthy after the controller decision")
        if args.scenario in {"initial", "healthy"}:
            if final_response.get("response", {}).get("revision") != commit + "-" + folder.name:
                raise AssertionError("Serving revision does not match the promoted candidate")
        summary["final_response"] = final_response
        summary.update(verdict=verdict, finished=now(), serving_hash=service_hash())
    except Exception as exc:
        summary.update(verdict="trial-failed", error=str(exc), finished=now())
        raise
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=5)
        for kind in ("rollout", "analysisrun", "pod", "service", "event"):
            try:
                (folder / f"{kind}.json").write_text(kube("get", kind, "-n", "demo-dev", "-o", "json"))
            except Exception as exc:
                summary[f"capture_{kind}_error"] = str(exc)
        if args.scenario == "telemetry-outage":
            try:
                kube("scale", "deployment/prometheus", "--replicas=1", "-n", "monitoring")
            except Exception as exc:
                summary["telemetry_restore_error"] = str(exc)
        proxy.terminate()
        try:
            proxy.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proxy.kill()
            proxy.wait()
        proxy_log.close()
        stable_file = folder / "stable.jsonl"
        if stable_file.exists():
            rows = [json.loads(row) for row in stable_file.read_text().splitlines()]
            summary["stable_requests"] = len(rows)
            summary["stable_non_200"] = sum(row["status"] != 200 for row in rows)
            if summary["stable_non_200"]:
                summary["availability_verdict"] = "failed-requests-observed"
        (folder / "summary.json").write_text(json.dumps(summary, indent=2))
        from scripts.evidence import finalize_archive
        finalize_archive(folder)
    print(json.dumps(summary), flush=True)
    if summary.get("stable_non_200"):
        raise AssertionError("Stable requests failed; inspect summary.json and stable.jsonl")


if __name__ == "__main__":
    main()
