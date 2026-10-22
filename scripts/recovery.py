"""Reconcile the fixed local release lease; Rollouts alone owns traffic selectors."""
import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

from scripts.evidence import archive_run
from scripts.live_trial import kube, resource
from scripts.publish_environment import git
from scripts.release_control import CONTROL, deadline, decide, now, read_control, write_control
from scripts.render_release import ROOT, IMAGE

DATA = Path('/var/lib/release-lab/recovery')
FILES = ('analysis.yaml', 'namespace.yaml', 'rollout.yaml', 'services.yaml')


def observation(state, head):
    rollout = resource('rollout', 'release-demo')
    status = rollout.get('status', {})
    container = rollout['spec']['template']['spec']['containers'][0]
    revision = next(e['value'] for e in container['env'] if e['name'] == 'APP_REVISION')
    target_revision = state.get('target_revision') if state['phase'] == 'recovering' else state['source_commit'] + '-' + state['release_id']
    target_image = state.get('target_image') if state['phase'] == 'recovering' else state['image']
    current = status.get('currentPodHash')
    serving = resource('service', 'demo-stable')['spec']['selector'].get('rollouts-pod-template-hash')
    runs = [r for r in resource('analysisrun')['items']
            if r['metadata'].get('labels', {}).get('rollouts-pod-template-hash') == current]
    def analysis(kind):
        matching = [r for r in runs if r['metadata']['labels'].get('rollout-type') == kind]
        if not matching:
            return None
        run = max(matching, key=lambda r: r['metadata']['creationTimestamp'])
        phase = run.get('status', {}).get('phase')
        # Cancelled/shortened measurements must not certify the complete gate.
        if phase == 'Successful' and (len(run.get('status', {}).get('metricResults', [])) != 2
                or any(m.get('successful', 0) < 5 for m in run['status']['metricResults'])):
            return 'Incomplete'
        return phase
    app = json.loads(kube('get', 'application', 'release-demo-dev', '-n', 'argocd', '-o', 'json'))
    sync = app.get('status', {}).get('sync', {})
    response, fresh = {}, False
    try:
        response = json.loads(kube('get', '--raw', '/api/v1/namespaces/demo-dev/services/demo-stable:80/proxy/'))
        selector = 'up{job="demo-pods",namespace="demo-dev",revision="' + str(serving) + '"}'
        expression = (f'count({selector}) == 2 and on() (min({selector}) == 1) '
                      f'and on() (max(time() - timestamp({selector})) <= 15)')
        metrics = json.loads(kube('get', '--raw', '/api/v1/namespaces/monitoring/services/prometheus:9090/proxy/api/v1/query?'
                                  + urlencode({'query': expression})))
        fresh = metrics.get('status') == 'success' and len(metrics.get('data', {}).get('result', [])) == 1
    except Exception:
        pass  # Unreachable/unhealthy serving or telemetry cannot certify recovery.
    matches = revision == target_revision and container['image'] == target_image
    healthy = (matches and status.get('phase') == 'Healthy' and serving == current
               and str(status.get('observedGeneration')) == str(rollout['metadata']['generation'])
               and sync.get('status') == 'Synced' and sync.get('revision') == head
               and response.get('revision') == target_revision and fresh)
    return {'matches': matches, 'healthy': healthy, 'phase': status.get('phase'),
            'invalid_spec': any(c.get('type') == 'InvalidSpec' and c.get('status') == 'True' for c in status.get('conditions', [])),
            'abort': bool(status.get('abort')), 'pre': analysis('PrePromotion'), 'post': analysis('PostPromotion'),
            'serving_hash': serving, 'candidate_hash': current, 'response': response, 'fresh_telemetry': fresh}


class Reconciler:
    def __init__(self, repository, data=DATA, observe=observation, capture=True):
        self.repository, self.data, self.observe, self.capture = repository, Path(data), observe, capture
        self.data.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.status_path = self.data / 'status.json'

    def status(self):
        return json.loads(self.status_path.read_text()) if self.status_path.exists() else {}

    def save(self, state):
        state['updated_at'] = now().isoformat()
        temporary = self.status_path.with_suffix('.tmp')
        with temporary.open('w') as stream:
            stream.write(json.dumps(state, indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.status_path)
        return state

    def commit(self, directory, state, message):
        write_control(directory, state)
        git(directory, 'config', 'user.name', 'release-recovery')
        git(directory, 'config', 'user.email', 'release-recovery@localhost')
        git(directory, 'add', '--', CONTROL, 'environments/dev')
        git(directory, 'commit', '-m', message)
        # Compare-and-swap via normal fast-forward push. Never force or rebase.
        git(directory, 'push', 'origin', 'HEAD:main')
        return git(directory, 'rev-parse', 'HEAD').stdout.strip()

    def folder(self, state):
        return ROOT / 'output' / f"recovery-{state['deployment_commit']}-{state.get('attempt', 1)}"

    def record(self, state, final=False):
        if not self.capture:
            return
        folder = self.folder(state)
        folder.mkdir(parents=True, exist_ok=True)
        # Preserve failing resources before Git restoration allows native GC.
        if not (folder / 'rollout.json').exists():
            for kind in ('rollout', 'analysisrun', 'service', 'pod'):
                try:
                    (folder / (kind + '.json')).write_text(kube('get', kind, '-n', 'demo-dev', '-o', 'json'))
                except Exception as exc:
                    state['capture_' + kind + '_error'] = str(exc)
        (folder / 'recovery.json').write_text(json.dumps(state, indent=2))
        if final:
            (folder / 'summary.json').write_text(json.dumps({'verdict': 'recovery-verified' if state['phase'] == 'recovered'
                                                          else 'recovery-failed', **state}, indent=2))
            try:
                archive_run(folder)
            except Exception as exc:
                state['archive_error'] = str(exc)

    def restore(self, directory, head, state):
        import yaml  # Only the WSL observer needs validation dependencies.
        previous = state['previous_commit']
        for name in FILES:
            content = git(directory, 'show', previous + ':environments/dev/' + name).stdout
            (Path(directory) / 'environments/dev' / name).write_text(content, newline='\n')
        target = yaml.safe_load((Path(directory) / 'environments/dev/rollout.yaml').read_text())
        container = target['spec']['template']['spec']['containers'][0]
        if not IMAGE.fullmatch(container['image']):
            raise ValueError('Recovery target is not a digest-pinned known-good release')
        state.update(phase='recovering', deployment_commit=state.get('deployment_commit', head),
                     target_image=container['image'], target_revision=next(e['value'] for e in container['env'] if e['name'] == 'APP_REVISION'),
                     deadline=deadline(600), recovery_started_at=now().isoformat())
        self.record(state)
        new_head = self.commit(directory, state, 'Restore known-good desired release after ' + state['release_id'])
        return self.save({**state, 'head': new_head, 'verified_samples': 0})

    def tick(self, retry=False):
        with tempfile.TemporaryDirectory(prefix='release-recovery-') as directory:
            git(directory, 'clone', '--branch', 'main', '--single-branch', '--', self.repository, directory)
            head = git(directory, 'rev-parse', 'HEAD').stdout.strip()
            state = read_control(directory)
            if state is None:
                return self.save({'phase': 'unmanaged', 'head': head})
            cached = self.status()
            if cached.get('blocked_head') == head and not retry:
                return cached  # An operator must explicitly retry a failed write.
            control_commit = git(directory, 'log', '-1', '--format=%H', '--', CONTROL).stdout.strip()
            state.setdefault('deployment_commit', control_commit)
            if state['phase'] in ('deploying', 'recovering') and head != control_commit and not retry:
                return self.save({**state, 'phase': 'recovery_failed', 'head': head, 'blocked_head': head,
                                  'error': 'Environment changed outside the active release lease; operator review required'})
            if retry:
                if cached.get('blocked_head') != head and state['phase'] != 'recovery_failed':
                    raise ValueError('Only an explicitly failed recovery can be retried')
                state['attempt'] = state.get('attempt', 1) + 1
                state['failure_stage'] = cached.get('failure_stage', state.get('failure_stage', 'operator-retry'))
                return self.restore(directory, head, state)
            if state['phase'] not in ('deploying', 'recovering'):
                return self.save({**state, 'head': head})
            try:
                observed = self.observe(state, head)
            except Exception as exc:
                observed = {'healthy': False, 'matches': False, 'error': str(exc)}
            streak = cached.get('verified_samples', 0) if cached.get('head') == head else 0
            observed['verified_samples'] = streak + 1 if observed.get('healthy') else 0
            action = decide(state, observed)
            state['observation'] = observed
            try:
                if action == 'restore':
                    state['failure_stage'] = 'post-promotion' if observed.get('post') in ('Failed', 'Error', 'Incomplete') else 'pre-promotion-or-timeout'
                    return self.restore(directory, head, state)
                if action in ('complete', 'fail'):
                    state['phase'] = ('recovered' if state['phase'] == 'recovering' else 'healthy') if action == 'complete' else 'recovery_failed'
                    state['finished_at'] = now().isoformat()
                    head = self.commit(directory, state, 'Verify release ' + state['release_id'] + ': ' + state['phase'])
                    if state['phase'] in ('recovered', 'recovery_failed'):
                        self.record({**state, 'head': head}, final=True)
                return self.save({**state, 'head': head, 'verified_samples': observed['verified_samples']})
            except Exception as exc:
                failed = {**state, 'phase': 'recovery_failed', 'blocked_head': git(directory, 'rev-parse', 'origin/main').stdout.strip(),
                          'head': head, 'error': str(exc), 'finished_at': now().isoformat()}
                self.record(failed, final=True)
                return self.save(failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--retry', action='store_true')
    parser.add_argument('--read-key', action='store_true', help='Exercise denied-write handling with the read-only key')
    args = parser.parse_args()
    os.environ['KUBECONFIG'] = str(ROOT / 'output/lab.kubeconfig')
    os.environ['GIT_SSH_COMMAND'] = ('ssh -i /opt/release-lab/secrets/environment-' + ('read' if args.read_key else 'write')
                                   + ' -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/opt/release-lab/secrets/known_hosts')
    repo = json.loads((ROOT / 'output/gitops/local-git.json').read_text())['repository_url']
    reconciler = Reconciler(repo)
    if args.status:
        print(json.dumps(reconciler.status(), indent=2))
        return
    if kube('config', 'current-context').strip() != 'k3d-release-lab':
        raise SystemExit('Only the dedicated lab is supported')
    import fcntl
    while True:
        try:
            with (DATA / 'worker.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                result = reconciler.tick(retry=args.retry)
            if not args.watch:
                print(json.dumps(result, indent=2))
                if result.get('phase') == 'recovery_failed':
                    raise SystemExit(1)
                return
        except Exception as exc:
            if not args.watch:
                raise
            print('Recovery observer error: ' + str(exc), flush=True)
        time.sleep(5)


if __name__ == '__main__':
    main()
