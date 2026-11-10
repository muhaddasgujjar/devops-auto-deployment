"""Real HTTP/process and PostgreSQL restore acceptance, in two bounded stages."""
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.backup import backup, restore
from backend.cli import post_callback
from backend.collector import SourcesUnavailable, collect
from backend.config import load_settings
from scripts.render_release import ROOT

OUTPUT = ROOT / 'output/backend-acceptance'


def require(condition, message):
    if not condition:
        raise AssertionError(message)


@contextmanager
def server(config_path, port):
    with socket.socket() as sock:
        require(sock.connect_ex(('127.0.0.1', port)) != 0, 'Acceptance HTTP port is already in use')
    env = {**os.environ, 'RELEASE_CONFIG_FILE': str(config_path)}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / ('api-' + str(port) + '.log')).open('a') as log:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.api:create_app', '--factory',
            '--host', '127.0.0.1', '--port', str(port), '--no-access-log'], cwd=ROOT, env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(base_url='http://127.0.0.1:' + str(port), timeout=30) as client:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    require(process.poll() is None, 'API process exited before readiness; inspect the retained log')
                    try:
                        if client.get('/health/live').status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.5)
                else:
                    raise TimeoutError('API process did not become ready')
                tokens = json.loads((Path(config_path).parent / 'tokens.json').read_text())
                client.headers['X-API-Key'] = tokens['admin']
                require(client.get('/health/ready').status_code == 200, 'Database API readiness failed')
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def get(client, path):
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def import_report(client, file, kind):
    raw = (ROOT / 'docs/evidence' / file).read_bytes()
    payload = {'event_id': 'report:' + hashlib.sha256(raw).hexdigest(),
               'expected_version': get(client, '/environment')['version'], 'kind': kind, 'report': json.loads(raw)}
    response = client.post('/imports', json=payload)
    response.raise_for_status()
    return response.json()


def reconcile(client, settings, kubeconfig):
    payload = {'event_id': 'reconcile:' + uuid.uuid4().hex, 'expected_version': get(client, '/environment')['version']}
    try:
        observation = collect(kubeconfig, Path('/var/lib/release-lab/git/environment.git'))
        payload['release'] = observation.model_dump(mode='json')
    except (SourcesUnavailable, KeyError, ValueError, StopIteration):
        payload['unavailable'] = 'sources_unavailable'
    response = post_callback(client, settings, payload)
    response.raise_for_status()
    return {**response.json(), 'collected_resource_version': payload.get('release', {}).get('observation_details', {}).get('resource_version')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['import', 'reconcile-restore'])
    parser.add_argument('--kubeconfig', type=Path, default=ROOT / 'output/lab.kubeconfig')
    args = parser.parse_args()
    settings = load_settings()
    config_path = Path(os.environ['RELEASE_CONFIG_FILE'])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if args.stage == 'import':
        with server(config_path, 8090) as client:
            imports = [import_report(client, 'ci-gitops-acceptance.json', 'ci_acceptance'),
                       import_report(client, 'runtime-failure-validation.json', 'runtime_acceptance'),
                       import_report(client, 'ci-negative-gate.json', 'ci_negative_gate')]
            require(import_report(client, 'runtime-failure-validation.json', 'runtime_acceptance')['duplicate'], 'Report replay was not idempotent')
            state = get(client, '/environment')
            require(state['desired']['build']['number'] == state['stable']['build']['number'] == 16, 'Historical state mismatch')
            require(len(get(client, '/releases')) == 9 and len(get(client, '/builds')) == 10, 'Import counts mismatch')
            reconcile(client, settings, args.kubeconfig)
            outage = get(client, '/environment')
            require(outage['freshness'] == 'unavailable', 'Stopped cluster did not produce explicit unavailability')
            receipt = {'passed': True, 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
                       'imports': imports, 'releases': 9, 'builds': 10, 'desired_build': 16,
                       'stable_build': 16, 'after_stopped_source': outage['freshness'], 'version': outage['version'],
                       'api_process_stopped_after_stage': True}
            (OUTPUT / 'import.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print('Real HTTP imports, replay and stopped-source acceptance passed; API stopped')
        return
    initial = json.loads((OUTPUT / 'import.json').read_text())
    require(initial['passed'], 'Run the import stage first')
    with server(config_path, 8090) as client:
        before = get(client, '/environment')
        require(before['desired']['build']['number'] == 16, 'Backend changed while it was stopped')
        discovered = reconcile(client, settings, args.kubeconfig)
        current = get(client, '/environment')
        require(current['freshness'] == 'current' and current['desired']['build']['number'] > 16 and
                current['desired']['id'] == current['stable']['id'] and current['desired']['status'] == 'promoted',
                'Read-only reconciliation did not discover the missed release')
        missed_build = current['desired']['build']['number']
        reconcile(client, settings, OUTPUT / 'deliberately-missing.kubeconfig')
        require(get(client, '/environment')['freshness'] == 'unavailable', 'Source outage was hidden')
        refreshed = reconcile(client, settings, args.kubeconfig)
        recovered = get(client, '/environment')
        require(recovered['freshness'] == 'current', 'Unchanged-resource-version refresh did not restore freshness')
        require(import_report(client, 'ci-gitops-acceptance.json', 'ci_acceptance')['duplicate'], 'Restart lost durable deduplication')
        snapshot = {name: get(client, '/' + name) for name in ('environment', 'releases', 'builds', 'audit')}
        archive = OUTPUT / ('state-' + uuid.uuid4().hex[:12] + '.dump')
        backup(archive)
        restored_name = 'release_state_restore_' + uuid.uuid4().hex[:12]
        restore(archive, restored_name)
        restored_settings = replace(settings, database_url=make_url(settings.database_url).set(
            database=restored_name).render_as_string(hide_password=False))
        restored_config = config_path.parent / (restored_name + '.json')
        fd = os.open(restored_config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(asdict(restored_settings), stream)
        with server(restored_config, 8091) as restored_client:
            restored = {name: get(restored_client, '/' + name) for name in snapshot}
            require(restored == snapshot, 'Restored database API output differs from the source')
        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            version = conn.scalar(text('SHOW server_version'))
            counts = {table: conn.scalar(text('SELECT count(*) FROM ' + table)) for table in (
                'builds', 'artifacts', 'releases', 'analyses', 'observations', 'incoming_events', 'audit')}
        engine.dispose()
        report = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': True,
                  'scope': 'Local PostgreSQL/API durable state, missed real release reconciliation and API-verified restore',
                  'initial_http_stage': initial, 'missed_release_detected': missed_build,
                  'previous_stored_build': 16, 'serving_revision': recovered['stable_revision'],
                  'source_uid': recovered['source_uid'], 'freshness_after_recovery': recovered['freshness'],
                  'version': recovered['version'], 'database_server_version': version, 'rows': counts,
                  'backup': {'archive': archive.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                             'bytes': archive.stat().st_size, 'restored_database': restored_name,
                             'identical_api_views': list(snapshot)},
                  'api_process_restart_passed': True, 'source_outage_recovery_passed': True,
                  'unchanged_kubernetes_resource_version': discovered['collected_resource_version'] == refreshed['collected_resource_version'],
                  'limitations': ['Local single project/environment; API keys are not enterprise SSO',
                                  'Curated imports retain reported proof; they do not independently rerun scans',
                                  'New live-discovered artifacts expose scan metadata as unknown until CI evidence arrives',
                                  'Collector reads Git/Kubernetes only; post-promotion recovery remains unimplemented',
                                  'Raw backups and credentials are private local state, excluded from Git']}
        (ROOT / 'docs/evidence/backend-acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Actual missed-release reconciliation, restart, outage recovery and PostgreSQL/API restore passed')


if __name__ == '__main__':
    main()
