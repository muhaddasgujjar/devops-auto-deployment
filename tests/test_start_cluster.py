import subprocess
import unittest
from unittest.mock import Mock

from scripts.start_cluster import start


class StartClusterTests(unittest.TestCase):
    def test_success(self):
        self.assertEqual(start(Mock(return_value=Mock(returncode=0)))["returncode"], 0)

    def test_real_failure_is_not_suppressed(self):
        self.assertEqual(start(Mock(return_value=Mock(returncode=2)))["returncode"], 2)

    def test_helper_timeout_is_recorded_for_independent_health_gate(self):
        report = start(Mock(side_effect=subprocess.TimeoutExpired("k3d", 60)))
        self.assertTrue(report["helper_timed_out"])
        self.assertIsNone(report["returncode"])

    def test_specific_post_start_log_timeout_is_recorded(self):
        result = Mock(returncode=1, stderr='error waiting for log line `cluster dns configmap`: context deadline exceeded')
        self.assertTrue(start(Mock(return_value=result))["post_start_log_wait_failed"])
