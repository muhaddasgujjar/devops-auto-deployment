import tempfile
import unittest
from pathlib import Path

from scripts.render_release import render

IMAGE = "localhost:5001/release-demo@sha256:" + "a" * 64
COMMIT = "b" * 40


class RenderTests(unittest.TestCase):
    def test_release_preserves_controller_expressions_and_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            names = render(IMAGE, COMMIT, directory)
            self.assertEqual(len(names), 4)
            rollout = (Path(directory) / "rollout.yaml").read_text()
            self.assertIn(IMAGE, rollout)
            self.assertIn(COMMIT, rollout)
            self.assertNotIn("__IMAGE__", rollout)
            self.assertIn("{{args.revision}}", (Path(directory) / "analysis.yaml").read_text())
            before = {p.name: p.read_bytes() for p in Path(directory).iterdir()}
            render(IMAGE, COMMIT, directory)
            self.assertEqual(before, {p.name: p.read_bytes() for p in Path(directory).iterdir()})

    def test_rejects_mutable_tags_and_yaml_injection_before_writing(self):
        for image in ("demo:latest", "demo@sha256:123", IMAGE + "\nkind: Secret", IMAGE.upper()):
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "new"
                with self.assertRaises(ValueError):
                    render(image, COMMIT, target)
                self.assertFalse(target.exists())

    def test_rejects_invalid_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                render(IMAGE, 'abc"\n', directory)

    def test_separate_rolling_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            render(IMAGE, COMMIT, directory, baseline=True)
            manifest = (Path(directory) / "deployment.yaml").read_text()
            self.assertIn("demo-baseline", manifest)
            self.assertIn("type: RollingUpdate", manifest)
            self.assertIn(IMAGE, manifest)
            self.assertNotIn("kind: Rollout\n", manifest)
