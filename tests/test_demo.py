import concurrent.futures
import json
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen, Request

from demo.app import create_server
from scripts.load import run


@contextmanager
def serving(**kwargs):
    server = create_server(port=0, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(url):
    try:
        with urlopen(url, timeout=3) as response:
            return response.status, response.read().decode()
    except HTTPError as exc:
        with exc:
            return exc.code, exc.read().decode()


class DemoTests(unittest.TestCase):
    def test_post_promotion_fault_passes_preview_and_excludes_preview_from_serving_metrics(self):
        with serving(mode='post-error', revision='post-test') as base:
            self.assertEqual(request(Request(base + '/', headers={'X-Release-Preview': 'true'}))[0], 200)
            self.assertIn('demo_serving_request_duration_seconds_count 0\n', request(base + '/metrics')[1])
            status, body = request(base + '/')
            self.assertEqual(status, 500)
            self.assertEqual(json.loads(body)['revision'], 'post-test')
            self.assertEqual(request(base + '/readyz')[0], 200)
            self.assertIn('demo_serving_requests_total{status="500"} 1\n', request(base + '/metrics')[1])

    def test_healthy_response_and_revision(self):
        with serving(revision="abc123") as base:
            status, body = request(base + "/")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["revision"], "abc123")

    def test_error_is_detectable_despite_healthy_probes(self):
        with serving(mode="error") as base:
            self.assertEqual(request(base + "/healthz")[0], 200)
            self.assertEqual(request(base + "/readyz")[0], 200)
            self.assertEqual(request(base + "/")[0], 500)
            metrics = request(base + "/metrics")[1]
            self.assertIn('demo_requests_total{status="500"} 1\n', metrics)
            self.assertIn('demo_requests_total{status="200"} 0\n', metrics)

    def test_startup_fault_fails_readiness_only(self):
        with serving(mode="startup") as base:
            self.assertEqual(request(base + "/readyz")[0], 503)
            self.assertEqual(request(base + "/healthz")[0], 200)

    def test_latency_fault_and_histogram(self):
        with serving(mode="latency", latency=0.12) as base:
            start = time.monotonic()
            self.assertEqual(request(base + "/")[0], 200)
            self.assertGreaterEqual(time.monotonic() - start, 0.12)
            metrics = request(base + "/metrics")[1]
            self.assertIn('demo_request_duration_seconds_bucket{le="0.1"} 0\n', metrics)
            self.assertIn('demo_request_duration_seconds_bucket{le="+Inf"} 1\n', metrics)

    def test_metrics_and_probes_do_not_fabricate_traffic(self):
        with serving() as base:
            for path in ("/healthz", "/readyz", "/metrics", "/unknown"):
                request(base + path)
            self.assertIn("demo_request_duration_seconds_count 0\n", request(base + "/metrics")[1])

    def test_parallel_request_accounting(self):
        with serving() as base:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                responses = list(executor.map(lambda _: request(base + "/")[0], range(32)))
            self.assertEqual(responses, [200] * 32)
            self.assertIn('demo_requests_total{status="200"} 32\n', request(base + "/metrics")[1])

    def test_external_evidence_records_http_errors(self):
        with tempfile.TemporaryDirectory() as directory, serving(mode="error") as base:
            target = Path(directory) / "evidence.jsonl"
            run(base + "/", 0.2, 2, target)
            rows = [json.loads(line) for line in target.read_text().splitlines()]
            self.assertGreater(len(rows), 0)
            self.assertTrue(all(row["status"] == 500 for row in rows))
            self.assertTrue(all(row["duration_seconds"] >= 0 for row in rows))
            with self.assertRaises(FileExistsError):
                run(base + "/", 0.1, 1, target)

    def test_invalid_fault_configuration(self):
        for kwargs in ({"mode": "unknown"}, {"latency": -1}, {"latency": float("nan")}):
            with self.assertRaises(ValueError):
                create_server(port=0, **kwargs)


if __name__ == "__main__":
    unittest.main()
