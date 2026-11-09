import contextlib
import io
import unittest
from unittest.mock import patch

from scripts import integration_runtime


class RuntimeProfileTests(unittest.TestCase):
    def test_lean_starts_git_without_inspecting_or_starting_ci(self):
        with patch("sys.argv", ["runtime", "start", "--profile", "lean"]), \
             patch.object(integration_runtime.Path, "exists", return_value=True), \
             patch.object(integration_runtime.subprocess, "run") as run, \
             contextlib.redirect_stdout(io.StringIO()):
            integration_runtime.main()
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0][0], "bash")

    def test_lean_without_config_does_not_provision_or_start_ci(self):
        with patch("sys.argv", ["runtime", "start", "--profile", "lean"]), \
             patch.object(integration_runtime.Path, "exists", return_value=False), \
             patch.object(integration_runtime.subprocess, "run") as run, \
             contextlib.redirect_stdout(io.StringIO()):
            integration_runtime.main()
        run.assert_not_called()
