"""Manage the loopback product API and its isolated, retained PostgreSQL store."""
import argparse
import json
import os
import secrets
import subprocess
import time
from pathlib import Path

from scripts.render_release import ROOT

STATE = Path('/opt/release-lab/secrets')
UNIT = 'release-lab-portal.service'
CONTAINER = 'release-portal-db'


def run(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        # Command arguments or stderr could contain environment details. Keep
        # generated database credentials out of all command output.
        raise RuntimeError('Portal operation failed: ' + args[0] + ' ' + args[1])
    return result.stdout.strip()


def environment():
    return dict(line.split('=', 1) for line in (STATE / 'portal.env').read_text().splitlines() if '=' in line)


def migrate():
    run('/opt/release-lab/venv/bin/python', '-m', 'alembic', '-c', 'apps/api/alembic.ini', 'upgrade', 'head',
        cwd=ROOT, env={**os.environ, **environment()}, timeout=90)


def setup():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not (STATE / 'portal.env').exists():
        password = secrets.token_hex(32)
        (STATE / 'portal.env').write_text('RELEASE_DATABASE_URL=postgresql+psycopg://release_portal:' + password
                                       + '@127.0.0.1:5433/release_portal\nRELEASE_CALLBACK_SECRET=' + secrets.token_hex(32) + '\n')
        (STATE / 'portal-db.env').write_text('POSTGRES_USER=release_portal\nPOSTGRES_DB=release_portal\nPOSTGRES_PASSWORD=' + password + '\n')
        (STATE / 'portal.env').chmod(0o600)
        (STATE / 'portal-db.env').chmod(0o600)
    result = subprocess.run(['docker', 'inspect', CONTAINER], capture_output=True, text=True)
    if result.returncode == 0:
        obj = json.loads(result.stdout)[0]
        if obj['Config'].get('Labels', {}).get('release-lab.managed') != 'true':
            raise RuntimeError('Refusing to manage an unlabelled database container')
        run('docker', 'start', CONTAINER)
    else:
        image = json.loads((ROOT / 'versions.json').read_text())['portal_postgres_image']
        if '@sha256:' not in image:
            raise RuntimeError('Portal database image must be digest-pinned')
        run('docker', 'volume', 'create', '--label', 'release-lab.managed=true', 'release-portal-data')
        run('docker', 'run', '-d', '--name', CONTAINER, '--label', 'release-lab.managed=true',
            '--restart', 'unless-stopped', '--memory', '192m', '--cpus', '0.5', '--pids-limit', '128', '--shm-size', '32m',
            '--env-file', str(STATE / 'portal-db.env'), '-p', '127.0.0.1:5433:5432',
            '-v', 'release-portal-data:/var/lib/postgresql/data', image,
            '-c', 'shared_buffers=32MB', '-c', 'max_connections=20', '-c', 'work_mem=2MB', timeout=120)
    for _ in range(30):
        if subprocess.run(['docker', 'exec', CONTAINER, 'pg_isready', '-U', 'release_portal', '-d', 'release_portal'], capture_output=True).returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError('Portal database did not become ready')


def install():
    setup()
    migrate()
    unit = Path('/etc/systemd/system') / UNIT
    unit.write_text('[Unit]\nDescription=Releaseboard local product API\nAfter=docker.service\n'
        '[Service]\nType=simple\nWorkingDirectory=' + str(ROOT).replace('%', '%%') + '\n'
        'EnvironmentFile=/opt/release-lab/secrets/portal.env\n'
        'ExecStart=/opt/release-lab/venv/bin/python -m uvicorn apps.api.main:app_factory --factory --host 127.0.0.1 --port 8083 --no-access-log\n'
        'Restart=on-failure\nRestartSec=5\nMemoryMax=192M\nCPUQuota=35%\nUMask=0077\n'
        'TimeoutStopSec=30\n[Install]\nWantedBy=multi-user.target\n')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', UNIT)
    run('systemctl', 'restart', UNIT)
    (ROOT / 'output/portal-installed.json').write_text(json.dumps({'url': 'http://localhost:8083/', 'service': UNIT}))
    print('Releaseboard: http://localhost:8083/ (loopback only; retained PostgreSQL data)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'migrate', 'start', 'stop', 'status'])
    args = parser.parse_args()
    if args.action == 'setup':
        install()
    elif args.action == 'migrate':
        migrate()
    elif args.action == 'start':
        setup()
        run('systemctl', 'start', UNIT)
    elif args.action == 'stop':
        run('systemctl', 'stop', UNIT)
        run('docker', 'stop', '--time', '30', CONTAINER)
    else:
        print(json.dumps({'api': run('systemctl', 'is-active', UNIT),
                          'url': 'http://localhost:8083/', 'database': run('docker', 'inspect', '--format', '{{.State.Status}}', CONTAINER)}))


if __name__ == '__main__':
    main()
