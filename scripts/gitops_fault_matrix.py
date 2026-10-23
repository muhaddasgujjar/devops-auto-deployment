"""Serial Jenkins/GitOps acceptance, including an unavailable recovery dependency."""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

from scripts.evidence import finalize_archive
from scripts.gitops_trial import Jenkins, validate_availability, validate_fault_evidence
from scripts.live_trial import kube, service_hash
from scripts.recovery_failure_check import status, worker
from scripts.render_release import ROOT

MATRIX = ('latency', 'startup', 'no-traffic', 'telemetry-outage', 'shared-telemetry-outage', 'healthy')


def preflight():
    os.environ['KUBECONFIG'] = str(ROOT / 'output/lab.kubeconfig')
    if kube('config', 'current-context').strip() != 'k3d-release-lab':
        raise RuntimeError('Only the dedicated lab is supported')
    if status().get('phase') not in ('healthy', 'recovered'):
        raise RuntimeError('Complete the active release/recovery before the matrix')
    client = Jenkins()
    if client.json('queue/api/json').get('items'):
        raise RuntimeError('Jenkins queue must be empty')
    for job in ('release-main', 'release-local'):
        build = client.json(f'job/{job}/api/json').get('lastBuild')
        if build and client.json(f'job/{job}/{build["number"]}/api/json')['building']:
            raise RuntimeError('Jenkins must be idle')
    metadata = json.loads(subprocess.check_output(['docker', 'exec', 'release-agent', 'cat',
        '/var/jenkins_home/.cache/trivy/db/metadata.json'], text=True, timeout=30))
    if datetime.fromisoformat(metadata['NextUpdate'].replace('Z', '+00:00')) <= datetime.now(timezone.utc):
        raise RuntimeError('Refresh the agent Trivy database before acceptance')


def verify_shared_failure(folder, trial):
    failed = trial.get('release_control', {})
    if (trial.get('verdict') != 'trial-failed' or 'Recovery failed' not in trial.get('error', '')
            or failed.get('phase') != 'recovery_failed'
            or failed.get('observation', {}).get('fresh_telemetry') is not False
            or 'deadline exceeded' not in failed.get('error', '')
            or not (folder / 'telemetry-fixture.json').exists()):
        raise AssertionError('Shared telemetry outage did not produce the expected bounded recovery failure')
    started = datetime.fromisoformat(failed['recovery_started_at'])
    finished = datetime.fromisoformat(failed['finished_at'])
    if (finished - started).total_seconds() < 600:
        raise AssertionError('Recovery failed before its configured verification window elapsed')
    runs = json.loads((folder / 'analysis-observed.json').read_text())['items']
    validate_fault_evidence('shared-telemetry-outage', [r for r in runs if r['metadata'].get('labels', {}).get(
        'rollouts-pod-template-hash') == trial.get('tested_candidate_hash')], {})
    rows = [json.loads(line) for line in (folder / 'stable.jsonl').read_text().splitlines()]
    validate_availability('shared-telemetry-outage', rows, None)
    return failed


def retry_shared_failure(failed, previous):
    # The child has restored monitoring in finally. Wait for the dependency,
    # prove its return did not silently clear failure, then explicitly retry.
    kube('rollout', 'status', 'deployment/prometheus', '-n', 'monitoring', '--timeout=120s')
    time.sleep(12)
    if status().get('phase') != 'recovery_failed':
        raise AssertionError('Restored telemetry silently cleared the failed recovery')
    result = worker('--retry')
    if result.returncode:
        raise RuntimeError('Explicit recovery retry failed: ' + result.stderr[-1000:])
    end = time.monotonic() + 700
    while time.monotonic() < end:
        recovered = status()
        sync = json.loads(kube('get', 'application', 'release-demo-dev', '-n', 'argocd', '-o', 'json')).get('status', {}).get('sync', {})
        if recovered.get('phase') == 'recovery_failed':
            raise RuntimeError('Explicit recovery retry reached failed state')
        if (recovered.get('phase') == 'recovered' and sync.get('status') == 'Synced'
                and sync.get('revision') == recovered.get('head')):
            if (service_hash() != previous or recovered.get('attempt', 0) <= failed.get('attempt', 1)
                    or recovered.get('deployment_commit') != failed.get('deployment_commit')):
                raise AssertionError('Retry did not verify the same release as a new attempt')
            return recovered
        time.sleep(3)
    raise TimeoutError('Explicit retry did not verify desired and serving recovery')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenarios', nargs='+', choices=MATRIX, default=list(MATRIX))
    args = parser.parse_args()
    preflight()
    folder = ROOT / 'output' / ('gitops-fault-matrix-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    folder.mkdir()
    summary = {'started': datetime.now(timezone.utc).isoformat(), 'scenarios': args.scenarios, 'trials': []}
    child = None
    try:
        for scenario in args.scenarios:
            preflight()
            previous = service_hash()
            before = set((ROOT / 'output').glob('gitops-' + scenario + '-*'))
            print('Starting actual CI/GitOps acceptance: ' + scenario, flush=True)
            with (folder / (scenario + '-console.txt')).open('w') as log:
                child = subprocess.Popen([sys.executable, '-m', 'scripts.gitops_trial', scenario],
                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                code = child.wait(timeout=3100)
            candidates = set((ROOT / 'output').glob('gitops-' + scenario + '-*')) - before
            if len(candidates) != 1:
                raise AssertionError('Cannot uniquely identify the child trial')
            trial_folder = candidates.pop()
            trial = json.loads((trial_folder / 'summary.json').read_text())
            entry = {'run_id': trial_folder.name, **trial}
            summary['trials'].append(entry)
            if scenario == 'shared-telemetry-outage':
                failed = verify_shared_failure(trial_folder, trial)
                if code == 0:
                    raise AssertionError('Ordinary trial falsely reported failed recovery as successful')
                print('Unavailable telemetry correctly prevented recovery; restoring and explicitly retrying', flush=True)
                entry['explicit_retry'] = retry_shared_failure(failed, previous)
                entry['fixture_verdict'] = 'shared-dependency-failure-and-explicit-retry-verified'
            elif code or trial.get('verdict') == 'trial-failed':
                raise RuntimeError(f'{scenario} failed; inspect {trial_folder.name}: {trial.get("error")}')
            print(scenario + ': verified', flush=True)
        summary['verdict'] = 'gitops-fault-matrix-verified'
    except BaseException as exc:
        summary.update(verdict='gitops-fault-matrix-failed', error=str(exc))
        raise
    finally:
        if child and child.poll() is None:
            os.killpg(child.pid, signal.SIGINT)
            try:
                child.wait(timeout=45)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        summary['finished'] = datetime.now(timezone.utc).isoformat()
        (folder / 'summary.json').write_text(json.dumps(summary, indent=2))
        finalize_archive(folder)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
