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
    parser.add_argument('scenario', choices=['healthy', 'error', 'latency', 'startup'])
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
    stop, threads = threading.Event(), []
    log = (folder / 'proxy.log').open('w')
    proxy = subprocess.Popen(['kubectl', 'proxy', '--address=127.0.0.1', '--port=18001'], stdout=log, stderr=subprocess.STDOUT)
    root = 'http://127.0.0.1:18001/api/v1/namespaces/demo-dev/services/'

    def traffic(service, filename):
        with (folder / filename).open('a') as stream:
            while not stop.is_set():
                stream.write(json.dumps(sample(root + service + ':80/proxy/')) + '\n')
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
            queue = jenkins.build(args.scenario, args.job)
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
        for i in range(4):
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
        deadline = time.monotonic() + 420
        while time.monotonic() < deadline:
            rollout = resource('rollout', 'release-demo')
            env = rollout['spec']['template']['spec']['containers'][0]['env']
            current_revision = next(e['value'] for e in env if e['name'] == 'APP_REVISION')
            state = rollout.get('status', {})
            candidate = state.get('currentPodHash')
            application = json.loads(kube('get', 'application', 'release-demo-dev', '-n', 'argocd', '-o', 'json'))
            synced = application.get('status', {}).get('sync', {})
            runs = [r for r in resource('analysisrun').get('items', []) if r['metadata'].get('labels', {}).get('rollouts-pod-template-hash') == candidate]
            phases = [r.get('status', {}).get('phase') for r in runs]
            observed = str(state.get('observedGeneration')) == str(rollout['metadata']['generation'])
            if (observed and current_revision == expected_revision and candidate != old_hash
                    and synced.get('revision') == evidence['environment_commit'] and synced.get('status') == 'Synced'):
                if args.scenario == 'healthy' and 'Successful' in phases and service_hash() == candidate:
                    summary['verdict'] = 'candidate-promoted-through-gitops'
                elif args.scenario in ('error', 'latency') and 'Failed' in phases and state.get('abort'):
                    summary['verdict'] = 'candidate-rejected-through-gitops'
                elif args.scenario == 'startup' and state.get('abort'):
                    summary['verdict'] = 'readiness-aborted-through-gitops'
                if 'verdict' in summary:
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
        (folder / 'summary.json').write_text(json.dumps(summary, indent=2))
        from scripts.evidence import finalize_archive
        finalize_archive(folder)
    print(json.dumps(summary), flush=True)
    if summary['stable_non_200']:
        raise AssertionError('Stable failures were observed; inspect retained evidence')


if __name__ == '__main__':
    main()
