"""Controlled release workload; intentionally dependency-free, not a production server."""
import json
import os
import signal
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MODES = {"healthy", "error", "latency", "startup", "post-error"}
BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.statuses = Counter({"200": 0, "500": 0})
        self.buckets = Counter()
        self.total_seconds = 0.0

    def observe(self, status, seconds):
        with self.lock:
            self.statuses[str(status)] += 1
            self.total_seconds += seconds
            for bound in BUCKETS:
                if seconds <= bound:
                    self.buckets[bound] += 1

    def render(self, prefix="demo"):
        with self.lock:
            count = sum(self.statuses.values())
            lines = ["# HELP demo_requests_total Application requests excluding probes and metrics.",
                     "# TYPE demo_requests_total counter"]
            lines += [f'demo_requests_total{{status="{s}"}} {n}' for s, n in sorted(self.statuses.items())]
            lines += ["# HELP demo_request_duration_seconds Application response time.",
                      "# TYPE demo_request_duration_seconds histogram"]
            lines += [f'demo_request_duration_seconds_bucket{{le="{b}"}} {self.buckets[b]}' for b in BUCKETS]
            lines += [f'demo_request_duration_seconds_bucket{{le="+Inf"}} {count}',
                      f"demo_request_duration_seconds_sum {self.total_seconds}",
                      f"demo_request_duration_seconds_count {count}"]
            return ("\n".join(lines).replace('demo_', prefix + '_') + "\n").encode()


def create_server(host="127.0.0.1", port=8080, mode="healthy", revision="local", latency=0.8):
    if mode not in MODES:
        raise ValueError(f"Invalid mode: {mode}")
    if not 0 <= latency <= 10:
        raise ValueError("latency must be between 0 and 10 seconds")
    metrics = Metrics()
    serving_metrics = Metrics()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/metrics":
                self.respond(200, metrics.render() + serving_metrics.render('demo_serving'), "text/plain; version=0.0.4")
                return
            if path in {"/healthz", "/readyz"}:
                status = 503 if path == "/readyz" and mode == "startup" else 200
                self.respond(status, json.dumps({"status": status}).encode())
                return
            if path != "/":
                self.respond(404, b'{"error":"not found"}')
                return
            start = time.monotonic()
            if mode == "latency":
                time.sleep(latency)
            preview = self.headers.get('X-Release-Preview') == 'true'
            # Controlled fixture: preview passes, ordinary serving traffic fails.
            status = 500 if mode == "error" or (mode == 'post-error' and not preview) else 200
            body = json.dumps({"service": "release-demo", "revision": revision, "mode": mode}).encode()
            metrics.observe(status, time.monotonic() - start)
            if not preview:
                serving_metrics.observe(status, time.monotonic() - start)
            self.respond(status, body)

        def respond(self, status, body, content_type="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, fmt, *args):
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main():
    server = create_server(os.getenv("HOST", "0.0.0.0"), int(os.getenv("PORT", "8080")),
                           os.getenv("DEMO_MODE", "healthy"), os.getenv("APP_REVISION", "local"),
                           float(os.getenv("DEMO_LATENCY_SECONDS", "0.8")))

    def stop(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"release-demo listening on {server.server_address}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
