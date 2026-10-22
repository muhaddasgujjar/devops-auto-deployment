import json
import re
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from scripts.publish_environment import publish
from scripts.recovery import Reconciler
from scripts.release_control import decide, deadline, now, read_control, write_control, validate_rollout_policy
from scripts.render_release import ROOT


class RecoveryTests(unittest.TestCase):
    def test_retention_and_history_constraints_including_the_actual_template(self):
        with self.assertRaises(ValueError):
            validate_rollout_policy({'revisionHistoryLimit': 0, 'strategy': {'blueGreen': {'scaleDownDelayRevisionLimit': 1}}})
        with self.assertRaises(ValueError):
            validate_rollout_policy({'strategy': {'blueGreen': {'postPromotionAnalysis': {}, 'scaleDownDelaySeconds': 120}}})
        content = (ROOT / 'templates/release/rollout.yaml').read_text()
        fields = {k: int(v) for k, v in re.findall(r'^\s*(revisionHistoryLimit|scaleDownDelaySeconds|scaleDownDelayRevisionLimit): (\d+)', content, re.M)}
        validate_rollout_policy({'revisionHistoryLimit': fields['revisionHistoryLimit'], 'strategy': {
            'blueGreen': {'postPromotionAnalysis': {}, **{k: v for k, v in fields.items() if k != 'revisionHistoryLimit'}}}})

    def test_promotion_requires_both_complete_analyses_and_live_health(self):
        state = {'phase': 'deploying', 'deadline': deadline(100)}
        good = {'matches': True, 'healthy': True, 'pre': 'Successful', 'post': 'Successful'}
        self.assertEqual(decide(state, good), 'complete')
        for key, value in [('post', 'Running'), ('post', 'Incomplete'), ('healthy', False), ('matches', False)]:
            self.assertEqual(decide(state, {**good, key: value}), 'wait')
        self.assertEqual(decide(state, {'matches': True, 'abort': True}), 'restore')
        self.assertEqual(decide(state, {'matches': True, 'invalid_spec': True}), 'restore')

    def test_recovery_needs_three_verified_samples_and_has_a_deadline(self):
        state = {'phase': 'recovering', 'deadline': deadline(100)}
        self.assertEqual(decide(state, {'matches': True, 'healthy': True, 'verified_samples': 2}), 'wait')
        self.assertEqual(decide(state, {'matches': True, 'healthy': True, 'verified_samples': 3}), 'complete')
        self.assertEqual(decide(state, {'healthy': False}, now() + timedelta(seconds=101)), 'fail')

    def git(self, *args):
        return subprocess.run(['git', *map(str, args)], check=True, text=True, capture_output=True).stdout

    def fixture(self, directory):
        base = Path(directory)
        remote, seed = base / 'env.git', base / 'seed'
        self.git('init', '--bare', '--initial-branch=main', remote)
        self.git('clone', remote, seed)
        self.git('-C', seed, 'config', 'user.name', 'test')
        self.git('-C', seed, 'config', 'user.email', 'test@localhost')
        (seed / 'README.md').write_text('Environment\n')
        self.git('-C', seed, 'add', '.')
        self.git('-C', seed, 'commit', '-m', 'Seed')
        self.git('-C', seed, 'push', 'origin', 'main')
        release = publish(str(remote), 'localhost:5001/demo@sha256:' + 'a' * 64, 'b' * 40, 'main-1', base / 'evidence.json')
        return base, remote, seed, release

    def test_verified_release_unlocks_next_publish_and_restart_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            base, remote, _, release = self.fixture(directory)
            observe = lambda *_: {'matches': True, 'healthy': True, 'pre': 'Successful', 'post': 'Successful'}
            first = Reconciler(str(remote), base / 'state', observe=observe, capture=False).tick()
            self.assertEqual(first['phase'], 'healthy')
            second = Reconciler(str(remote), base / 'state', observe=observe, capture=False).tick()
            self.assertEqual(first['head'], second['head'])
            self.assertEqual(second['deployment_commit'], release['environment_commit'])
            publish(str(remote), 'localhost:5001/demo@sha256:' + 'a' * 64, 'b' * 40, 'main-2', base / 'two.json')

    def test_denied_git_write_stays_failed_across_restart_and_blocks_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            base, remote, _, release = self.fixture(directory)
            hook = remote / 'hooks/pre-receive'
            hook.write_text('#!/bin/sh\nexit 1\n', newline='\n')
            hook.chmod(0o755)
            observe = lambda *_: {'matches': True, 'healthy': True, 'pre': 'Successful', 'post': 'Successful'}
            failed = Reconciler(str(remote), base / 'state', observe=observe, capture=False).tick()
            self.assertEqual(failed['phase'], 'recovery_failed')
            self.assertEqual(failed['blocked_head'], release['environment_commit'])
            self.assertEqual(Reconciler(str(remote), base / 'state', observe=observe, capture=False).tick()['phase'], 'recovery_failed')
            self.assertEqual(self.git('--git-dir', remote, 'rev-parse', 'main').strip(), release['environment_commit'])
            with self.assertRaisesRegex(RuntimeError, 'lease'):
                publish(str(remote), 'localhost:5001/demo@sha256:' + 'a' * 64, 'b' * 40, 'main-2', base / 'two.json')

    def test_recovery_timeout_is_persisted_and_cannot_be_called_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            base, remote, seed, _ = self.fixture(directory)
            self.git('-C', seed, 'pull', '--ff-only')
            state = read_control(seed)
            state.update(phase='recovering', deadline=(now() - timedelta(seconds=1)).isoformat())
            write_control(seed, state)
            self.git('-C', seed, 'add', '.')
            self.git('-C', seed, 'commit', '-m', 'Interrupted recovery')
            self.git('-C', seed, 'push', 'origin', 'main')
            result = Reconciler(str(remote), base / 'state', observe=lambda *_: {'healthy': False}, capture=False).tick()
            self.assertEqual(result['phase'], 'recovery_failed')
            remote_state = json.loads(self.git('--git-dir', remote, 'show', 'main:release-control.json'))
            self.assertEqual(remote_state['phase'], 'recovery_failed')

    def test_environment_edit_outside_active_lease_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            base, remote, seed, _ = self.fixture(directory)
            self.git('-C', seed, 'pull', '--ff-only')
            (seed / 'README.md').write_text('Independent operator edit\n')
            self.git('-C', seed, 'add', '.')
            self.git('-C', seed, 'commit', '-m', 'Operator edit during release')
            self.git('-C', seed, 'push', 'origin', 'main')
            expected = self.git('--git-dir', remote, 'rev-parse', 'main').strip()
            result = Reconciler(str(remote), base / 'state', observe=lambda *_: {}, capture=False).tick()
            self.assertEqual(result['phase'], 'recovery_failed')
            self.assertEqual(result['blocked_head'], expected)
            self.assertEqual(self.git('--git-dir', remote, 'rev-parse', 'main').strip(), expected)
