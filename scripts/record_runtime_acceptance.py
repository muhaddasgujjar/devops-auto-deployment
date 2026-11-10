"""Cross-check six serialized GitOps trials and retain a portable evidence index."""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from scripts.record_ci_acceptance import require
from scripts.observation import stable_sample_quality
from scripts.render_release import ROOT
from scripts.runtime_decision import decision

SCENARIOS = {'error', 'latency', 'startup', 'no-traffic', 'telemetry-outage', 'healthy'}


def verify(folder):
    def read(name):
        return json.loads((folder / name).read_text())
    summary, build = read('summary.json'), read('jenkins-build.json')
    source, scan, images = read('source.json'), read('scan.json'), read('image-inspect.json')
    environment, app = read('environment-commit.json'), read('application.json')
    rollout = next(x for x in read('rollout.json')['items'] if x['metadata']['name'] == 'release-demo')
    analyses = read('analysisrun.json')['items']
    stable = next(x for x in read('service.json')['items'] if x['metadata']['name'] == 'demo-stable')
    stable_hash = stable['spec']['selector']['rollouts-pod-template-hash']
    scenario, sha = summary['scenario'], summary['source_commit']
    revision = sha + '-' + summary['release_id']
    mode = scenario if scenario in ('error', 'latency', 'startup') else 'healthy'
    require('DEMO_MODE=' + mode in images[0]['Config']['Env'] and
            'APP_REVISION=' + revision in images[0]['Config']['Env'], 'Image mode/revision mismatch')
    require(summary.get('acceptance_passed') is True, 'Observer did not accept this trial')
    require(build['result'] == 'SUCCESS' and build['number'] == summary['jenkins_build'], 'CI identity mismatch')
    counts = re.findall(r'Ran (\d+) tests?', (folder / 'jenkins-console.txt').read_text())
    require(counts and int(counts[-1]) > 0, 'No completed CI test suite in the console')
    require(source['source_commit'] == sha == environment['source_commit'], 'Source provenance mismatch')
    require(source['negative_test_requested'] is False, 'Unexpected negative CI gate')
    require(scan['Metadata']['ImageID'] == images[0]['Id'], 'Scan/image identity mismatch')
    require(summary['image'] in images[0]['RepoDigests'], 'Published registry digest mismatch')
    require(scan.get('Results') and scan['Metadata'].get('OS'), 'No supported scan results')
    require(not any(v['Severity'] in ('HIGH', 'CRITICAL') for result in scan['Results']
                    for v in result.get('Vulnerabilities', [])), 'Unresolved HIGH/CRITICAL findings')
    sbom = read('sbom.json')
    require(sbom.get('bomFormat') == 'CycloneDX' and sbom.get('components'), 'Missing SBOM')
    require(environment['environment_commit'] == summary['environment_commit'], 'Environment artifact mismatch')
    require(rollout['spec']['template']['spec']['containers'][0]['image'] == summary['image'], 'Runtime image mismatch')
    verdict = decision(scenario, revision, environment['environment_commit'], summary['previous_stable_hash'],
                       rollout, app, analyses, stable_hash)
    require(verdict and verdict == summary['verdict'], 'Snapshot/controller decision mismatch')
    rows = [json.loads(line) for line in (folder / 'stable.jsonl').read_text().splitlines()]
    require(rows and len(rows) == summary['stable_requests'] and all(x.get('status') == 200 for x in rows)
            and summary['stable_non_200'] == 0, 'Availability evidence mismatch')
    quality = stable_sample_quality(rows)
    baseline, final = summary['baseline_response'], summary['final_response']
    require(baseline['status'] == final['status'] == 200 and
            baseline['response']['mode'] == final['response']['mode'] == 'healthy', 'Unhealthy stable response')
    expected_serving = revision if scenario == 'healthy' else baseline['response']['revision']
    require(final['response']['revision'] == expected_serving and summary['serving_hash'] == stable_hash,
            'Stable serving identity mismatch')
    require(all(x.get('response', {}).get('mode') == 'healthy' and
                x.get('response', {}).get('revision') in {baseline['response']['revision'], expected_serving}
                for x in rows), 'Unexpected stable response during observation')
    if scenario == 'telemetry-outage':
        require(summary.get('telemetry_restored') is True and not summary.get('telemetry_restore_error'),
                'Monitoring restoration was not verified')
    if scenario in ('startup', 'no-traffic'):
        require(not list(folder.glob('preview-*.jsonl')), 'Unexpected preview traffic injection')
    candidate = rollout['status']['currentPodHash']
    current_analyses = [{'name': x['metadata']['name'], 'phase': x.get('status', {}).get('phase'),
                         'metrics': x.get('status', {}).get('metricResults', [])}
                        for x in analyses
                        if x['metadata'].get('labels', {}).get('rollouts-pod-template-hash') == candidate]
    metrics = [metric for analysis in current_analyses for metric in analysis['metrics']]
    if scenario in ('error', 'latency'):
        metric_name, threshold = ('candidate-error-ratio', 0.05) if scenario == 'error' else ('candidate-p95-latency', 0.5)
        measurements = [m for metric in metrics if metric['name'] == metric_name
                        for m in metric.get('measurements', []) if m.get('phase') == 'Failed']
        require(measurements and any(json.loads(m['value'])[0] > threshold for m in measurements),
                'No failed measurement for the intended fault threshold')
    if scenario == 'no-traffic':
        require(metrics and all(metric.get('phase') == 'Inconclusive' for metric in metrics) and
                all(m.get('value') == '[]' for metric in metrics for m in metric.get('measurements', [])),
                'Missing-traffic results were not empty/inconclusive')
    if scenario == 'telemetry-outage':
        require(any(m.get('phase') == 'Error' and m.get('message')
                    for metric in metrics for m in metric.get('measurements', [])), 'No telemetry transport error')
    if scenario == 'startup':
        # This pinned Rollouts controller records deadline aborts as RolloutAborted.
        timeout_message = f'ReplicaSet "release-demo-{candidate}" has timed out progressing.'
        require(rollout['spec'].get('progressDeadlineAbort') is True and
                any(x.get('type') == 'Progressing' and x.get('status') == 'False' and
                    x.get('reason') == 'RolloutAborted' and timeout_message in x.get('message', '')
                    for x in rollout['status'].get('conditions', [])), 'No candidate-bound progress-deadline abort')
        pods = [x for x in read('pod.json')['items']
                if x['metadata'].get('labels', {}).get('rollouts-pod-template-hash') == candidate]
        require(len(pods) == rollout['spec']['replicas'] and all(
            any(c['type'] == 'Ready' and c['status'] == 'False' for c in p['status'].get('conditions', []))
            for p in pods), 'Missing unready candidate pod evidence')
    artifacts = ['summary.json', 'jenkins-build.json', 'source.json', 'scan.json', 'sbom.json',
                 'image-inspect.json', 'environment-commit.json', 'rollout.json', 'analysisrun.json',
                 'application.json', 'service.json', 'pod.json', 'stable.jsonl', 'jenkins-console.txt']
    artifacts.extend(path.name for path in sorted(folder.glob('preview-*.jsonl')))
    elapsed = (datetime.fromisoformat(summary['decision_observed']) -
               datetime.fromisoformat(summary['observation_started'])).total_seconds()
    return {**summary, 'passed': True, 'ci_duration_ms': build['duration'], 'candidate_hash': candidate,
            'tests_in_release_snapshot': int(counts[-1]),
            'analyses': current_analyses, 'reported_high_critical': 0,
            'wall_observation_to_decision_seconds': round(elapsed, 3),
            'sampling_quality': quality,
            'raw_trial': folder.relative_to(ROOT).as_posix(),
            'artifact_sha256': {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in artifacts}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trials', type=Path, nargs='+', required=True)
    parser.add_argument('--health', type=Path, required=True)
    args = parser.parse_args()
    folders = [x.resolve() for x in args.trials]
    require(all(x.is_relative_to((ROOT / 'output').resolve()) for x in folders), 'Only local trial folders supported')
    trials = [verify(x) for x in folders]
    require(len(trials) == len(SCENARIOS) and {x['scenario'] for x in trials} == SCENARIOS,
            'Select exactly one accepted trial for each of the six scenarios')
    trials.sort(key=lambda x: x['started'])
    require(trials[-1]['scenario'] == 'healthy', 'Healthy restoration must be last')
    require(all(a['finished'] < b['started'] for a, b in zip(trials, trials[1:])), 'Trials overlap')
    require(len({x['source_commit'] for x in trials}) == 1, 'Trials must exercise the same application source')
    health = json.loads(args.health.read_text())
    required = {'nodes', 'argo-rollouts', 'prometheus', 'stable_service', 'serving_revision_telemetry', 'gitops_sync'}
    require(health.get('ok') is True and required.issubset(health['checks']) and
            all(x['ok'] for x in health['checks'].values()), 'Final health failed')
    require(health['checked_at'] > trials[-1]['finished'], 'Final health predates restoration')
    require(health['release']['phase'] == 'Healthy' and
            health['release']['serving_hash'] == trials[-1]['serving_hash'] and
            health['release']['response']['revision'] == trials[-1]['final_response']['response']['revision'],
            'Final health does not describe the final healthy trial')
    history = []
    for path in sorted((ROOT / 'output').glob('gitops-*/summary.json')):
        attempt = json.loads(path.read_text())
        if attempt.get('started', '') >= trials[0]['started']:
            try:
                verify(path.parent)
                crosscheck = {'crosscheck_passed': True}
            except (ValueError, KeyError, OSError, StopIteration) as exc:
                crosscheck = {'crosscheck_passed': False, 'crosscheck_error': str(exc)}
            history.append({'raw_trial': path.parent.relative_to(ROOT).as_posix(), **attempt, **crosscheck})
    report = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': True,
              'scope': 'Local manual CI/GitOps pre-promotion rejection and final healthy restoration',
              'trials': trials, 'attempt_history': history, 'final_health': health,
              'final_health_sha256': hashlib.sha256(args.health.read_bytes()).hexdigest(),
              'limitations': ['One serial observation per accepted case; no reliability distribution or production SLO',
                              'Stable HTTP measurement uses the Kubernetes API proxy after CI completes',
                              'Observer requests Argo hard refresh; CI has no cluster credentials',
                              'Missing traffic/telemetry block promotion; they do not prove that the candidate is bad',
                              'Post-promotion detection and Git-authoritative recovery are not implemented',
                              'Application source is the recorded CI snapshot, separate from the newer observer source']}
    report['limitations'].append('Small wall-clock corrections are counted per trial; wall elapsed times are approximate, not benchmark timings')
    target = ROOT / 'docs/evidence/runtime-failure-validation.json'
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'trials': len(trials), 'output': str(target)}))


if __name__ == '__main__':
    main()
