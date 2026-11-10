"""Independently correlate backend test gates, scanner identity and registry bytes."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.render_release import ROOT


def require(value, message):
    if not value:
        raise ValueError(message)


def manifest(reference):
    request = Request('http://127.0.0.1:5001/v2/release-state/manifests/' + reference,
                      headers={'Accept': ','.join(['application/vnd.oci.image.index.v1+json',
                          'application/vnd.oci.image.manifest.v1+json', 'application/vnd.docker.distribution.manifest.v2+json'])})
    with urlopen(request, timeout=10) as response:
        raw = response.read()
        digest = response.headers['Docker-Content-Digest']
    require(digest == 'sha256:' + hashlib.sha256(raw).hexdigest(), 'Registry manifest content hash mismatch')
    return json.loads(raw), digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--positive', type=Path, required=True)
    parser.add_argument('--negative', type=Path, required=True)
    args = parser.parse_args()
    def read(folder, name):
        return json.loads((folder / name).read_text())
    positive, negative = read(args.positive, 'result.json'), read(args.negative, 'result.json')
    tests, failed_tests = read(args.positive, 'tests.json'), read(args.negative, 'tests.json')
    build, failed_build = read(args.positive, 'jenkins-build.json'), read(args.negative, 'jenkins-build.json')
    require(positive['passed'] and positive['published'] and build['result'] == 'SUCCESS', 'Positive build failed')
    require(not negative['published'] and failed_build['result'] == 'FAILURE' and negative['negative_test'], 'Negative gate did not block publication')
    require(tests['passed'] and failed_tests['failures'] == 1 and not failed_tests['errors'] and
            failed_tests['tests_run'] == tests['tests_run'] + 1, 'Negative gate is not exactly one intentional failed test')
    require(positive['source_commit'] == negative['source_commit'], 'Gate proofs use different source commits')
    require(positive['ephemeral_resources_removed'] and negative['ephemeral_resources_removed'], 'CI cleanup failed')
    require(not (args.negative / 'scan.json').exists() and not (args.negative / 'sbom.json').exists(), 'Negative tests did not block later stages')
    try:
        manifest(negative['image_tag'].rsplit(':', 1)[1])
    except HTTPError as error:
        require(error.code == 404, 'Could not verify negative registry tag absence')
    else:
        raise ValueError('Negative image tag was published')
    scan, sbom = read(args.positive, 'scan.json'), read(args.positive, 'sbom.json')
    inspected = json.loads(subprocess.check_output(['docker', 'image', 'inspect', positive['image']], text=True))[0]
    require(scan['Metadata']['ImageID'] == inspected['Id'] == positive['image_config_id'], 'Scanned image identity differs')
    require(positive['image'] in inspected['RepoDigests'], 'Published digest differs')
    require(inspected['Config']['User'] == '10001:10001' and
            inspected['Config']['Labels']['org.opencontainers.image.revision'] == positive['source_commit'], 'Runtime UID or source label mismatch')
    classes = {r.get('Class') for r in scan.get('Results', [])}
    require({'os-pkgs', 'lang-pkgs'}.issubset(classes), 'OS/Python scan coverage missing')
    require(not any(v.get('Severity') in ('HIGH', 'CRITICAL') for r in scan['Results']
                    for v in r.get('Vulnerabilities', [])), 'HIGH/CRITICAL findings remain')
    require(sbom.get('bomFormat') == 'CycloneDX' and sbom.get('components'), 'SBOM is missing')
    frontend_audit = read(args.positive, 'frontend-audit.json')
    frontend_build = read(args.positive, 'frontend-build.json')
    require(not frontend_audit.get('error') and frontend_audit['metadata']['vulnerabilities']['high'] == 0 and
            frontend_audit['metadata']['vulnerabilities']['critical'] == 0, 'Frontend dependency gate failed')
    require(frontend_build['format'] == 1 and 'index.html' in frontend_build['files'] and
            positive.get('runtime_portal_assets_verified'), 'Packaged portal runtime proof missing')
    body, digest = manifest(positive['image'].split('@')[1])
    require(positive['image'].endswith('@' + digest), 'Registry manifest digest differs')
    if 'manifests' in body:
        children = [m for m in body['manifests'] if m.get('platform', {}).get('os') == 'linux' and
                    m.get('platform', {}).get('architecture') == 'amd64']
        require(len(children) == 1, 'Cannot identify unique runtime platform manifest')
        body, _ = manifest(children[0]['digest'])
    report = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': True,
              'job': 'backend-gate', 'source_commit': positive['source_commit'], 'positive': positive,
              'negative': negative, 'positive_tests': tests, 'negative_tests': failed_tests,
              'negative_registry_tag_absent': True, 'scan_classes': sorted(classes),
              'reported_high_critical': 0, 'docker_image_id': inspected['Id'],
              'registry_manifest_digest': digest, 'oci_config_digest': body['config']['digest'],
              'runtime_user': inspected['Config']['User'], 'sbom_components': len(sbom['components']),
              'frontend_input_sha256': frontend_build['input_sha256'],
              'frontend_runtime_assets_verified': True, 'frontend_reported_high_critical': 0,
              'positive_raw_trial': args.positive.as_posix(), 'negative_raw_trial': args.negative.as_posix(),
              'artifact_sha256': {name: hashlib.sha256((args.positive / name).read_bytes()).hexdigest()
                                  for name in ('source.json', 'result.json', 'tests.json', 'scan.json', 'sbom.json', 'frontend-audit.json', 'frontend-build.json')},
              'limitations': ['Local manually triggered trusted Docker-socket agent; external SCM/PR isolation still pending',
                              'Backend image publication does not change application environment Git or promote a release',
                              'All CI PostgreSQL data/credentials are ephemeral and separate from the real backend database']}
    (ROOT / 'docs/evidence/backend-ci-acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'tests': tests['tests_run'], 'reported_high_critical': 0,
                      'oci_config_digest': report['oci_config_digest']}))


if __name__ == '__main__':
    main()
