"""Supervise loopback-only access to the existing lab interfaces."""
import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

from scripts.render_release import ROOT

STATE = ROOT / "output/review.json"
URLS = {"app": "http://localhost:8081/", "prometheus": "http://localhost:9090/", "rollouts": "http://localhost:3100/rollouts/"}


def identity(pid):
    try:
        proc = Path(f"/proc/{pid}")
        if b"scripts.review" not in (proc / "cmdline").read_bytes():
            return None
        return (proc / "stat").read_text().split(") ", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def status():
    try:
        record = json.loads(STATE.read_text())
        record["running"] = bool(record["start_ticks"]) and identity(record["pid"]) == record["start_ticks"]
        return record
    except (OSError, ValueError, KeyError):
        return {"running": False}


def serve():
    import fcntl
    STATE.parent.mkdir(parents=True, exist_ok=True)
    lock = (STATE.parent / "review.lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Review interfaces are already supervised")
    os.environ["KUBECONFIG"] = str(ROOT / "output/lab.kubeconfig")
    context = subprocess.check_output(["kubectl", "config", "current-context"], text=True).strip()
    if context != "k3d-release-lab":
        raise SystemExit("Expected k3d-release-lab context")
    commands = {
        "app": ["kubectl", "port-forward", "--address=127.0.0.1", "-n", "demo-dev", "service/demo-stable", "8081:80"],
        "prometheus": ["kubectl", "port-forward", "--address=127.0.0.1", "-n", "monitoring", "service/prometheus", "9090:9090"],
        "rollouts": ["kubectl", "argo", "rollouts", "dashboard", "--address", "127.0.0.1", "--port", "3100", "-n", "demo-dev"],
    }
    children, logs = {}, {}
    running = True
    serving_hash = None

    def stop_signal(*_):
        nonlocal running
        running = False

    def stop_child(name):
        child = children.get(name)
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    try:
        while running:
            try:
                latest = subprocess.check_output(["kubectl", "get", "service", "demo-stable", "-n", "demo-dev", "-o", "jsonpath={.spec.selector.rollouts-pod-template-hash}", "--request-timeout=5s"], text=True, stderr=subprocess.DEVNULL, timeout=10).strip()
                if latest and latest != serving_hash:
                    stop_child("app")
                    serving_hash = latest
            except (subprocess.SubprocessError, OSError):
                pass
            for name, command in commands.items():
                if name not in children or children[name].poll() is not None:
                    if name not in logs:
                        logs[name] = (STATE.parent / f"review-{name}.log").open("a")
                    children[name] = subprocess.Popen(command, cwd=ROOT, stdout=logs[name], stderr=subprocess.STDOUT)
            record = {"pid": os.getpid(), "start_ticks": identity(os.getpid()), "urls": URLS,
                      "serving_hash": serving_hash, "children": {name: proc.pid for name, proc in children.items()}}
            temp = STATE.with_suffix(".tmp")
            temp.write_text(json.dumps(record, indent=2))
            temp.replace(STATE)
            for _ in range(5):
                if not running:
                    break
                time.sleep(1)
    finally:
        for name in children:
            stop_child(name)
        for log in logs.values():
            log.close()
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true")
    group.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    if args.status or args.stop:
        record = status()
        if args.stop and record["running"]:
            os.kill(record["pid"], signal.SIGTERM)
            for _ in range(20):
                if not status()["running"]:
                    break
                time.sleep(0.5)
            if status()["running"]:
                raise SystemExit("Review supervisor is still stopping; inspect its logs")
        print(json.dumps(record, indent=2))
    else:
        serve()


if __name__ == "__main__":
    main()
