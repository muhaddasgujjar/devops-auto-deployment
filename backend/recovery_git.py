"""Forward-only, compare-and-swap environment Git writer. No Kubernetes operations."""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import yaml

PATH = 'environments/dev/rollout.yaml'
SHA = re.compile('[a-f0-9]{40}')


class GitUnavailable(RuntimeError):
    pass


class ConcurrentGitChange(RuntimeError):
    pass


def git(directory, *args, check=True):
    try:
        result = subprocess.run(['git', '-C', str(directory), *args], capture_output=True, text=True,
                                timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise GitUnavailable('Environment Git operation unavailable') from None
    if check and result.returncode:
        raise GitUnavailable('Environment Git operation failed')
    return result


def manifest(directory, commit):
    raw = git(directory, 'show', commit + ':' + PATH).stdout
    if len(raw.encode()) > 262144:
        raise GitUnavailable('Environment manifest exceeds the managed size limit')
    document = yaml.safe_load(raw)
    if (document.get('apiVersion') != 'argoproj.io/v1alpha1' or document.get('kind') != 'Rollout' or
        document.get('metadata', {}).get('name') != 'release-demo' or
        document['metadata'].get('namespace') != 'demo-dev'):
        raise GitUnavailable('Environment manifest is outside the managed workload')
    return document


def binding(document):
    containers = document['spec']['template']['spec']['containers']
    if len(containers) != 1 or containers[0]['name'] != 'app':
        raise GitUnavailable('Unexpected workload container identity')
    revisions = [e.get('value') for e in containers[0].get('env', []) if e.get('name') == 'APP_REVISION']
    if len(revisions) != 1:
        raise GitUnavailable('Missing workload source identity')
    return containers[0]['image'], revisions[0]


def expected(release):
    return release['artifact']['image'], f"{release['build']['source_commit']}-jenkins-{release['build']['number']}"


def publish_recovery(repository, recovery, *, guard=lambda: None, before_push=lambda directory: None):
    identifier, base = recovery['id'], recovery['base_commit']
    target, origin = recovery['target'], recovery['origin']
    if (not re.fullmatch('[a-f0-9-]{36}', identifier) or not SHA.fullmatch(base) or
        not target or not SHA.fullmatch(target['environment_commit'])):
        raise ValueError('Recovery requires immutable incident and target identities')
    if not repository.startswith('ssh://') and not Path(repository).is_absolute():
        raise ValueError('Use the scoped SSH repository or an absolute isolated test repository')
    marker = 'metadata/recoveries/' + identifier + '.json'
    receipt = {'recovery_id': identifier, 'base_commit': base, 'target_release_id': target['id'],
               'target_environment_commit': target['environment_commit'], 'image': expected(target)[0],
               'revision': expected(target)[1], 'policy': recovery['policy']}
    with tempfile.TemporaryDirectory(prefix='release-recovery-git-') as directory:
        try:
            subprocess.run(['git', 'clone', '--branch', 'main', '--single-branch', '--', repository, directory],
                           capture_output=True, check=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            raise GitUnavailable('Environment Git clone unavailable') from None
        head = git(directory, 'rev-parse', 'HEAD').stdout.strip()
        prior = git(directory, 'show', head + ':' + marker, check=False)
        if prior.returncode == 0:
            if json.loads(prior.stdout) != receipt:
                raise GitUnavailable('Recovery marker differs from the retained incident')
            published = git(directory, 'log', '-1', '--format=%H', '--', marker).stdout.strip()
            if head != published:
                raise ConcurrentGitChange('A newer environment commit follows this recovery')
            if git(directory, 'rev-parse', head + '^').stdout.strip() != base or binding(manifest(directory, head)) != expected(target):
                raise GitUnavailable('Published recovery lineage or target differs')
            return {'environment_commit': head, 'changed': False, **receipt}
        if head != base:
            raise ConcurrentGitChange('Environment Git advanced before recovery')
        guard()
        current = manifest(directory, head)
        accepted = manifest(directory, target['environment_commit'])
        if binding(current) != expected(origin) or binding(accepted) != expected(target):
            raise GitUnavailable('Git workload identity differs from accepted evidence')
        if git(directory, 'merge-base', '--is-ancestor', target['environment_commit'], base, check=False).returncode:
            raise GitUnavailable('Accepted target is not in the environment history')
        # Restore only the accepted pod template. Keep today's services, replica
        # count, strategy, analysis policy and every unrelated environment file.
        current['spec']['template'] = accepted['spec']['template']
        current['metadata'].setdefault('annotations', {})['release-lab/recovery-id'] = identifier
        (Path(directory) / PATH).write_text(yaml.safe_dump(current, sort_keys=False), newline='\n')
        record = Path(directory) / marker
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps(receipt, sort_keys=True, indent=2) + '\n', newline='\n')
        git(directory, 'config', 'user.name', 'release-recovery')
        git(directory, 'config', 'user.email', 'release-recovery@localhost')
        git(directory, 'add', '--', PATH, marker)
        git(directory, 'commit', '-m', 'Recover accepted release\n\nRecovery-ID: ' + identifier)
        commit = git(directory, 'rev-parse', 'HEAD').stdout.strip()
        assert git(directory, 'rev-parse', commit + '^').stdout.strip() == base
        before_push(directory)  # Injectable concurrent-writer/crash test boundary.
        guard()
        pushed = git(directory, 'push', 'origin', 'HEAD:refs/heads/main', check=False)
        if pushed.returncode:
            remote = git(directory, 'ls-remote', 'origin', 'refs/heads/main', check=False)
            observed = remote.stdout.split()[0] if remote.returncode == 0 and remote.stdout.split() else None
            if observed != commit:
                if observed and observed != base:
                    raise ConcurrentGitChange('A concurrent publisher won the environment Git update')
                raise GitUnavailable('Recovery push could not be confirmed')
        return {'environment_commit': commit, 'changed': True, **receipt}
