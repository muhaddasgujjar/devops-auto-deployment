import importlib.util
import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

spec = importlib.util.spec_from_file_location(
    "demo", Path(__file__).resolve().parents[1] / "demo/app/server.py"
)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class DemoTests(unittest.TestCase):
    def start(self, mode="healthy", **kwargs):
        server = demo.DemoServer(("127.0.0.1", 0), mode=mode, revision="test-revision", **kwargs)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()

        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.addCleanup(cleanup)
        self.base = f"http://127.0.0.1:{server.server_port}"
        return server

    def get(self, path):
        try:
            response = urlopen(self.base + path, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.read().decode()

    def test_healthy_release_identity_and_probes(self):
        self.start()
        for path in ("/healthz", "/readyz", "/api/work", "/version"):
            self.assertEqual(self.get(path)[0], 200)
        self.assertEqual(json.loads(self.get("/version")[1])["revision"], "test-revision")

    def test_application_failure_does_not_fail_process_probe(self):
        self.start("errors")
        self.assertEqual(self.get("/healthz")[0], 200)
        self.assertEqual(self.get("/readyz")[0], 200)
        self.assertEqual(self.get("/api/work")[0], 500)
        self.assertIn('status="500"} 1', self.get("/metrics")[1])

    def test_unready_release_is_alive_but_not_ready(self):
        self.start("unready")
        self.assertEqual(self.get("/healthz")[0], 200)
        self.assertEqual(self.get("/readyz")[0], 503)

    def test_latency_release_exposes_duration(self):
        self.start("latency", latency=0.15)
        start = time.perf_counter()
        self.assertEqual(self.get("/api/work")[0], 200)
        self.assertGreaterEqual(time.perf_counter() - start, 0.14)
        metrics = self.get("/metrics")[1]
        self.assertIn('le="0.1"} 0', metrics)
        self.assertIn('le="0.5"} 1', metrics)
        self.assertIn('le="+Inf"} 1', metrics)

    def test_concurrent_counts_and_probe_exclusion(self):
        self.start()
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(lambda _: self.get("/api/work")[0], range(20)))
        self.assertEqual(statuses, [200] * 20)
        for path in ("/healthz", "/readyz", "/metrics", "/missing"):
            self.get(path)
        metrics = self.get("/metrics")[1]
        self.assertIn('status="200"} 20', metrics)
        self.assertIn('le="+Inf"} 20', metrics)
        self.assertTrue(metrics.endswith("\n"))

    def test_unknown_route_has_no_work_sample(self):
        self.start()
        self.assertEqual(self.get("/missing")[0], 404)
        self.assertIn('status="200"} 0', self.get("/metrics")[1])

    def test_draining_rejects_new_work(self):
        server = self.start()
        server.draining = True
        self.assertEqual(self.get("/readyz")[0], 503)
        self.assertEqual(self.get("/api/work")[0], 503)
        self.assertEqual(self.get("/healthz")[0], 200)

    def test_invalid_configuration_rejected(self):
        for kwargs in ({"mode": "unknown"}, {"revision": 'bad"label'},
                       {"latency": -1}, {"latency": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                demo.DemoServer(("127.0.0.1", 0), **kwargs)


if __name__ == "__main__":
    unittest.main()
