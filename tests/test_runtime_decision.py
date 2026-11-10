import copy
import unittest

from scripts.runtime_decision import decision


class RuntimeDecisionTests(unittest.TestCase):
    def setUp(self):
        self.rollout = {'metadata': {'generation': 4},
                        'spec': {'template': {'spec': {'containers': [{'env': [{'name': 'APP_REVISION', 'value': 'wanted'}]}]}}},
                        'status': {'observedGeneration': '4', 'currentPodHash': 'new', 'abort': True}}
        self.app = {'status': {'sync': {'status': 'Synced', 'revision': 'git-commit'}}}

    def run_case(self, scenario, phase, *, hash='new', stable='old', app=None, rollout=None):
        runs = [{'metadata': {'labels': {'rollouts-pod-template-hash': hash}}, 'status': {'phase': phase}}]
        return decision(scenario, 'wanted', 'git-commit', 'old', rollout or self.rollout,
                        app or self.app, runs, stable)

    def test_wrong_analysis_revision_is_not_a_rejection(self):
        self.assertIsNone(self.run_case('error', 'Failed', hash='old'))

    def test_wrong_git_commit_is_not_accepted(self):
        app = copy.deepcopy(self.app); app['status']['sync']['revision'] = 'other'
        self.assertIsNone(self.run_case('error', 'Failed', app=app))

    def test_stale_generation_is_not_accepted(self):
        rollout = copy.deepcopy(self.rollout); rollout['status']['observedGeneration'] = '3'
        self.assertIsNone(self.run_case('error', 'Failed', rollout=rollout))

    def test_metric_rejection_requires_abort_and_stable_retention(self):
        self.assertEqual(self.run_case('error', 'Failed'), 'candidate-rejected-through-gitops')
        rollout = copy.deepcopy(self.rollout); rollout['status']['abort'] = False
        self.assertIsNone(self.run_case('latency', 'Failed', rollout=rollout))

    def test_fault_cannot_change_stable_selector(self):
        with self.assertRaises(AssertionError):
            self.run_case('error', 'Failed', stable='new')

    def test_healthy_promotion_needs_successful_analysis(self):
        self.assertIsNone(self.run_case('healthy', 'Error', stable='new'))
        self.assertEqual(self.run_case('healthy', 'Successful', stable='new'), 'candidate-promoted-through-gitops')

    def test_missing_traffic_is_inconclusive_not_success(self):
        self.assertIsNone(self.run_case('no-traffic', 'Successful'))
        self.assertEqual(self.run_case('no-traffic', 'Inconclusive'), 'missing-traffic-inconclusive-through-gitops')

    def test_telemetry_transport_error_blocks_candidate(self):
        self.assertEqual(self.run_case('telemetry-outage', 'Error'), 'missing-telemetry-blocked-through-gitops')

    def test_readiness_abort_does_not_require_an_analysis(self):
        self.assertEqual(self.run_case('startup', None), 'readiness-aborted-through-gitops')
