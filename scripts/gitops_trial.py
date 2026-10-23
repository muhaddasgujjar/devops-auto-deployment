"""Observe a local Jenkins -> environment Git -> Argo CD -> Rollouts trial."""
import argparse
import base64
import http.cookiejar
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor

from scripts.live_trial import kube, resource, sample, service_hash
from scripts.render_release import ROOT


SCENARIOS = ('healthy', 'error', 'latency', 'startup', 'post-error', 'no-traffic',
             'telemetry-outage', 'shared-telemetry-outage')


def artifact_mode(scenario):
    return 'healthy' if scenario in ('no-traffic', 'telemetry-outage', 'shared-telemetry-outage') else scenario


def validate_availability(scenario, rows, expected_revision):
    if not rows:
        raise AssertionError('No independent serving observations were recorded')
    errors = [row for row in rows if row.get('status') != 200]
    if scenario == 'post-error':
        if not errors or any(row.get('status') != 500 or row.get('response', {}).get('revision') != expected_revision for row in errors):
            raise AssertionError('Fault trial must record candidate 500s only, followed by verified recovery')
        last_error = max(i for i, row in enumerate(rows) if row.get('status') != 200)
        if not any(row.get('status') == 200 for row in rows[last_error + 1:]):
            raise AssertionError('No healthy serving observation after the candidate failures')
    elif errors:
        raise AssertionError('Stable failures were observed; inspect retained evidence')


def validate_fault_evidence(scenario, runs, rollout):
    metrics = [m for r in runs for m in r.get('status', {}).get('metricResults', [])]
    if scenario == 'latency':
        passed = any(m.get('name') == 'candidate-p95-latency' and m.get('phase') == 'Failed' for m in metrics)
    elif scenario == 'no-traffic':
        passed = any(m.get('phase') == 'Inconclusive' and any(v.get('value') in ('[]', '[NaN]')
                     for v in m.get('measurements', [])) for m in metrics)
    elif scenario in ('telemetry-outage', 'shared-telemetry-outage'):
        passed = any(m.get('phase') == 'Error' and any(v.get('phase') == 'Error'
                     for v in m.get('measurements', [])) for m in metrics)
    elif scenario == 'startup':
        if rollout.get('kind') == 'List':
            rollout = next((item for item in rollout.get('items', [])
                            if item.get('metadata', {}).get('name') == 'release-demo'), {})
        status = rollout.get('status', {})
        passed = any(c.get('reason') == 'ProgressDeadlineExceeded' or (
            status.get('abort') and c.get('type') == 'Progressing' and c.get('status') == 'False'
            and c.get('reason') == 'RolloutAborted' and 'has timed out progressing' in c.get('message', ''))
            for c in status.get('conditions', []))
    else:
        return
    if not passed:
        raise AssertionError('Missing evidence of the intended ' + scenario + ' failure')


class TelemetryFixture:
    """Temporary monitoring maintenance; never modifies Git-owned app manifests."""
    def __init__(self, folder):
        self.folder, self.replicas = folder, None

    def start(self):
        deployment = json.loads(kube('get', 'deployment', 'prometheus', '-n', 'monitoring', '-o', 'json'))
        replicas = deployment['spec'].get('replicas', 1)
        if replicas != 1 or deployment.get('status', {}).get('availableReplicas', 0) != 1:
            raise RuntimeError('Telemetry fixture requires the healthy single-replica lab monitor')
        self.replicas = replicas
        # Persist the restoration target before mutation, including on interruption.
        (self.folder / 'telemetry-fixture.json').write_text(json.dumps({'replicas': replicas, 'started': datetime.now(timezone.utc).isoformat()}))
        kube('scale', 'deployment/prometheus', '-n', 'monitoring', '--replicas=0', '--current-replicas=1')
        print('Controlled telemetry outage started', flush=True)

    def restore(self):
        if self.replicas is not None:
            kube('scale', 'deployment/prometheus', '-n', 'monitoring', '--replicas=' + str(self.replicas))
            self.replicas = None
            print('Monitoring replica count restored; waiting for fresh recovery evidence', flush=True)


class Jenkins:
    def __init__(self):
        password = Path('/opt/release-lab/secrets/jenkins-password').read_text().strip()
        self.auth = 'Basic ' + base64.b64encode(('release-admin:' + password).encode()).decode()
        self.client = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, path, data=None, headers=None):
        if path.startswith('http://'):
            # Queue locations come from our loopback server; never send auth elsewhere.
            if not path.startswith('http://127.0.0.1:8082/'):
                raise ValueError('Unexpected Jenkins queue origin')
            url = path
        else:
            url = 'http://127.0.0.1:8082/' + path
        with self.client.open(Request(url, data=data, headers={'Authorization': self.auth, **(headers or {})}), timeout=15) as response:
            return response.read(), response.headers

    def json(self, path):
        return json.loads(self.request(path)[0])

    def build(self, mode, job):
        crumb = self.json('crumbIssuer/api/json')
        _, headers = self.request(f'job/{job}/buildWithParameters', urlencode({'DEMO_MODE': mode}).encode(),
                                  {crumb['crumbRequestField']: crumb['crumb'], 'Content-Type': 'application/x-www-form-urlencoded'})
        return headers['Location']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', choices=SCENARIOS)
    parser.add_argument('--job', choices=['release-local', 'release-main'], default='release-main')
    parser.add_argument('--observe-build', type=int, help='Observe an existing build without triggering another')
    parser.add_argument('--retry-analysis', action='store_true', help='Retry an interrupted inconclusive candidate after starting traffic')
    args = parser.parse_args()
    os.environ['KUBECONFIG'] = str(ROOT / 'output/lab.kubeconfig')
    if kube('config', 'current-context').strip() != 'k3d-release-lab':
        parser.error('Only the named lab is supported')
    app = json.loads(kube('get', 'application', 'release-demo-dev', '-n', 'argocd', '-o', 'json'))
    if app.get('status', {}).get('sync', {}).get('status') != 'Synced':
        parser.error('Environment Application must be Synced before starting a trial')
    folder = ROOT / 'output' / ('gitops-' + args.scenario + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    folder.mkdir(parents=True, exist_ok=False)
    old_hash = service_hash()
    summary = {'scenario': args.scenario, 'jenkins_job': args.job, 'previous_stable_hash': old_hash,
               'started': datetime.now(timezone.utc).isoformat()}
    telemetry = TelemetryFixture(folder)
    telemetry_started = False
    observed_runs = {}
    expected_revision = None
    stop, threads = threading.Event(), []
    log = (folder / 'proxy.log').open('w')
    proxy = subprocess.Popen(['kubectl', 'proxy', '--address=127.0.0.1', '--port=18001'], stdout=log, stderr=subprocess.STDOUT)
    root = 'http://127.0.0.1:18001/api/v1/namespaces/demo-dev/services/'

    def traffic(service, filename):
        with (folder / filename).open('a') as stream:
            while not stop.is_set():
                stream.write(json.dumps(sample(root + service + ':80/proxy/', preview=service == 'demo-preview')) + '\n')
                stream.flush()
                stop.wait(0.2)

    def start_traffic(service, filename):
        worker = threading.Thread(target=traffic, args=(service, filename), daemon=True)
        worker.start()
        threads.append(worker)

    try:
        for _ in range(30):
            if proxy.poll() is not None:
                raise RuntimeError('Proxy port unavailable; another trial may be running')
            if sample(root + 'demo-stable:80/proxy/').get('status') == 200:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('Stable application was not reachable before the test')
        start_traffic('demo-stable', 'stable.jsonl')
        jenkins = Jenkins()
        deadline = time.monotonic() + 1200
        number = args.observe_build
        if not number:
            queue = jenkins.build(artifact_mode(args.scenario), args.job)
            while time.monotonic() < deadline:
                queued = jenkins.json(queue + 'api/json')
                if queued.get('cancelled'):
                    raise RuntimeError('Jenkins queue item cancelled')
                number = queued.get('executable', {}).get('number')
                if number:
                    break
                time.sleep(2)
        if not number:
            raise TimeoutError('No executor became available')
        summary['jenkins_build'] = number
        print(f'Jenkins build {number}; waiting for scan and environment commit', flush=True)
        while time.monotonic() < deadline:
            try:
                build = jenkins.json(f'job/{args.job}/{number}/api/json')
            except HTTPError as exc:
                if args.observe_build and exc.code == 404:
                    time.sleep(3)
                    continue
                raise
            if not build['building']:
                (folder / 'jenkins-build.json').write_text(json.dumps(build, indent=2))
                (folder / 'jenkins-console.txt').write_bytes(jenkins.request(f'job/{args.job}/{number}/consoleText')[0])
                if build['result'] != 'SUCCESS':
                    raise RuntimeError(f'Jenkins result: {build["result"]}; inspect retained console')
                summary['build_causes'] = [cause for action in build.get('actions', [])
                                           for cause in action.get('causes', [])]
                break
            time.sleep(3)
        else:
            raise TimeoutError('Jenkins build exceeded observation deadline')
        evidence = jenkins.json(f'job/{args.job}/{number}/artifact/output/environment-commit.json')
        summary.update(evidence)
        for filename in ('scan.json', 'sbom.json', 'environment-commit.json'):
            (folder / filename).write_bytes(jenkins.request(f'job/{args.job}/{number}/artifact/output/{filename}')[0])
        if any(a.get('relativePath') == 'output/trivy-db-metadata.json' for a in build.get('artifacts', [])):
            (folder / 'trivy-db-metadata.json').write_bytes(
                jenkins.request(f'job/{args.job}/{number}/artifact/output/trivy-db-metadata.json')[0])
        print('Build passed; observing Argo reconciliation and candidate analysis', flush=True)
        expected_revision = evidence['source_commit'] + '-' + evidence['release_id']
        for i in range(0 if args.scenario == 'no-traffic' else 4):
            start_traffic('demo-preview', f'preview-{i}.jsonl')
        if args.retry_analysis:
            # retry rollout only acts on aborted releases. An inconclusive run
            # must be aborted first; resuming it would bypass fresh measurement.
            state = resource('rollout', 'release-demo').get('status', {})
            if any(p.get('reason') == 'InconclusiveAnalysisRun' for p in state.get('pauseConditions', [])):
                subprocess.run(['kubectl', 'argo', 'rollouts', 'abort', 'release-demo', '-n', 'demo-dev'], check=True)
                for _ in range(30):
                    if resource('rollout', 'release-demo').get('status', {}).get('abort'):
                        break
                    time.sleep(1)
                else:
                    raise TimeoutError('Inconclusive candidate did not abort before retry')
            subprocess.run(['kubectl', 'argo', 'rollouts', 'retry', 'rollout', 'release-demo', '-n', 'demo-dev'], check=True)
            summary['operator_analysis_retry'] = True
        deadline = time.monotonic() + 1800
        while time.monotonic() < deadline:
            rollout = resource('rollout', 'release-demo')
            env = rollout['spec']['template']['spec']['containers'][0]['env']
            current_revision = next(e['value'] for e in env if e['name'] == 'APP_REVISION')
            state = rollout.get('status', {})
            candidate = state.get('currentPodHash')
            if current_revision == expected_revision and candidate != old_hash:
                summary['tested_candidate_hash'] = candidate
            application = json.loads(kube('get', 'application', 'release-demo-dev', '-n', 'argocd', '-o', 'json'))
            synced = application.get('status', {}).get('sync', {})
            runs = [r for r in resource('analysisrun').get('items', []) if r['metadata'].get('labels', {}).get('rollouts-pod-template-hash') == candidate]
            phases = [r.get('status', {}).get('phase') for r in runs]
            for run in runs:
                observed_runs[run['metadata']['name']] = run
            (folder / 'analysis-observed.json').write_text(json.dumps({'items': list(observed_runs.values())}, indent=2))
            if (args.scenario in ('telemetry-outage', 'shared-telemetry-outage') and not telemetry_started
                    and current_revision == expected_revision and candidate != old_hash
                    and any(r['metadata'].get('labels', {}).get('rollout-type') == 'PrePromotion'
                            and r.get('status', {}).get('phase') == 'Running' for r in runs)):
                telemetry.start()
                telemetry_started = True
            recovery_path = Path('/var/lib/release-lab/recovery/status.json')
            recovery = json.loads(recovery_path.read_text()) if recovery_path.exists() else {}
            controlled = recovery.get('deployment_commit') == evidence['environment_commit']
            if (args.scenario == 'telemetry-outage' and telemetry_started and controlled
                    and recovery.get('phase') == 'recovering'):
                telemetry.restore()
            if controlled and recovery.get('phase') in ('healthy', 'recovered', 'recovery_failed'):
                (folder / 'recovery.json').write_text(json.dumps(recovery, indent=2))
                summary['release_control'] = recovery
            if controlled and recovery.get('phase') == 'recovery_failed':
                raise RuntimeError('Recovery failed; inspect recovery-status before retrying')
            if (controlled and recovery.get('phase') == 'recovered'
                    and synced.get('status') == 'Synced' and synced.get('revision') == recovery.get('head')):
                (folder / 'recovery.json').write_text(json.dumps(recovery, indent=2))
                summary['recovery'] = recovery
                summary['verdict'] = ('post-promotion-recovered-through-gitops' if args.scenario == 'post-error'
                                      else 'candidate-rejected-and-restored-through-gitops')
                break
            observed = str(state.get('observedGeneration')) == str(rollout['metadata']['generation'])
            if (observed and current_revision == expected_revision and candidate != old_hash
                    and synced.get('revision') == (recovery.get('head') if controlled and recovery.get('phase') == 'healthy'
                                                   else evidence['environment_commit']) and synced.get('status') == 'Synced'):
                if (args.scenario == 'healthy' and state.get('phase') == 'Healthy' and 'Successful' in phases
                        and service_hash() == candidate and (not recovery_path.exists() or (controlled and recovery.get('phase') == 'healthy'))):
                    summary['verdict'] = 'candidate-promoted-through-gitops'
                elif args.scenario in ('error', 'latency') and 'Failed' in phases and state.get('abort'):
                    summary['verdict'] = 'candidate-rejected-through-gitops'
                elif args.scenario == 'startup' and state.get('abort'):
                    summary['verdict'] = 'readiness-aborted-through-gitops'
                if 'verdict' in summary:
                    if recovery_path.exists() and recovery.get('phase') not in ('healthy', 'recovered'):
                        summary.pop('verdict')
                        time.sleep(3)
                        continue
                    if args.scenario != 'healthy' and service_hash() != old_hash:
                        raise AssertionError('Faulty candidate changed stable service')
                    break
            time.sleep(3)
        else:
            raise TimeoutError('Expected GitOps/controller outcome was not observed')
        final = sample(root + 'demo-stable:80/proxy/')
        if final.get('status') != 200 or final.get('response', {}).get('mode') != 'healthy':
            raise AssertionError('Stable response unhealthy')
        if args.scenario == 'healthy' and final['response']['revision'] != expected_revision:
            raise AssertionError('Serving revision does not match Jenkins artifact')
        if args.scenario != 'healthy' and service_hash() != old_hash:
            raise AssertionError('Fault trial did not preserve the previous stable service')
        if args.scenario == 'telemetry-outage' and not telemetry_started:
            raise AssertionError('Telemetry outage was never injected')
        if args.scenario in ('latency', 'startup', 'no-traffic', 'telemetry-outage'):
            failure_folder = ROOT / 'output' / ('recovery-' + evidence['environment_commit'] + '-1')
            failed_rollout = json.loads((failure_folder / 'rollout.json').read_text()) if (failure_folder / 'rollout.json').exists() else rollout
            captured = json.loads((failure_folder / 'analysisrun.json').read_text()).get('items', []) if (failure_folder / 'analysisrun.json').exists() else []
            failed_runs = [r for r in [*observed_runs.values(), *captured]
                           if r['metadata'].get('labels', {}).get('rollouts-pod-template-hash') == summary.get('tested_candidate_hash')]
            validate_fault_evidence(args.scenario, failed_runs, failed_rollout)
        if args.scenario == 'post-error':
            if (summary.get('recovery', {}).get('failure_stage') != 'post-promotion'
                    or service_hash() != old_hash):
                raise AssertionError('Post-promotion failure did not restore the previous healthy service')
        summary.update(final_response=final, serving_hash=service_hash())
    except BaseException as exc:
        summary.update(verdict='trial-failed', error=str(exc))
        raise
    finally:
        stop.set()
        for worker in threads:
            worker.join(timeout=5)
        try:
            telemetry.restore()
        except Exception as exc:
            summary.update(verdict='trial-failed', error='Monitoring restoration failed: ' + str(exc))
        for kind in ('rollout', 'analysisrun', 'service', 'pod'):
            try:
                (folder / (kind + '.json')).write_text(kube('get', kind, '-n', 'demo-dev', '-o', 'json'))
            except Exception as exc:
                summary['capture_' + kind + '_error'] = str(exc)
        try:
            (folder / 'application.json').write_text(kube('get', 'application', 'release-demo-dev', '-n', 'argocd', '-o', 'json'))
        except Exception as exc:
            summary['capture_application_error'] = str(exc)
        proxy.terminate()
        try:
            proxy.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proxy.kill()
            proxy.wait()
        log.close()
        rows = [json.loads(line) for line in (folder / 'stable.jsonl').read_text().splitlines()] if (folder / 'stable.jsonl').exists() else []
        summary.update(stable_requests=len(rows), stable_non_200=sum(row.get('status') != 200 for row in rows),
                       finished=datetime.now(timezone.utc).isoformat())
        # Apply availability assertions before immutable archival, so an experiment
        # that fails its last check can never retain a successful verdict.
        if summary.get('verdict') != 'trial-failed':
            try:
                validate_availability(args.scenario, rows, expected_revision)
            except AssertionError as exc:
                summary.update(verdict='trial-failed', error=str(exc))
        if args.scenario == 'post-error':
            failed = [i for i, row in enumerate(rows) if row.get('status') != 200]
            if failed:
                restored = next((row for row in rows[failed[-1] + 1:] if row.get('status') == 200), None)
                summary['first_failed_response'] = rows[failed[0]]['timestamp']
                summary['last_failed_response'] = rows[failed[-1]]['timestamp']
                if restored:
                    summary['first_restored_response'] = restored['timestamp']
                    summary['observed_failure_window_seconds'] = round((datetime.fromisoformat(restored['timestamp'])
                        - datetime.fromisoformat(rows[failed[0]]['timestamp'])).total_seconds(), 3)
        (folder / 'summary.json').write_text(json.dumps(summary, indent=2))
        from scripts.evidence import finalize_archive
        finalize_archive(folder)
    print(json.dumps(summary), flush=True)
    if summary.get('verdict') == 'trial-failed':
        raise AssertionError(summary['error'])


if __name__ == '__main__':
    main()
