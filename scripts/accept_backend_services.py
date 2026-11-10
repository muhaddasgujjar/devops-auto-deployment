"""Exercise the actual scoped collector, service restarts and restricted-role restore."""
import hashlib
import json
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.engine import make_url

from backend.backup import backup, restore
from backend.security import connect, private_json
from scripts.accept_backend import server
from scripts.backend_runtime import CONFIG, SECRET_ROOT
from scripts.render_release import ROOT


def command(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True, timeout=45)


def wait(check, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (httpx.TransportError, ValueError, OSError, KeyError):
            pass
        time.sleep(1)
    raise TimeoutError('Service acceptance condition was not observed')


def properties(unit):
    fields = ['User', 'MainPID', 'NRestarts', 'ActiveState', 'Restart', 'ProtectSystem', 'NoNewPrivileges']
    result = command('systemctl', 'show', unit, *['--property=' + value for value in fields])
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


def status():
    return json.loads(Path('/var/lib/release-observer/status.json').read_text())


def main():
    tokens = json.loads((SECRET_ROOT / 'tokens.json').read_text())
    kube = ['kubectl', '--kubeconfig', str(ROOT / 'output/lab.kubeconfig'), '--context=k3d-release-lab']
    scoped = ['kubectl', '--kubeconfig', str(SECRET_ROOT / 'observer.kubeconfig')]
    api, collector = 'release-state-api.service', 'release-state-collector.service'
    command('systemctl', 'start', api, collector)
    restored_binding = True
    try:
        with httpx.Client(base_url='http://127.0.0.1:8090', headers={'X-API-Key': tokens['admin']},
                          timeout=10, trust_env=False) as client:
            def state():
                response = client.get('/environment')
                response.raise_for_status()
                return response.json()
            wait(lambda: status().get('outcome') == 'observed' and state()['freshness'] == 'current')
            initial = state()
            initial_service = properties(collector)
            if initial_service['User'] != 'release-observer' or status()['uid'] == 0:
                raise AssertionError('Collector is not using its dedicated unprivileged account')
            cases = [(['get', 'rollouts.argoproj.io/release-demo', '-n', 'demo-dev'], True),
                     (['get', 'applications.argoproj.io/release-demo-dev', '-n', 'argocd'], True),
                     (['patch', 'rollouts.argoproj.io/release-demo', '-n', 'demo-dev'], False),
                     (['list', 'secrets', '-n', 'demo-dev'], False),
                     (['create', 'pods', '-n', 'demo-dev'], False),
                     (['get', 'applications.argoproj.io/other', '-n', 'argocd'], False)]
            authorization = []
            for args, expected in cases:
                response = command(*scoped, 'auth', 'can-i', *args, check=False)
                allowed = response.stdout.strip() == 'yes'
                if allowed != expected:
                    raise AssertionError('Scoped Kubernetes authorization mismatch')
                authorization.append({'request': args, 'allowed': allowed})
            command('systemctl', 'kill', '--signal=SIGKILL', '--kill-whom=main', collector)
            wait(lambda: properties(collector).get('MainPID') not in ('0', initial_service['MainPID']) and
                 status().get('pid') == int(properties(collector)['MainPID']) and status()['outcome'] == 'observed')
            restarted_collector = properties(collector)
            if int(restarted_collector['NRestarts']) < 1:
                raise AssertionError('Collector was not automatically restarted')
            command(*kube, 'delete', 'rolebinding', 'release-observer', '-n', 'argocd')
            restored_binding = False
            wait(lambda: state()['freshness'] == 'unavailable')
            unavailable = state()
            if unavailable['stable_revision'] != initial['stable_revision']:
                raise AssertionError('Source outage changed stored serving identity')
            command(*kube, 'apply', '-f', str(ROOT / 'platform/backend-observer.yaml'))
            restored_binding = True
            wait(lambda: state()['freshness'] == 'current')
            command('systemctl', 'stop', api)
            wait(lambda: status()['outcome'] == 'api_unavailable')
            retry_bound = status()['attempts']
            command('systemctl', 'start', api)
            wait(lambda: status()['outcome'] == 'observed' and state()['freshness'] == 'current')
            command('systemctl', 'stop', collector)
            before_api = properties(api)
            command('systemctl', 'kill', '--signal=SIGKILL', '--kill-whom=main', api)
            wait(lambda: properties(api).get('MainPID') not in ('0', before_api['MainPID']) and
                 client.get('/health/ready').status_code == 200)
            restarted_api = properties(api)
            snapshot = {name: client.get('/' + name).json() for name in ('environment', 'releases', 'builds', 'audit')}
            if snapshot['environment']['stable_revision'] != initial['stable_revision']:
                raise AssertionError('API restart changed serving identity')
            archive = ROOT / 'output' / ('restricted-backend-' + uuid.uuid4().hex[:12] + '.dump')
            backup(archive)
            restored_name = 'release_state_restore_' + uuid.uuid4().hex[:12]
            restore(archive, restored_name)
            configuration = json.loads(CONFIG.read_text())
            configuration['database_url'] = make_url(configuration['database_url']).set(database=restored_name).render_as_string(hide_password=False)
            restored_file = SECRET_ROOT / (restored_name + '.json')
            private_json(restored_file, configuration)
            with server(restored_file, 8091) as restored_client:
                restored = {name: restored_client.get('/' + name).json() for name in snapshot}
                if restored != snapshot:
                    raise AssertionError('Restricted-role restored API differs')
            with connect(json.loads(CONFIG.read_text())['database_url']) as conn:
                db_role = conn.execute('SELECT current_user').fetchone()[0]
            report = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': True,
                      'runtime_database_role': db_role, 'collector_service': restarted_collector,
                      'api_service': restarted_api, 'kubernetes_authorization': authorization,
                      'collector_automatic_restart_passed': True, 'api_automatic_restart_passed': True,
                      'source_authorization_outage_and_recovery_passed': True,
                      'api_outage_retry_attempts': retry_bound, 'serving_revision_preserved': initial['stable_revision'],
                      'backup': {'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'bytes': archive.stat().st_size,
                                 'archive': archive.relative_to(ROOT).as_posix(), 'restored_database': restored_name,
                                 'identical_restricted_api_views': list(snapshot)},
                      'limitations': ['One-hour observer token is explicitly refreshed by the administrator before later sessions',
                                      'Units are installed but not enabled at boot; laptop services are started/stopped explicitly',
                                      'The collector uses namespace-scoped read access and cannot deploy or recover releases']}
            (ROOT / 'docs/evidence/backend-services-acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps({'passed': True, 'retry_bound': retry_bound, 'runtime_role': db_role}))
    finally:
        if not restored_binding:
            command(*kube, 'apply', '-f', str(ROOT / 'platform/backend-observer.yaml'))
        command('systemctl', 'stop', collector, api)


if __name__ == '__main__':
    main()
