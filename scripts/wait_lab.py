"""Wait for sustained lab readiness, allowing bounded WSL resume transients."""
import argparse
import json
import time
from pathlib import Path

from scripts.doctor import inspect


def wait_for_health(inspect_fn, required, *, timeout=180, stable_samples=2,
                    interval=3, clock=time.monotonic, sleep=time.sleep):
    deadline = clock() + timeout
    streak = 0
    attempts = 0
    last = {}
    while clock() < deadline:
        attempts += 1
        try:
            last = inspect_fn()
        except Exception as error:
            last = {"error": str(error), "checks": {}}
        passed = all(last.get("checks", {}).get(name, {}).get("ok") is True for name in required)
        streak = streak + 1 if passed else 0
        if streak >= stable_samples:
            return {"ready": True, "attempts": attempts, "stable_samples": streak,
                    "required_checks": list(required), "health": last}
        sleep(min(interval, max(0, deadline - clock())))
    return {"ready": False, "attempts": attempts, "stable_samples": streak,
            "required_checks": list(required), "health": last}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["controllers", "release"], default="controllers")
    parser.add_argument("--timeout", type=int,
                        help="Polling seconds (controllers: 180; release: 420 for old-series expiry)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    timeout = args.timeout if args.timeout is not None else (420 if args.stage == "release" else 180)
    if timeout <= 0:
        parser.error("timeout must be positive")
    required = ["nodes", "argo-rollouts", "prometheus"]
    if args.stage == "release":
        required += ["stable_service", "serving_revision_telemetry", "gitops_sync"]
    report = wait_for_health(inspect, required, timeout=timeout)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("ready", "attempts", "required_checks")}))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
