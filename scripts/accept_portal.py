"""Check the installed same-origin portal with protected local keys; print no secrets."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone

import httpx

from scripts.backend_runtime import SECRET_ROOT
from scripts.render_release import ROOT


def main():
    base = 'http://127.0.0.1:8090'
    tokens = json.loads((SECRET_ROOT / 'tokens.json').read_text())
    with httpx.Client(base_url=base, timeout=10, trust_env=False) as client:
        index = client.get('/')
        assert index.status_code == 200 and 'Release Lab' in index.text
        assert "script-src 'self'" in index.headers['content-security-policy']
        assert index.headers['cache-control'] == 'no-store'
        assert client.get('/environment').status_code == 401
        manifest = client.get('/portal/build.json').json()
        for name, digest in manifest['files'].items():
            response = client.get('/' if name == 'index.html' else '/portal/' + name)
            assert response.status_code == 200
            assert hashlib.sha256(response.content).hexdigest() == digest
        login = client.post('/auth/session', json={'key': tokens['read']}, headers={'Origin': base})
        assert login.status_code == 200 and login.json()['role'] == 'read'
        assert 'httponly' in login.headers['set-cookie'].lower()
        assert 'samesite=strict' in login.headers['set-cookie'].lower()
        assert not any(value in login.text for value in tokens.values())
        csrf = login.json()['csrf_token']
        environment = client.get('/environment').json()
        releases = client.get('/releases?limit=100').json()
        builds = client.get('/builds?limit=100').json()
        assert environment['desired'] and environment['stable'] and releases and builds
        assert client.get('/audit').status_code == 403
        assert client.delete('/auth/session', headers={'Origin': base}).status_code == 403
        assert client.delete('/auth/session', headers={'Origin': base, 'X-CSRF-Token': csrf}).status_code == 200
        assert client.get('/environment').status_code == 401
        login = client.post('/auth/session', json={'key': tokens['admin']}, headers={'Origin': base})
        assert login.status_code == 200 and login.json()['role'] == 'admin'
        audit = client.get('/audit?limit=100')
        assert audit.status_code == 200 and audit.json()
        assert client.delete('/auth/session', headers={'Origin': base, 'X-CSRF-Token': login.json()['csrf_token']}).status_code == 200
    source = subprocess.check_output(['systemctl', 'show', 'release-state-api', '-p', 'WorkingDirectory', '--value'], text=True).strip().rsplit('/', 1)[1]
    report = {'recorded_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': True,
              'installed_source_commit': source, 'frontend_input_sha256': manifest['input_sha256'],
              'verified_asset_count': len(manifest['files']), 'read_audit_denied': True,
              'admin_audit_allowed': True, 'csrf_enforced': True, 'logout_revokes_access': True,
              'keys_disclosed': False, 'release_records': len(releases), 'build_records': len(builds),
              'desired_build': environment['desired']['build']['number'],
              'stable_build': environment['stable']['build']['number'],
              'freshness': environment['freshness'], 'environment_version': environment['version'],
              'limitations': ['Loopback HTTP, one API worker, process-local sessions; TLS/remote hosting remain future work',
                              'This check reads production lab evidence; it does not promote or recover releases']}
    (ROOT / 'docs/evidence/portal-service-acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
