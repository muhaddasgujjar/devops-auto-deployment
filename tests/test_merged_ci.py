import base64
import re
import unittest

from scripts.configure_merged_ci import configuration


class MergedConfigurationTests(unittest.TestCase):
    def test_rejects_source_injection(self):
        for value in ('main', 'a' * 39, 'a' * 40 + "';println('x')"):
            with self.assertRaises(ValueError):
                configuration(value)

    def test_reviewed_pipeline_and_disabled_legacy_jobs(self):
        script = configuration('a' * 40)
        encoded = re.search(r"new String\('([A-Za-z0-9+/=]+)'\.decodeBase64", script).group(1)
        pipeline = base64.b64decode(encoded).decode()
        self.assertIn("TRUSTED_SOURCE_SHA = '" + 'a' * 40 + "'", pipeline)
        self.assertNotIn('__SOURCE_SHA__', pipeline)
        self.assertIn('old.setDisabled(true)', script)
        self.assertIn('old.removeProperty(PipelineTriggersJobProperty)', script)
        self.assertLess(pipeline.index("stage('Tests')"), pipeline.index("stage('Build and scan')"))
