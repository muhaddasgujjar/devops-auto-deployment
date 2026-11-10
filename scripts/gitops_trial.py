"""Observe a local Jenkins -> environment Git -> Argo CD -> Rollouts trial."""
import argparse
import base64
import hashlib
import http.cookiejar
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError, URLError

from scripts.live_trial import kube, resource, sample, service_hash
from scripts.render_release import ROOT
from scripts.runtime_decision import decision
from scripts.observation import stable_sample_quality


def queued_build_number(item):
    return (item.get('executable') or {}).get('number')


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

    def wait_ready(self, timeout=180):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = self.json('crumbIssuer/api/json')
                if result.get('crumbRequestField') and result.get('crumb'):
                    return
            except HTTPError as error:
                if error.code not in (404, 502, 503, 504):
                    raise
            except (URLError, OSError, ValueError):
                pass
            time.sleep(2)
        raise TimeoutError('Authenticated Jenkins/CSRF endpoint did not become ready')

    def build(self, mode, job, fail_tests=False):
        self.wait_ready()
        crumb = self.json('crumbIssuer/api/json')
        parameters = {'DEMO_MODE': mode}
        if job == 'release-merged':
            parameters['FAIL_TEST_GATE'] = 'true' if fail_tests else 'false'
        _, headers = self.request(f'job/{job}/buildWithParameters', urlencode(parameters).encode(),
                                  {crumb['crumbRequestField']: crumb['crumb'], 'Content-Type': 'application/x-www-form-urlencoded'})
        return headers['Location']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', choices=['healthy', 'error', 'latency', 'startup', 'no-traffic', 'telemetry-outage'])
    parser.add_argument('--job', choices=['release-local', 'release-main', 'release-merged'], default='release-merged')
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
    if not old_hash:
        raise RuntimeError('Establish a verified stable revision before runtime trials')
    summary = {'scenario': args.scenario, 'previous_stable_hash': old_hash, 'started': datetime.now(timezone.utc).isoformat()}
    summary['observer_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    summary['observer_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                  for name in ('scripts/gitops_trial.py', 'scripts/runtime_decision.py', 'scripts/observation.py')}
    stop, threads = threading.Event(), []
    monitoring = None
    log = (folder / 'proxy.log').open('w')
    proxy = subprocess.Popen(['kubectl', 'proxy', '--address=127.0.0.1', '--port=18001'], stdout=log, stderr=subprocess.STDOUT)
    root = 'http://127.0.0.1:18001/api/v1/namespaces/demo-dev/services/'

    def traffic(service, filename):
        with (folder / filename).open('a') as stream:
            while not stop.is_set():
                started_monotonic = time.monotonic()
                row = sample(root + service + ':80/proxy/')
                row['client_monotonic_seconds'] = started_monotonic
                stream.write(json.dumps(row) + '\n')
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
        baseline = sample(root + 'demo-stable:80/proxy/')
        if baseline.get('status') != 200 or baseline.get('response', {}).get('mode') != 'healthy':
            raise RuntimeError('Stable baseline must serve a healthy revision')
        summary['baseline_response'] = baseline
        jenkins = Jenkins()
        mode = args.scenario if args.scenario in ('error', 'latency', 'startup') else 'healthy'
        queue = jenkins.build(mode, args.job)
        deadline = time.monotonic() + 1200
        number = None
        while time.monotonic() < deadline:
            queued = jenkins.json(queue + 'api/json')
            if queued.get('cancelled'):
                raise RuntimeError('Jenkins queue item cancelled')
            number = queued_build_number(queued)
            if number:
                break
            time.sleep(2)
        if not number:
            raise TimeoutError('No executor became available')
        summary['jenkins_build'] = number
        print(f'Jenkins build {number}; waiting for scan and environment commit', flush=True)
        while time.monotonic() < deadline:
            build = jenkins.json(f'job/{args.job}/{number}/api/json')
            if not build['building']:
                (folder / 'jenkins-build.json').write_text(json.dumps(build, indent=2))
                (folder / 'jenkins-console.txt').write_bytes(jenkins.request(f'job/{args.job}/{number}/consoleText')[0])
                if build['result'] != 'SUCCESS':
                    raise RuntimeError(f'Jenkins result: {build["result"]}; inspect retained console')
                break
            time.sleep(3)
        else:
            raise TimeoutError('Jenkins build exceeded observation deadline')
        evidence = jenkins.json(f'job/{args.job}/{number}/artifact/output/environment-commit.json')
        summary.update(evidence)
        files = ['scan.json', 'sbom.json', 'environment-commit.json']
        if args.job == 'release-merged':
            files += ['source.json', 'image-inspect.json']
        for filename in files:
            (folder / filename).write_bytes(jenkins.request(f'job/{args.job}/{number}/artifact/output/{filename}')[0])
        print('Build passed; observing Argo reconciliation and candidate analysis', flush=True)
        summary['observation_started'] = datetime.now(timezone.utc).isoformat()
        observation_monotonic = time.monotonic()
        summary['availability_boundary'] = 'After CI completion; excludes build/scan and Git publication interval'
        start_traffic('demo-stable', 'stable.jsonl')
        expected_revision = evidence['source_commit'] + '-' + evidence['release_id']
        if args.scenario == 'telemetry-outage':
            obj = json.loads(kube('get', 'deployment', 'prometheus', '-n', 'monitoring', '-o', 'json'))
            monitoring = {'uid': obj['metadata']['uid'], 'replicas': obj['spec'].get('replicas', 1)}
            if monitoring['replicas'] != 1:
                raise RuntimeError('Telemetry injection requires the existing one-replica lab monitor')
            patch = [{'op': 'test', 'path': '/metadata/uid', 'value': monitoring['uid']},
                     {'op': 'test', 'path': '/spec/replicas', 'value': monitoring['replicas']},
                     {'op': 'replace', 'path': '/spec/replicas', 'value': 0}]
            kube('patch', 'deployment', 'prometheus', '-n', 'monitoring', '--type=json', '-p', json.dumps(patch))
            summary['telemetry_injection'] = monitoring
            deadline = time.monotonic() + 60
            while json.loads(kube('get', 'pods', '-l', 'app=prometheus', '-n', 'monitoring', '-o', 'json'))['items']:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Prometheus did not stop within the injection window')
                time.sleep(1)
        if args.scenario not in ('startup', 'no-traffic'):
            for i in range(4):
                start_traffic('demo-preview', f'preview-{i}.jsonl')
        # Refresh only GitOps discovery; CI never applies runtime manifests.
        kube('annotate', 'application', 'release-demo-dev', '-n', 'argocd',
             'argocd.argoproj.io/refresh=hard', '--overwrite')
        deadline = time.monotonic() + 420
        while time.monotonic() < deadline:
            rollout = resource('rollout', 'release-demo')
            application = json.loads(kube('get', 'application', 'release-demo-dev', '-n', 'argocd', '-o', 'json'))
            verdict = decision(args.scenario, expected_revision, evidence['environment_commit'], old_hash,
                               rollout, application, resource('analysisrun').get('items', []), service_hash())
            if verdict:
                summary['verdict'] = verdict
                summary['decision_observed'] = datetime.now(timezone.utc).isoformat()
                summary['client_monotonic_observation_seconds'] = round(time.monotonic() - observation_monotonic, 3)
                break
            time.sleep(3)
        else:
            raise TimeoutError('Expected GitOps/controller outcome was not observed')
        final = sample(root + 'demo-stable:80/proxy/')
        if final.get('status') != 200 or final.get('response', {}).get('mode') != 'healthy':
            raise AssertionError('Stable response unhealthy')
        if args.scenario == 'healthy' and final['response']['revision'] != expected_revision:
            raise AssertionError('Serving revision does not match Jenkins artifact')
        if args.scenario != 'healthy' and final['response']['revision'] != baseline['response']['revision']:
            raise AssertionError('Rejected candidate changed the stable serving revision')
        summary.update(final_response=final, serving_hash=service_hash())
    except Exception as exc:
        summary.update(verdict='trial-failed', error=str(exc))
        raise
    finally:
        stop.set()
        for worker in threads:
            worker.join(timeout=5)
        for kind in ('rollout', 'analysisrun', 'service', 'pod'):
            try:
                (folder / (kind + '.json')).write_text(kube('get', kind, '-n', 'demo-dev', '-o', 'json'))
            except Exception as exc:
                summary['capture_' + kind + '_error'] = str(exc)
        try:
            (folder / 'application.json').write_text(kube('get', 'application', 'release-demo-dev', '-n', 'argocd', '-o', 'json'))
        except Exception as exc:
            summary['capture_application_error'] = str(exc)
        if monitoring is not None:
            try:
                obj = json.loads(kube('get', 'deployment', 'prometheus', '-n', 'monitoring', '-o', 'json'))
                if obj['metadata']['uid'] != monitoring['uid']:
                    raise RuntimeError('Monitor identity changed; refusing restoration')
                if obj['spec'].get('replicas', 1) == 0:
                    patch = [{'op': 'test', 'path': '/metadata/uid', 'value': monitoring['uid']},
                             {'op': 'test', 'path': '/spec/replicas', 'value': 0},
                             {'op': 'replace', 'path': '/spec/replicas', 'value': monitoring['replicas']}]
                    kube('patch', 'deployment', 'prometheus', '-n', 'monitoring', '--type=json', '-p', json.dumps(patch))
                elif obj['spec'].get('replicas') != monitoring['replicas']:
                    raise RuntimeError('Monitor replicas changed externally; refusing overwrite')
                deadline = time.monotonic() + 120
                while True:
                    restored = json.loads(kube('get', 'deployment', 'prometheus', '-n', 'monitoring', '-o', 'json'))
                    status = restored.get('status', {})
                    if (restored['metadata']['uid'] == monitoring['uid'] and
                            status.get('observedGeneration') == restored['metadata']['generation'] and
                            status.get('availableReplicas', 0) >= monitoring['replicas']):
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Prometheus availability did not recover')
                    time.sleep(2)
                summary['telemetry_restored'] = True
            except Exception as exc:
                summary['telemetry_restore_error'] = str(exc)
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
        try:
            summary['sampling_quality'] = stable_sample_quality(rows)
            summary['sampling_gate_passed'] = True
        except ValueError as exc:
            summary['sampling_gate_passed'] = False
            summary['sampling_error'] = str(exc)
        summary['availability_gate_passed'] = summary['sampling_gate_passed'] and summary['stable_non_200'] == 0
        summary['acceptance_passed'] = (summary.get('verdict') not in (None, 'trial-failed')
                                        and summary['availability_gate_passed']
                                        and not summary.get('telemetry_restore_error'))
        (folder / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
    if not summary['acceptance_passed']:
        raise AssertionError('Trial acceptance failed; inspect retained evidence')


if __name__ == '__main__':
    main()
