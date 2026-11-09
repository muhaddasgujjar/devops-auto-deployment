"""Linux Docker smoke checks. Deletes only the containers it creates."""
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
report_path = root / "docs/evidence/container-validation.json"
report_path.unlink(missing_ok=True)  # A failed rerun must not leave an earlier success receipt.
image = json.loads((root / "versions.json").read_text())["sample_image"]


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True, timeout=60).strip()


def request(base, path):
    try:
        response = urlopen(base + path, timeout=3)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.read().decode()


results = []
for mode, work_status, ready_status in (("healthy", 200, 200), ("errors", 500, 200),
                                        ("unready", 200, 503)):
    container = docker("run", "--detach", "--publish", "127.0.0.1::8080",
                       "--read-only", "--cap-drop", "ALL", "--security-opt",
                       "no-new-privileges", "--memory", "96m", "--cpus", "0.25",
                       "--env", f"DEMO_MODE={mode}", "--env", f"APP_REVISION=container-{mode}", image)
    try:
        port = docker("port", container, "8080/tcp").split(":")[-1]
        base = "http://127.0.0.1:" + port
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if request(base, "/healthz")[0] == 200:
                    break
            except (URLError, TimeoutError, ConnectionError):
                pass
            time.sleep(0.2)
        else:
            state = docker("inspect", container, "--format", "{{.State.Status}}")
            logs = docker("logs", "--tail", "10", container)
            raise RuntimeError(f"Container startup timed out: mode={mode}, state={state}, logs={logs}")
        assert request(base, "/readyz")[0] == ready_status
        assert request(base, "/api/work")[0] == work_status
        assert f'container-{mode}' in request(base, "/metrics")[1]
        assert docker("inspect", container, "--format", "{{.Config.User}}") == "10001:10001"
        docker("stop", "--time", "5", container)
        exit_code = int(docker("inspect", container, "--format", "{{.State.ExitCode}}"))
        assert exit_code == 0, f"SIGTERM shutdown failed: {exit_code}"
        results.append({"mode": mode, "expected_work_status": work_status,
                        "expected_readiness": ready_status, "non_root": True,
                        "read_only_root": True, "sigterm_exit_code": exit_code, "passed": True})
    finally:
        docker("rm", "--force", container)

report = {"recorded_at_utc": datetime.now(timezone.utc).isoformat(),
          "image": image, "image_id": docker("image", "inspect", image, "--format", "{{.Id}}"),
          "docker_server": docker("version", "--format", "{{.Server.Version}}"),
          "results": results, "passed": True,
          "scope": "Real isolated local containers; no Kubernetes recovery or image scan assertion"}
report_path.write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
