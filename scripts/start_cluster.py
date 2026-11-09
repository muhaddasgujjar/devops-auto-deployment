"""Bound the k3d helper; the caller must independently verify cluster health."""
import json
import subprocess
from pathlib import Path


def start(run=subprocess.run):
    try:
        result = run(["k3d", "cluster", "start", "release-lab", "--wait=false", "--timeout", "60s"],
                     timeout=75, check=False, capture_output=True, text=True)
        stderr = result.stderr if isinstance(result.stderr, str) else ""
        log_wait_failed = (result.returncode != 0 and "error waiting for log line" in stderr
                           and "cluster dns configmap" in stderr
                           and "context deadline exceeded" in stderr)
        return {"helper_timed_out": False, "returncode": result.returncode,
                "post_start_log_wait_failed": log_wait_failed,
                "diagnostic": stderr[-2000:]}
    except subprocess.TimeoutExpired:
        # subprocess.run terminates and waits for the child; no cluster/data deletion.
        return {"helper_timed_out": True, "returncode": None,
                "warning": "k3d helper deadline exceeded; mandatory Kubernetes readiness gate follows"}


def main():
    report = start()
    target = Path("output/cluster-start-helper.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["helper_timed_out"] or report.get("post_start_log_wait_failed") else report["returncode"]


if __name__ == "__main__":
    raise SystemExit(main())
