import unittest

from scripts.wait_lab import wait_for_health


class WaitLabTests(unittest.TestCase):
    def run_sequence(self, sequence, timeout=5):
        elapsed = [0]
        samples = iter(sequence)
        def inspect():
            item = next(samples, False)
            if isinstance(item, Exception):
                raise item
            return {"checks": {"nodes": {"ok": item}}}
        def sleep(seconds):
            elapsed[0] += seconds
        return wait_for_health(inspect, ["nodes"], timeout=timeout,
                               interval=1, clock=lambda: elapsed[0], sleep=sleep)

    def test_transient_success_does_not_pass_and_failure_resets_streak(self):
        result = self.run_sequence([True, False, True, True])
        self.assertTrue(result["ready"])
        self.assertEqual(result["attempts"], 4)

    def test_api_exception_is_retried(self):
        result = self.run_sequence([RuntimeError("API resuming"), True, True])
        self.assertTrue(result["ready"])
        self.assertEqual(result["attempts"], 3)

    def test_unhealthy_lab_times_out(self):
        result = self.run_sequence([False] * 10, timeout=3)
        self.assertFalse(result["ready"])
        self.assertEqual(result["attempts"], 3)
