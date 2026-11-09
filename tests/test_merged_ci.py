import base64
import re
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from scripts.configure_merged_ci import configuration
from scripts.render_release import ROOT
from scripts.gitops_trial import Jenkins, queued_build_number


class MergedConfigurationTests(unittest.TestCase):
    def test_jenkins_startup_connection_reset_is_retried(self):
        client = Jenkins.__new__(Jenkins)
        client.json = Mock(side_effect=[ConnectionResetError('starting'), {'crumbRequestField': 'field', 'crumb': 'value'}])
        with patch('scripts.gitops_trial.time.sleep'):
            client.wait_ready(timeout=1)
        self.assertEqual(client.json.call_count, 2)

    def test_jenkins_authentication_failure_is_not_hidden_as_startup(self):
        client = Jenkins.__new__(Jenkins)
        client.json = Mock(side_effect=HTTPError('http://127.0.0.1/', 401, 'Unauthorized', None, None))
        with self.assertRaises(HTTPError):
            client.wait_ready(timeout=1)

    def test_pending_jenkins_queue_can_have_null_executable(self):
        self.assertIsNone(queued_build_number({'executable': None}))
        self.assertIsNone(queued_build_number({}))
        self.assertEqual(queued_build_number({'executable': {'number': 42}}), 42)

    def test_rejects_source_injection(self):
        for value in ('main', 'a' * 39, 'a' * 40 + "';println('x')"):
            with self.assertRaises(ValueError):
                configuration(value)

    def test_reviewed_pipeline_and_disabled_legacy_jobs(self):
        script = configuration('a' * 40, (ROOT / 'ci/Jenkinsfile.acceptance').read_text())
        encoded = re.search(r"new String\('([A-Za-z0-9+/=]+)'\.decodeBase64", script).group(1)
        pipeline = base64.b64decode(encoded).decode()
        self.assertIn("TRUSTED_SOURCE_SHA = '" + 'a' * 40 + "'", pipeline)
        self.assertNotIn('__SOURCE_SHA__', pipeline)
        self.assertIn('old.setDisabled(true)', script)
        self.assertIn('old.removeProperty(PipelineTriggersJobProperty)', script)
        self.assertLess(pipeline.index("stage('Tests')"), pipeline.index("stage('Build and scan')"))
