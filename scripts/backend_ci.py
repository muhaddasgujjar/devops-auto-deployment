"""Trusted local CI: build, isolated PostgreSQL tests, scan/SBOM, then digest publication."""
import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from scripts.prepare_backend_build import prepare
from scripts.render_release import ROOT


def command(*args, check=True, timeout=600, **kwargs):
    result = subprocess.run(args, capture_output=True, timeout=timeout, **kwargs)
    if check and result.returncode:
        if result.stdout:
            print(result.stdout.decode(errors='replace')[-6000:], flush=True)
        if result.stderr:
            print(result.stderr.decode(errors='replace')[-4000:], flush=True)
        raise RuntimeError('Backend CI command failed: ' + args[0])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--build-number', required=True, type=int)
    parser.add_argument('--wheels', type=Path, default=Path('/opt/release-backend-wheels'))
    parser.add_argument('--negative-test', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}', args.source_sha) or args.build_number < 1:
        parser.error('A full source commit and positive build number are required')
    actual = command('git', '-C', str(ROOT), 'rev-parse', 'HEAD').stdout.decode().strip()
    if actual != args.source_sha:
        raise RuntimeError('CI checkout does not match reviewed source')
    if command('git', '-C', str(ROOT), 'diff', '--name-only', 'HEAD').stdout:
        raise RuntimeError('Tracked CI source is dirty')
    for kind in (signal.SIGTERM, signal.SIGINT):
        signal.signal(kind, lambda signum, frame: (_ for _ in ()).throw(SystemExit(143)))
    output = ROOT / 'output/backend-ci'
    output.mkdir(parents=True, exist_ok=True)
    versions = json.loads((ROOT / 'backend-versions.json').read_text())
    run_id = uuid.uuid4().hex[:12]
    network, pg, test, api = ['backend-ci-' + kind + '-' + run_id for kind in ('net', 'pg', 'test', 'api')]
    label = 'release-lab.backend-ci=' + run_id
    tag = f'localhost:5001/release-state:{args.source_sha}-jenkins-{args.build_number}'
    test_tag = 'release-state-test:' + run_id
    summary = {'source_commit': args.source_sha, 'build': args.build_number, 'negative_test': args.negative_test,
               'published': False, 'passed': False, 'image_tag': tag}
    containers, network_created = [], False
    (output / 'source.json').write_text(json.dumps(summary, indent=2))
    try:
        with tempfile.TemporaryDirectory(prefix='release-backend-ci-') as temporary:
            private = Path(temporary)
            context = prepare(private / 'context', args.wheels)
            print('Building pinned runtime and test targets from verified wheels', flush=True)
            for target, image in (('runtime', tag), ('test', test_tag)):
                result = command('docker', 'build', '-f', str(context / 'ci/backend.Dockerfile'), '--target', target,
                    '--build-arg', 'PYTHON_IMAGE=' + versions['python_image'], '--build-arg', 'SOURCE_SHA=' + args.source_sha,
                    '-t', image, str(context), timeout=900)
                (output / ('build-' + target + '.log')).write_bytes(result.stdout + result.stderr)
            command('docker', 'network', 'create', '--label', label, network)
            network_created = True
            password = secrets.token_urlsafe(24)
            pg_env = private / 'postgres.env'
            pg_env.write_text('POSTGRES_USER=release_state\nPOSTGRES_DB=release_state\nPOSTGRES_PASSWORD=' + password + '\n')
            pg_env.chmod(0o600)
            command('docker', 'run', '-d', '--name', pg, '--label', label, '--network', network,
                    '--memory=192m', '--cpus=1', '--env-file', str(pg_env), versions['postgres_image'],
                    'postgres', '-c', 'shared_buffers=24MB', '-c', 'max_connections=30')
            containers.append(pg)
            deadline = time.monotonic() + 90
            while command('docker', 'exec', pg, 'pg_isready', '-U', 'release_state', check=False).returncode:
                if time.monotonic() > deadline:
                    raise TimeoutError('Isolated PostgreSQL did not become ready')
                time.sleep(1)
            def url(user, password):
                return f'postgresql+psycopg://{user}:{password}@{pg}:5432/release_state'
            read = secrets.token_urlsafe(32)
            config = {'bootstrap': {'database_url': url('release_state', password)},
                      'migration': {'database_url': url('release_state_migrator', secrets.token_urlsafe(24))},
                      'runtime': {'database_url': url('release_state_runtime', secrets.token_urlsafe(24)),
                                  'api_keys': {hashlib.sha256(read.encode()).hexdigest(): 'read'},
                                  'callback_secret': secrets.token_urlsafe(32)}}
            env_file = private / 'test.env'
            env_file.write_text('RELEASE_CI_CONFIG_B64=' + base64.b64encode(json.dumps(config).encode()).decode() +
                                '\nRELEASE_NEGATIVE_TEST=' + ('true' if args.negative_test else 'false') + '\n')
            env_file.chmod(0o600)
            print('Running actual PostgreSQL/API and permission tests in the test target', flush=True)
            command('docker', 'create', '--name', test, '--label', label, '--network', network,
                    '--memory=256m', '--cpus=1', '--env-file', str(env_file), test_tag)
            containers.append(test)
            execution = command('docker', 'start', '-a', test, check=False, timeout=300)
            print((execution.stdout + execution.stderr).decode(errors='replace')[-5000:], flush=True)
            command('docker', 'cp', test + ':/tmp/backend-tests.json', str(output / 'tests.json'), check=False)
            tests = json.loads((output / 'tests.json').read_text())
            if execution.returncode or not tests['passed']:
                raise RuntimeError('Backend tests blocked scan and publication')
            # Independently boot the actual runtime target, containing no test fixtures.
            runtime_config = private / 'runtime.json'
            runtime_config.write_text(json.dumps(config['runtime']))
            runtime_config.chmod(0o644)  # Parent is private; copied file must be readable by UID 10001.
            command('docker', 'create', '--name', api, '--label', label, '--network', network,
                    '--memory=192m', '--cpus=1', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
                    '-e', 'RELEASE_CONFIG_FILE=/tmp/runtime.json', tag)
            containers.append(api)
            command('docker', 'cp', str(runtime_config), api + ':/tmp/runtime.json')
            command('docker', 'start', api)
            deadline = time.monotonic() + 45
            probe = "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8090/health/live',timeout=3).status==200"
            while command('docker', 'exec', api, 'python', '-c', probe, check=False).returncode:
                if time.monotonic() >= deadline:
                    raise RuntimeError('Runtime target did not become healthy')
                time.sleep(1)
            require_uid = command('docker', 'exec', api, 'id', '-u').stdout.decode().strip()
            if require_uid != '10001':
                raise RuntimeError('Runtime image is not running as the expected non-root UID')
            print('Runtime target passed startup; scanning OS and Python dependencies', flush=True)
            pinned_scanner = json.loads((ROOT / 'versions.json').read_text())['trivy']
            if ('Version: ' + pinned_scanner) not in command('trivy', '--version').stdout.decode():
                raise RuntimeError('Scanner version mismatch')
            command('trivy', 'image', '--quiet', '--scanners', 'vuln', '--severity', 'HIGH,CRITICAL', '--exit-code', '1',
                    '--format', 'json', '--output', str(output / 'scan.json'), tag, timeout=600)
            scan = json.loads((output / 'scan.json').read_text())
            inspected_before_push = json.loads(command('docker', 'image', 'inspect', tag).stdout)[0]
            if (scan['Metadata']['ImageID'] != inspected_before_push['Id'] or
                    not any(result.get('Class') == 'lang-pkgs' for result in scan.get('Results', [])) or
                    any(v.get('Severity') in ('HIGH', 'CRITICAL') for result in scan.get('Results', [])
                        for v in result.get('Vulnerabilities', []))):
                raise RuntimeError('Image identity, dependency coverage or vulnerability gate failed')
            command('trivy', 'image', '--quiet', '--format', 'cyclonedx', '--output', str(output / 'sbom.json'), tag)
            command('docker', 'push', tag)
            command('docker', 'pull', tag)
            inspected = json.loads(command('docker', 'image', 'inspect', tag).stdout)[0]
            scan = json.loads((output / 'scan.json').read_text())
            digests = [value for value in inspected['RepoDigests'] if value.startswith('localhost:5001/release-state@sha256:')]
            if len(digests) != 1 or scan['Metadata']['ImageID'] != inspected['Id']:
                raise RuntimeError('Scan/published image identity mismatch')
            summary.update(published=True, passed=True, image=digests[0], image_config_id=inspected['Id'],
                           runtime_uid=10001, tests_run=tests['tests_run'], scanner_version=pinned_scanner)
    finally:
        cleanup_errors = []
        for container in reversed(containers):
            info = command('docker', 'inspect', container, check=False)
            if info.returncode:
                continue
            obj = json.loads(info.stdout)[0]
            if obj['Config'].get('Labels', {}).get('release-lab.backend-ci') != run_id:
                cleanup_errors.append('ownership mismatch')
                continue
            if command('docker', 'rm', '-f', '-v', container, check=False).returncode:
                cleanup_errors.append('container removal failed')
        if network_created and command('docker', 'network', 'rm', network, check=False).returncode:
            cleanup_errors.append('network removal failed')
        summary['ephemeral_resources_removed'] = not cleanup_errors
        summary['cleanup_errors'] = cleanup_errors
        if cleanup_errors:
            summary['passed'] = False
        (output / 'result.json').write_text(json.dumps(summary, indent=2) + '\n')
        if cleanup_errors:
            raise RuntimeError('Backend CI resources require inspection')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
