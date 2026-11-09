"""Cross-check a completed local trial and export sanitized acceptance evidence."""
import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from scripts.gitops_trial import Jenkins
from scripts.render_release import ROOT


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', type=Path, required=True)
    args = parser.parse_args()
    target = ROOT / 'docs/evidence/ci-gitops-acceptance.json'
    target.unlink(missing_ok=True)
    folder = args.trial.resolve()
    require(folder.is_relative_to((ROOT / 'output').resolve()), 'Use a local output trial directory')
    def read(name):
        return json.loads((folder / name).read_text())
    summary = read('summary.json')
    build = read('jenkins-build.json')
    number = summary['jenkins_build']
    client = Jenkins()
    for name in ('source.json', 'image-inspect.json'):
        (folder / name).write_bytes(client.request(f'job/release-merged/{number}/artifact/output/{name}')[0])
    source, images, scan = read('source.json'), read('image-inspect.json'), read('scan.json')
    sbom, env = read('sbom.json'), read('environment-commit.json')
    app, rollout, analyses, services = read('application.json'), read('rollout.json'), read('analysisrun.json'), read('service.json')
    if 'items' in rollout:
        rollout = next((x for x in rollout['items'] if x['metadata']['name'] == 'release-demo'), {})
    require(bool(rollout.get('spec')), 'Missing target rollout snapshot')
    negative = json.loads((ROOT / 'docs/evidence/ci-negative-gate.json').read_text())
    sha = summary['source_commit']
    expected_revision = sha + '-' + summary['release_id']
    require(build['result'] == 'SUCCESS' and build['number'] == number, 'CI result mismatch')
    require(summary['verdict'] == 'candidate-promoted-through-gitops', 'Candidate was not promoted')
    require(summary['stable_requests'] > 0 and summary['stable_non_200'] == 0, 'Availability gate failed or unmeasured')
    require(source['source_commit'] == sha == env['source_commit'], 'Source provenance mismatch')
    require(source['negative_test_requested'] is False, 'Positive trial requested a negative gate')
    require(negative['passed'] and negative['source']['source_commit'] == sha, 'No passing negative proof for this source')
    require(negative['environment_before'] == negative['environment_after'], 'Negative trial changed desired state')
    require(scan['Metadata']['ImageID'] == images[0]['Id'], 'Scanned image differs from published image')
    require(summary['image'] in images[0]['RepoDigests'], 'Registry digest mismatch')
    require(scan.get('Results') and scan['Metadata'].get('OS'), 'Missing supported OS scan evidence')
    blocked = [v for result in scan['Results'] for v in result.get('Vulnerabilities', [])
               if v.get('Severity') in ('HIGH', 'CRITICAL')]
    require(not blocked, 'HIGH/CRITICAL findings remain')
    require(sbom.get('bomFormat') == 'CycloneDX' and sbom.get('components'), 'Missing SBOM components')
    require(summary['environment_commit'] == env['environment_commit'] == app['status']['sync']['revision'], 'Environment/sync mismatch')
    require(app['status']['sync']['status'] == 'Synced', 'Application is not synced')
    require(rollout['spec']['template']['spec']['containers'][0]['image'] == summary['image'], 'Runtime image mismatch')
    serving = summary['serving_hash']
    require(any(x.get('status', {}).get('phase') == 'Successful' and
                x['metadata'].get('labels', {}).get('rollouts-pod-template-hash') == serving
                for x in analyses['items']), 'No successful analysis for serving revision')
    require(any(x['metadata']['name'] == 'demo-stable' and
                x['spec']['selector'].get('rollouts-pod-template-hash') == serving
                for x in services['items']), 'Stable service selector mismatch')
    final = summary['final_response']
    require(final['status'] == 200 and final['response']['revision'] == expected_revision and
            final['response']['mode'] == 'healthy', 'Served revision mismatch')
    console = (folder / 'jenkins-console.txt').read_text()
    counts = re.findall(r'Ran (\d+) tests?', console)
    require(bool(counts), 'No completed unittest count in build console')
    versions = json.loads(subprocess.check_output(['git', '-C', str(ROOT), 'show', sha + ':versions.json'], text=True))
    require('Version: ' + versions['trivy'] in console, 'Pinned scanner version not observed')
    report = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': True,
              'trigger': source['trigger'], 'job': 'release-merged', 'build': number,
              'source_commit': sha, 'tests_in_release_snapshot': int(counts[-1]),
              'ci_duration_ms': build['duration'], 'application_base': versions['python_image'],
              'scanner_version': versions['trivy'], 'reported_high_critical': len(blocked),
              'image_config_id': images[0]['Id'], 'image': summary['image'],
              'environment_commit': env['environment_commit'], 'serving_revision': expected_revision,
              'serving_hash': serving, 'controller_verdict': summary['verdict'],
              'stable_requests': summary['stable_requests'], 'stable_non_200': 0,
              'availability_boundary': summary['availability_boundary'],
              'negative_gate_build': negative['build'], 'negative_environment_unchanged': True,
              'raw_trial': str(folder.relative_to(ROOT)),
              'artifact_sha256': {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                                  for name in ('source.json', 'scan.json', 'sbom.json', 'image-inspect.json', 'summary.json')},
              'limitations': ['One passing local manual trial, not an external webhook or production SLO',
                              'Availability excludes CI build, scan and environment publication',
                              'Earlier failed availability/scan/transport attempts are retained separately']}
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
