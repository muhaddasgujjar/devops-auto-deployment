"""Prove denied recovery writes stay blocked across restart, then explicitly retry."""
import json
import os
import subprocess
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.evidence import finalize_archive
from scripts.gitops_trial import Jenkins
from scripts.live_trial import kube, resource, service_hash
from scripts.render_release import ROOT

UNIT = 'release-lab-recovery.service'
STATUS = Path('/var/lib/release-lab/recovery/status.json')


def status():
    return json.loads(STATUS.read_text())


def worker(*args):
    return subprocess.run([sys.executable, '-m', 'scripts.recovery', *args],
                          capture_output=True, text=True, timeout=180)


def main():
    os.environ['KUBECONFIG'] = str(ROOT / 'output/lab.kubeconfig')
    if kube('config', 'current-context').strip() != 'k3d-release-lab':
        raise SystemExit('Only the dedicated lab is supported')
    if resource('rollout', 'release-demo')['status'].get('phase') != 'Healthy' or status().get('phase') not in ('healthy', 'recovered'):
        raise SystemExit('Complete the active release/recovery before this failure check')
    client = Jenkins()
    for job in ('release-main', 'release-local'):
        latest = client.json(f'job/{job}/api/json').get('lastBuild')
        if latest and client.json(f'job/{job}/{latest["number"]}/api/json')['building']:
            raise SystemExit('CI must be idle before stopping the recovery observer')
    repo = json.loads((ROOT / 'output/gitops/local-git.json').read_text())['repository_url']
    read_env = {**os.environ, 'GIT_SSH_COMMAND': 'ssh -i /opt/release-lab/secrets/environment-read -o IdentitiesOnly=yes '
                '-o StrictHostKeyChecking=yes -o UserKnownHostsFile=/opt/release-lab/secrets/known_hosts'}
    def head():
        return subprocess.check_output(['git', 'ls-remote', repo, 'refs/heads/main'], env=read_env, text=True, timeout=30).split()[0]
    if status().get('head') != head():
        raise SystemExit('Wait for the recovery observer to catch up with environment Git')
    folder = ROOT / 'output' / ('recovery-write-check-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    folder.mkdir(parents=True)
    summary = {'started': datetime.now(timezone.utc).isoformat(), 'fixture': 'read-only-recovery-key'}
    previous = service_hash()
    old_folders = set((ROOT / 'output').glob('gitops-post-error-*'))
    child = None
    log = (folder / 'observer-console.txt').open('w')
    try:
        subprocess.run(['systemctl', 'stop', UNIT], check=True)
        child = subprocess.Popen([sys.executable, '-m', 'scripts.gitops_trial', 'post-error', '--job', 'release-main'],
                                 stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        print('Testing a serving fault with recovery observer paused', flush=True)
        end = time.monotonic() + 1200
        while time.monotonic() < end:
            rollout = resource('rollout', 'release-demo')['status']
            candidate = rollout.get('currentPodHash')
            runs = resource('analysisrun')['items']
            failed = any(r['metadata'].get('labels', {}).get('rollouts-pod-template-hash') == candidate
                         and r['metadata']['labels'].get('rollout-type') == 'PostPromotion'
                         and r.get('status', {}).get('phase') in ('Failed', 'Error') for r in runs)
            if candidate != previous and rollout.get('abort') and failed and service_hash() == previous:
                break
            if child.poll() is not None:
                raise RuntimeError('Fault observer exited before native post-promotion rollback')
            time.sleep(3)
        else:
            raise TimeoutError('Native rollback was not observed')
        denied = worker('--read-key')
        failed = status()
        if denied.returncode != 1 or failed.get('phase') != 'recovery_failed' or not failed.get('blocked_head'):
            raise AssertionError('Read-only key did not produce an explicit failed recovery')
        summary['denied_write'] = failed
        blocked = head()
        subprocess.run(['systemctl', 'start', UNIT], check=True)
        time.sleep(12)
        if status().get('phase') != 'recovery_failed' or head() != blocked:
            raise AssertionError('Restart silently retried or cleared the denied-write block')
        summary['failure_persisted_across_restart'] = True
        print('Denied Git write remained blocked across observer restart', flush=True)
        if child.wait(timeout=60) == 0:
            raise AssertionError('The ordinary trial falsely reported a failed recovery as successful')
        observer_folders = set((ROOT / 'output').glob('gitops-post-error-*')) - old_folders
        if len(observer_folders) != 1:
            raise AssertionError('Could not identify the retained failure trial')
        observer_folder = observer_folders.pop()
        trial = json.loads((observer_folder / 'summary.json').read_text())
        summary['fault_trial'] = {'run_id': observer_folder.name, 'jenkins_build': trial.get('jenkins_build'),
                                 'stable_requests': trial.get('stable_requests'), 'stable_non_200': trial.get('stable_non_200')}
        if trial.get('verdict') != 'trial-failed' or 'Recovery failed' not in trial.get('error', ''):
            raise AssertionError('Failure trial did not record the expected recovery failure')
        bad_revision = trial['source_commit'] + '-' + trial['release_id']
        rows = [json.loads(line) for line in (observer_folder / 'stable.jsonl').read_text().splitlines()]
        errors = [row for row in rows if row.get('status') != 200]
        if not errors or any(row.get('status') != 500 or row.get('response', {}).get('revision') != bad_revision for row in errors):
            raise AssertionError('Failure check saw unexpected serving failures beyond the injected candidate')
        retried = worker('--retry')
        if retried.returncode:
            raise RuntimeError('Explicit recovery retry failed: ' + retried.stderr[-1000:])
        print('Explicit write-key retry submitted; checking desired and serving state', flush=True)
        end = time.monotonic() + 700
        while time.monotonic() < end:
            recovered = status()
            app = json.loads(kube('get', 'application', 'release-demo-dev', '-n', 'argocd', '-o', 'json'))
            sync = app.get('status', {}).get('sync', {})
            if recovered.get('phase') == 'recovery_failed':
                raise RuntimeError('Recovery retry reached failed state')
            if recovered.get('phase') == 'recovered' and sync.get('revision') == recovered.get('head') and sync.get('status') == 'Synced':
                break
            time.sleep(3)
        else:
            raise TimeoutError('Explicit retry did not verify recovery within its deadline')
        if service_hash() != previous or recovered.get('attempt', 0) <= failed.get('attempt', 1):
            raise AssertionError('Retry did not restore the previous healthy release as a new attempt')
        summary.update(verdict='denied-write-restart-and-retry-verified', recovery=recovered)
        (folder / 'recovery.json').write_text(json.dumps({'failed': failed, 'recovered': recovered}, indent=2))
    except Exception as exc:
        summary.update(verdict='recovery-failure-check-failed', error=str(exc))
        raise
    finally:
        if child and child.poll() is None:
            os.killpg(child.pid, signal.SIGINT)
            try:
                child.wait(timeout=40)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        subprocess.run(['systemctl', 'start', UNIT], check=True)
        log.close()
        summary['finished'] = datetime.now(timezone.utc).isoformat()
        (folder / 'summary.json').write_text(json.dumps(summary, indent=2))
        finalize_archive(folder)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
