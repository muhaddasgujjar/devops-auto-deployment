import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.gitops_trial import TelemetryFixture, artifact_mode, validate_availability, validate_fault_evidence
from scripts.gitops_fault_matrix import verify_shared_failure


class GitOpsTrialTests(unittest.TestCase):
    def test_environment_faults_build_healthy_artifacts(self):
        for scenario in ('no-traffic', 'telemetry-outage', 'shared-telemetry-outage'):
            self.assertEqual(artifact_mode(scenario), 'healthy')
        self.assertEqual(artifact_mode('latency'), 'latency')

    def test_independent_availability_rejects_empty_and_unrelated_errors(self):
        for rows in ([], [{'status': 0}], [{'status': 500}]):
            with self.assertRaises(AssertionError):
                validate_availability('latency', rows, 'new')
        validate_availability('no-traffic', [{'status': 200}], 'new')

    def test_serving_fault_needs_attributed_errors_and_observed_restoration(self):
        bad = {'status': 500, 'response': {'revision': 'new'}}
        good = {'status': 200}
        validate_availability('post-error', [good, bad, good], 'new')
        for rows in ([good], [good, bad], [dict(bad, status=0), good],
                     [{'status': 500, 'response': {'revision': 'old'}}, good]):
            with self.assertRaises(AssertionError):
                validate_availability('post-error', rows, 'new')

    def test_telemetry_cleanup_remains_retryable_after_scale_failure(self):
        fixture = TelemetryFixture(None)
        fixture.replicas = 1
        with patch('scripts.gitops_trial.kube', side_effect=RuntimeError('API unavailable')):
            with self.assertRaises(RuntimeError):
                fixture.restore()
        self.assertEqual(fixture.replicas, 1)
        with patch('scripts.gitops_trial.kube') as scale:
            fixture.restore()
            fixture.restore()
            scale.assert_called_once_with('scale', 'deployment/prometheus', '-n', 'monitoring', '--replicas=1')

    def test_fault_verdict_requires_the_intended_failure_evidence(self):
        for scenario, metric in (
            ('latency', {'name': 'candidate-p95-latency', 'phase': 'Failed'}),
            ('no-traffic', {'phase': 'Inconclusive', 'measurements': [{'value': '[]'}]}),
            ('telemetry-outage', {'phase': 'Error', 'measurements': [{'phase': 'Error'}]}),
        ):
            validate_fault_evidence(scenario, [{'status': {'metricResults': [metric]}}], {})
            with self.assertRaises(AssertionError):
                validate_fault_evidence(scenario, [], {})
        validate_fault_evidence('startup', [], {'status': {'conditions': [{'reason': 'ProgressDeadlineExceeded'}]}})
        validate_fault_evidence('startup', [], {'kind': 'List', 'items': [{'metadata': {'name': 'release-demo'},
            'status': {'abort': True, 'conditions': [{'type': 'Progressing', 'status': 'False',
                'reason': 'RolloutAborted', 'message': 'ReplicaSet "candidate" has timed out progressing.'}]}}]})
        with self.assertRaises(AssertionError):
            validate_fault_evidence('startup', [], {'status': {'phase': 'Healthy'}})
        with self.assertRaises(AssertionError):
            validate_fault_evidence('startup', [], {'status': {'abort': True, 'conditions': [{
                'type': 'Progressing', 'status': 'False', 'reason': 'RolloutAborted', 'message': 'Operator abort'}]}})

    def test_shared_failure_requires_full_deadline_and_unavailable_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'telemetry-fixture.json').write_text('{"replicas":1}')
            (folder / 'stable.jsonl').write_text('{"status":200}\n')
            (folder / 'analysis-observed.json').write_text(json.dumps({'items': [{
                'metadata': {'labels': {'rollouts-pod-template-hash': 'candidate'}},
                'status': {'metricResults': [{'phase': 'Error', 'measurements': [{'phase': 'Error'}]}]}
            }]}))
            failed = {'phase': 'recovery_failed', 'observation': {'fresh_telemetry': False},
                      'error': 'Recovery verification deadline exceeded',
                      'recovery_started_at': '2026-10-23T00:00:00+00:00',
                      'finished_at': '2026-10-23T00:10:01+00:00'}
            trial = {'verdict': 'trial-failed', 'error': 'Recovery failed',
                     'release_control': failed, 'tested_candidate_hash': 'candidate'}
            self.assertEqual(verify_shared_failure(folder, trial), failed)
            for changed in (dict(failed, observation={'fresh_telemetry': True}),
                            dict(failed, finished_at='2026-10-23T00:00:01+00:00')):
                with self.assertRaises(AssertionError):
                    verify_shared_failure(folder, dict(trial, release_control=changed))


if __name__ == '__main__':
    unittest.main()
