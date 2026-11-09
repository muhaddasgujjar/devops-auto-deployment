"""Small, trusted-lab HTTP workload for release and recovery experiments."""

import json
import math
import os
import re
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class DemoServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(self, address, *, mode="healthy", revision="dev", latency=0.25):
        if mode not in {"healthy", "errors", "unready", "latency"}:
            raise ValueError("Unsupported DEMO_MODE")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", revision):
            raise ValueError("APP_REVISION must be 1-80 letters, digits, _, . or -")
        if not math.isfinite(latency) or not 0 <= latency <= 5:
            raise ValueError("DEMO_LATENCY_SECONDS must be between 0 and 5")
        self.mode = mode
        self.revision = revision
        self.latency = latency
        self.draining = False
        self.lock = threading.Lock()
        self.requests = {200: 0, 500: 0}
        self.buckets = {bound: 0 for bound in (0.01, 0.1, 0.5, 1.0, 5.0)}
        self.duration_sum = 0.0
        super().__init__(address, DemoHandler)

    def metrics(self):
        labels = f'app="release-demo",revision="{self.revision}"'
        with self.lock:
            counts = self.requests.copy()
            buckets = self.buckets.copy()
            duration_sum = self.duration_sum
        total = sum(counts.values())
        lines = [
            "# HELP demo_work_requests_total Completed work requests by revision and status.",
            "# TYPE demo_work_requests_total counter",
        ]
        for status, count in counts.items():
            lines.append(f'demo_work_requests_total{{{labels},status="{status}"}} {count}')
        lines += [
            "# HELP demo_work_duration_seconds Work handler duration, excluding network transfer.",
            "# TYPE demo_work_duration_seconds histogram",
        ]
        for bound, count in buckets.items():
            lines.append(f'demo_work_duration_seconds_bucket{{{labels},le="{bound}"}} {count}')
        lines += [
            f'demo_work_duration_seconds_bucket{{{labels},le="+Inf"}} {total}',
            f"demo_work_duration_seconds_sum{{{labels}}} {duration_sum}",
            f"demo_work_duration_seconds_count{{{labels}}} {total}",
        ]
        return "\n".join(lines) + "\n"


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "ReleaseDemo/0.1"

    def log_message(self, *_):
        pass  # Avoid logging arbitrary request text in the controlled workload.

    def reply(self, status, body, content_type="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = urlsplit(self.path).path
        service = self.server
        if path == "/healthz":
            self.reply(200, {"alive": True})
        elif path == "/readyz":
            ready = service.mode != "unready" and not service.draining
            self.reply(200 if ready else 503, {"ready": ready})
        elif path in {"/", "/version"}:
            self.reply(200, {"app": "release-demo", "revision": service.revision,
                             "mode": service.mode})
        elif path == "/metrics":
            self.reply(200, service.metrics(), "text/plain; version=0.0.4; charset=utf-8")
        elif path == "/api/work":
            if service.draining:
                self.reply(503, {"error": "draining"})
                return
            start = time.perf_counter()
            if service.mode == "latency":
                time.sleep(service.latency)
            status = 500 if service.mode == "errors" else 200
            duration = time.perf_counter() - start
            with service.lock:
                service.requests[status] += 1
                service.duration_sum += duration
                for bound in service.buckets:
                    if duration <= bound:
                        service.buckets[bound] += 1
            self.reply(status, {"revision": service.revision, "ok": status == 200})
        else:
            self.reply(404, {"error": "not found"})


def main():
    service = DemoServer(
        (os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8080"))),
        mode=os.environ.get("DEMO_MODE", "healthy"),
        revision=os.environ.get("APP_REVISION", "dev"),
        latency=float(os.environ.get("DEMO_LATENCY_SECONDS", "0.25")),
    )

    def stop(*_):
        if not service.draining:
            service.draining = True
            threading.Thread(target=service.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(json.dumps({"listening": service.server_address, "mode": service.mode,
                      "revision": service.revision}), flush=True)
    try:
        service.serve_forever(poll_interval=0.1)
    finally:
        service.server_close()


if __name__ == "__main__":
    main()
