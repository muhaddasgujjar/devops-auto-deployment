import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.git_ssh_command import allowed_command, REPOSITORY
from scripts.publish_environment import publish
from scripts.release_control import write_control, read_control


class GitOpsTests(unittest.TestCase):
    def test_keys_cannot_escape_repository_or_write_with_read_role(self):
        self.assertEqual(allowed_command(f"git-upload-pack '{REPOSITORY}'", 'read'), ['git-upload-pack', REPOSITORY])
        self.assertEqual(allowed_command(f"git-receive-pack '{REPOSITORY}'", 'write'), ['git-receive-pack', REPOSITORY])
        for command, role in [(f"git-receive-pack '{REPOSITORY}'", 'read'),
                              ('git-upload-pack /etc', 'write'), (f'git-upload-pack {REPOSITORY}; id', 'write'),
                              ('sh', 'read')]:
            with self.assertRaises(ValueError):
                allowed_command(command, role)

    def test_publish_writes_digest_unique_release_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            remote, seed = base / 'env.git', base / 'seed'
            def git(*args):
                return subprocess.run(['git', *map(str, args)], check=True, text=True, capture_output=True).stdout
            git('init', '--bare', '--initial-branch=main', remote)
            git('clone', remote, seed)
            git('-C', seed, 'config', 'user.name', 'test')
            git('-C', seed, 'config', 'user.email', 'test@localhost')
            (seed / 'README.md').write_text('Environment\n')
            git('-C', seed, 'add', '.')
            git('-C', seed, 'commit', '-m', 'Initialize environment')
            git('-C', seed, 'push', 'origin', 'main')
            image, sha = 'localhost:5001/release-demo@sha256:' + 'a' * 64, 'b' * 40
            evidence = base / 'evidence.json'
            first = publish(str(remote), image, sha, 'jenkins-1', evidence)
            self.assertTrue(first['changed'])
            content = git('--git-dir', remote, 'show', 'main:environments/dev/rollout.yaml')
            self.assertIn(image, content)
            self.assertIn(sha + '-jenkins-1', content)
            second = publish(str(remote), image, sha, 'jenkins-1', evidence)
            self.assertFalse(second['changed'])
            self.assertEqual(first['environment_commit'], second['environment_commit'])
            with self.assertRaisesRegex(RuntimeError, 'lease'):
                publish(str(remote), image, sha, 'jenkins-2', evidence)
            git('-C', seed, 'pull', '--ff-only')
            state = read_control(seed)
            state['phase'] = 'healthy'
            write_control(seed, state)
            git('-C', seed, 'add', 'release-control.json')
            git('-C', seed, 'commit', '-m', 'Verify previous release')
            git('-C', seed, 'push', 'origin', 'main')
            third = publish(str(remote), image, sha, 'jenkins-2', evidence)
            self.assertNotEqual(first['environment_commit'], third['environment_commit'])
            self.assertEqual(json.loads(evidence.read_text())['release_id'], 'jenkins-2')

    def test_invalid_release_is_rejected_before_git(self):
        for image, sha, identifier in [('demo:latest', 'b' * 40, 'ok'),
                                      ('localhost:5001/demo@sha256:' + 'a' * 64, 'b' * 40, 'x\nkind: Secret')]:
            with self.assertRaises(ValueError):
                publish('ssh://invalid.example/repo', image, sha, identifier, 'unused.json')
