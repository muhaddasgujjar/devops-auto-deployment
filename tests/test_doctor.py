import json
import unittest
from unittest.mock import patch

from scripts import doctor


class DoctorTests(unittest.TestCase):
    def inspect_with_gitops_discovery(self, fail_discovery):
        def kube(*args):
            if args[:2] == ("config", "current-context"):
                return "k3d-release-lab"
            if args[:2] == ("get", "nodes"):
                return json.dumps({"items": [{"metadata": {"name": "node"}, "status": {
                    "conditions": [{"type": key, "status": value} for key, value in
                                   {"Ready": "True", "MemoryPressure": "False", "DiskPressure": "False"}.items()]}}]})
            if args[:2] == ("get", "deployment"):
                return json.dumps({"metadata": {"generation": 1}, "spec": {"replicas": 1},
                                   "status": {"observedGeneration": 1, "availableReplicas": 1}})
            if args[:2] == ("get", "crd"):
                if fail_discovery:
                    raise RuntimeError("discovery unavailable")
                return ""
            raise RuntimeError("endpoint unavailable")

        with patch.object(doctor, "kube", side_effect=kube), \
             patch.object(doctor, "resource", side_effect=RuntimeError("release unavailable")), \
             patch.object(doctor.Path, "read_text", return_value="MemAvailable: 4096 kB\n"):
            return doctor.inspect()

    def test_discovery_failure_retains_other_check_results(self):
        report = self.inspect_with_gitops_discovery(True)
        self.assertTrue(report["checks"]["nodes"]["ok"])
        self.assertTrue(report["checks"]["argo-rollouts"]["ok"])
        self.assertFalse(report["checks"]["stable_service"]["ok"])
        self.assertIn("discovery unavailable", report["checks"]["gitops_sync"]["detail"])
        self.assertFalse(report["ok"])

    def test_missing_gitops_is_not_reported_as_ready(self):
        report = self.inspect_with_gitops_discovery(False)
        self.assertFalse(report["checks"]["gitops_sync"]["ok"])
        self.assertEqual(report["checks"]["gitops_sync"]["detail"]["reason"],
                         "Argo CD Application CRD is absent")


if __name__ == "__main__":
    unittest.main()
