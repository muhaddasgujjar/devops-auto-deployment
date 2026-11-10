"""Install manually started systemd services from committed code, without enabling boot startup."""
import argparse
import hashlib
import json
import os
import secrets
import subprocess
import tarfile
import tempfile
from pathlib import Path

from backend.security import private_json
from backend.ui_bundle import copy_bundle, verify
from scripts.backend_runtime import CONFIG, SECRET_ROOT
from scripts.render_release import ROOT

MARKER = '# Managed by release-lab backend\n'


def command(*args):
    return subprocess.check_output(args, text=True, timeout=120).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-observer-token', action='store_true')
    parser.add_argument('--refresh-recovery-token', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('Service installation requires the local Linux administrator')
    for user in ('release-api', 'release-observer', 'release-recovery'):
        if subprocess.run(['id', '-u', user], capture_output=True).returncode:
            command('useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', user)
    sha = command('git', '-C', str(ROOT), 'rev-parse', 'HEAD')
    if command('git', '-C', str(ROOT), 'status', '--porcelain', '--', 'backend', 'frontend'):
        raise RuntimeError('Commit backend and frontend source before installing the service snapshot')
    snapshot = Path('/opt/release-lab/backend-runtime') / sha
    if not snapshot.exists():
        snapshot.mkdir(parents=True)
        with tempfile.TemporaryFile() as archive:
            subprocess.run(['git', '-C', str(ROOT), 'archive', sha, 'backend', 'frontend'], stdout=archive, check=True)
            archive.seek(0)
            with tarfile.open(fileobj=archive) as content:
                content.extractall(snapshot, filter='data')
    verify(snapshot / 'frontend', ROOT / 'frontend/dist')
    copy_bundle(ROOT / 'frontend', snapshot / 'frontend/dist')
    observer_config = SECRET_ROOT / 'collector.json'
    if not observer_config.exists():
        current = json.loads(CONFIG.read_text())
        token = secrets.token_urlsafe(32)
        current['api_keys'][hashlib.sha256(token.encode()).hexdigest()] = 'read'
        pending = CONFIG.with_suffix('.collector-pending')
        private_json(pending, current)
        os.replace(pending, CONFIG)
        private_json(observer_config, {'api_url': 'http://127.0.0.1:8090', 'read_key': token,
            'callback_secret': current['callback_secret'], 'kubeconfig': str(SECRET_ROOT / 'observer.kubeconfig'),
            'environment_git': '/var/lib/release-lab/git/environment.git'})
    if args.refresh_observer_token:
        kubeconfig = ROOT / 'output/lab.kubeconfig'
        base = ['kubectl', '--kubeconfig', str(kubeconfig), '--context=k3d-release-lab']
        command(*base, 'apply', '-f', str(ROOT / 'platform/backend-observer.yaml'))
        raw = json.loads(command(*base, 'config', 'view', '--raw', '--minify', '-o', 'json'))
        token = command(*base, 'create', 'token', 'release-observer', '-n', 'release-observer', '--duration=1h')
        limited = {'apiVersion': 'v1', 'kind': 'Config', 'current-context': 'k3d-release-lab',
                   'clusters': raw['clusters'], 'users': [{'name': 'observer', 'user': {'token': token}}],
                   'contexts': [{'name': 'k3d-release-lab', 'context': {'cluster': raw['clusters'][0]['name'], 'user': 'observer'}}]}
        target = SECRET_ROOT / 'observer.kubeconfig'
        pending = target.with_suffix('.pending')
        private_json(pending, limited)
        os.replace(pending, target)
    if not (SECRET_ROOT / 'observer.kubeconfig').exists():
        raise RuntimeError('Start the lean lab and refresh the one-hour read-only observer token first')
    recovery_config = SECRET_ROOT / 'recovery.json'
    if args.refresh_recovery_token:
        base = ['kubectl', '--kubeconfig', str(ROOT / 'output/lab.kubeconfig'), '--context=k3d-release-lab']
        command(*base, 'apply', '-f', str(ROOT / 'platform/backend-recovery.yaml'))
        raw = json.loads(command(*base, 'config', 'view', '--raw', '--minify', '-o', 'json'))
        token = command(*base, 'create', 'token', 'release-recovery', '-n', 'release-recovery', '--duration=1h')
        limited = {'apiVersion': 'v1', 'kind': 'Config', 'current-context': 'k3d-release-lab',
                   'clusters': raw['clusters'], 'users': [{'name': 'recovery', 'user': {'token': token}}],
                   'contexts': [{'name': 'k3d-release-lab', 'context': {'cluster': raw['clusters'][0]['name'], 'user': 'recovery'}}]}
        target = SECRET_ROOT / 'recovery.kubeconfig'
        pending = target.with_suffix('.pending')
        private_json(pending, limited)
        os.replace(pending, target)
        if not recovery_config.exists():
            key = secrets.token_urlsafe(32)
            current = json.loads(CONFIG.read_text())
            current['api_keys'][hashlib.sha256(key.encode()).hexdigest()] = 'recovery'
            pending = CONFIG.with_suffix('.recovery-pending')
            private_json(pending, current)
            os.replace(pending, CONFIG)
            private_json(recovery_config, {'api_url': 'http://127.0.0.1:8090', 'api_key': key,
                'repository': 'ssh://release-git@127.0.0.1:2222/var/lib/release-lab/git/environment.git',
                'kubeconfig': str(SECRET_ROOT / 'recovery.kubeconfig'),
                'environment_git': '/var/lib/release-lab/git/environment.git'})
    common = f'''[Unit]
After=network.target
StartLimitIntervalSec=120
StartLimitBurst=3

[Service]
WorkingDirectory={snapshot}
Environment=PYTHONPATH={snapshot}
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=3
TimeoutStopSec=20
MemoryMax=192M
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
InaccessiblePaths=-/var/run/docker.sock /mnt /opt/release-lab/secrets
'''
    units = {
        'release-state-api': common + f'''User=release-api
Group=release-api
LoadCredential=api.json:{CONFIG}
Environment=RELEASE_CONFIG_FILE=%d/api.json
ExecStart=/opt/release-lab/backend-venv/bin/python -m uvicorn backend.api:create_app --factory --host 127.0.0.1 --port 8090 --no-access-log
''',
        'release-state-collector': common + f'''User=release-observer
Group=release-observer
LoadCredential=collector.json:{observer_config}
LoadCredential=kubeconfig:{SECRET_ROOT / 'observer.kubeconfig'}
Environment=RELEASE_WORKER_CONFIG_FILE=%d/collector.json
Environment=RELEASE_OBSERVER_KUBECONFIG=%d/kubeconfig
StateDirectory=release-observer
StateDirectoryMode=0750
ExecStart=/opt/release-lab/backend-venv/bin/python -m backend.worker
'''}
    if recovery_config.exists():
        git_key = SECRET_ROOT.parent / 'environment-recovery'
        if not git_key.exists() or not (SECRET_ROOT / 'recovery.kubeconfig').exists():
            raise RuntimeError('Start local Git and refresh the scoped recovery token before installing recovery')
        units['release-state-recovery'] = common + f'''User=release-recovery
Group=release-recovery
LoadCredential=recovery.json:{recovery_config}
LoadCredential=kubeconfig:{SECRET_ROOT / 'recovery.kubeconfig'}
LoadCredential=git-key:{git_key}
LoadCredential=known-hosts:{SECRET_ROOT.parent / 'known_hosts'}
Environment=RELEASE_RECOVERY_CONFIG_FILE=%d/recovery.json
Environment=RELEASE_RECOVERY_KUBECONFIG=%d/kubeconfig
Environment=RELEASE_RECOVERY_GIT_KEY=%d/git-key
Environment=RELEASE_RECOVERY_KNOWN_HOSTS=%d/known-hosts
StateDirectory=release-recovery
StateDirectoryMode=0750
ExecStart=/opt/release-lab/backend-venv/bin/python -m backend.recovery_worker
'''
    for name, unit in units.items():
        path = Path('/etc/systemd/system') / (name + '.service')
        if path.exists() and not path.read_text().startswith(MARKER):
            raise RuntimeError('Refusing to replace an unmanaged systemd service')
        path.write_text(MARKER + unit)
    command('systemctl', 'daemon-reload')
    print(json.dumps({'source_commit': sha, 'units_installed': list(units), 'boot_startup_enabled': False,
                      'observer_token_lifetime': '1h; refresh explicitly before later sessions'}))


if __name__ == '__main__':
    main()
