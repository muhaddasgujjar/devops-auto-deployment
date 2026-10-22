"""Read-only checks of the named lab, serving release, and revision telemetry."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from scripts.live_trial import kube, resource
from scripts.render_release import ROOT


def inspect():
    os.environ["KUBECONFIG"] = str(ROOT / "output/lab.kubeconfig")
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "checks": {}, "attention": []}

    def check(name, operation):
        try:
            passed, detail = operation()
            report["checks"][name] = {"ok": bool(passed), "detail": detail}
        except Exception as exc:
            report["checks"][name] = {"ok": False, "detail": str(exc)}

    context = kube("config", "current-context").strip()
    if context != "k3d-release-lab":
        raise ValueError(f"Expected k3d-release-lab context; received {context}")
    report["context"] = context

    def nodes():
        data = json.loads(kube("get", "nodes", "-o", "json"))["items"]
        states = [{"name": node["metadata"]["name"], "conditions": {c["type"]: c["status"] for c in node["status"]["conditions"]}} for node in data]
        return bool(states) and all(n["conditions"].get("Ready") == "True" and
                                   n["conditions"].get("MemoryPressure") == "False" and
                                   n["conditions"].get("DiskPressure") == "False" for n in states), states
    check("nodes", nodes)
    for namespace, name in (("argo-rollouts", "argo-rollouts"), ("monitoring", "prometheus")):
        def deployment(namespace=namespace, name=name):
            obj = json.loads(kube("get", "deployment", name, "-n", namespace, "-o", "json"))
            desired = obj["spec"].get("replicas", 1)
            status = obj.get("status", {})
            return desired > 0 and status.get("availableReplicas", 0) >= desired and status.get("observedGeneration") == obj["metadata"]["generation"], status
        check(name, deployment)

    def storage():
        obj = json.loads(kube('get', 'deployment', 'prometheus', '-n', 'monitoring', '-o', 'json'))
        volumes = obj['spec']['template']['spec'].get('volumes', [])
        claim_name = next((v.get('persistentVolumeClaim', {}).get('claimName')
                           for v in volumes if v['name'] == 'data'), None)
        if claim_name != 'prometheus-data':
            return False, {'error': 'Prometheus is not using the expected persistent claim'}
        claim = json.loads(kube('get', 'pvc', claim_name, '-n', 'monitoring', '-o', 'json'))
        volume = json.loads(kube('get', 'pv', claim['spec']['volumeName'], '-o', 'json'))
        detail = {'claim': claim_name, 'phase': claim.get('status', {}).get('phase'),
                  'volume': volume['metadata']['name'], 'reclaim_policy': volume['spec']['persistentVolumeReclaimPolicy']}
        return detail['phase'] == 'Bound' and detail['reclaim_policy'] == 'Retain', detail
    check('prometheus_storage', storage)
    recovery_path = Path('/var/lib/release-lab/recovery/status.json')
    if recovery_path.exists():
        def recovery():
            state = json.loads(recovery_path.read_text())
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(state['updated_at'])).total_seconds()
            return state.get('phase') != 'recovery_failed' and age <= 60, {
                'phase': state.get('phase'), 'age_seconds': round(age, 1),
                'deployment_commit': state.get('deployment_commit'), 'error': state.get('error')}
        check('release_recovery', recovery)

    def release():
        obj = resource("rollout", "release-demo")
        stable = resource("service", "demo-stable")["spec"]["selector"].get("rollouts-pod-template-hash")
        expected = obj["spec"].get("replicas", 1)
        data = json.loads(kube("get", "--raw", "/api/v1/namespaces/demo-dev/services/demo-stable:80/proxy/"))
        report["release"] = {"phase": obj["status"].get("phase"), "candidate_hash": obj["status"].get("currentPodHash"),
                             "serving_hash": stable, "expected_pods": expected, "response": data,
                             "desired_image": obj["spec"]["template"]["spec"]["containers"][0]["image"]}
        if obj["status"].get("phase") != "Healthy":
            report["attention"].append("The candidate is not Healthy; inspect its analysis separately from stable-service health.")
        return bool(stable) and data.get("mode") == "healthy", report["release"]
    check("stable_service", release)

    def telemetry():
        serving = report.get("release", {})
        query = 'up{job="demo-pods",namespace="demo-dev",revision="' + serving.get("serving_hash", "") + '"}'
        endpoint = "/api/v1/namespaces/monitoring/services/prometheus:9090/proxy/api/v1/query?"
        data = json.loads(kube("get", "--raw", endpoint + urlencode({"query": query})))
        targets = data.get("data", {}).get("result", [])
        ages = json.loads(kube("get", "--raw", endpoint + urlencode({"query": "time() - timestamp(" + query + ")"})))
        samples = ages.get("data", {}).get("result", [])
        passed = (data.get("status") == ages.get("status") == "success"
                  and len(targets) == len(samples) == serving.get("expected_pods")
                  and all(float(t["value"][1]) == 1 for t in targets)
                  and all(0 <= float(t["value"][1]) <= 15 for t in samples))
        return passed, {"targets": targets, "sample_age_seconds": samples}
    check("serving_revision_telemetry", telemetry)
    if kube('get', 'crd', 'applications.argoproj.io', '--ignore-not-found', '-o', 'name').strip():
        raw = kube('get', 'application', 'release-demo-dev', '-n', 'argocd', '--ignore-not-found', '-o', 'json')
        if raw.strip():
            app = json.loads(raw)
            def gitops():
                sync = app.get('status', {}).get('sync', {})
                detail = {'sync': sync, 'health': app.get('status', {}).get('health'),
                          'conditions': app.get('status', {}).get('conditions', [])}
                return sync.get('status') == 'Synced' and bool(sync.get('revision')), detail
            check('gitops_sync', gitops)
    info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    report["linux_memory_available_mib"] = round(int(info["MemAvailable"].split()[0]) / 1024, 1)
    report["ok"] = all(c["ok"] for c in report["checks"].values())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = inspect()
    except Exception as exc:
        report = {"ok": False, "error": str(exc)}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
