"""Manage only the labelled local PostgreSQL service; preserve its volume and keys."""
import argparse
import hashlib
import json
import os
import secrets
import subprocess
import time
from pathlib import Path

from scripts.render_release import ROOT

SECRET_ROOT = Path('/opt/release-lab/secrets/backend')
CONFIG = SECRET_ROOT / 'config.json'
NAME = 'release-state-db'
LABEL = 'release-lab.backend'


def command(*args, **kwargs):
    result = subprocess.run(args, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-1500:])
    return result


def inspect():
    result = subprocess.run(['docker', 'inspect', NAME], capture_output=True)
    if result.returncode:
        return None
    obj = json.loads(result.stdout)[0]
    if obj['Config'].get('Labels', {}).get(LABEL) != 'true':
        raise RuntimeError('Refusing to manage an unlabelled database container')
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'start', 'stop', 'status'])
    args = parser.parse_args()
    if args.action == 'setup':
        if not CONFIG.exists():
            if inspect() is not None:
                raise RuntimeError('Database exists without its configuration; refusing to replace secrets')
            SECRET_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
            SECRET_ROOT.chmod(0o700)
            password = secrets.token_urlsafe(32)
            tokens = {role: secrets.token_urlsafe(32) for role in ('read', 'developer', 'admin')}
            config = {'database_url': f'postgresql+psycopg://release_state:{password}@127.0.0.1:15432/release_state',
                      'api_keys': {hashlib.sha256(token.encode()).hexdigest(): role for role, token in tokens.items()},
                      'callback_secret': secrets.token_urlsafe(48)}
            for path, content in ((CONFIG, json.dumps(config)), (SECRET_ROOT / 'tokens.json', json.dumps(tokens)),
                                  (SECRET_ROOT / 'postgres.env', f'POSTGRES_PASSWORD={password}\nPOSTGRES_USER=release_state\nPOSTGRES_DB=release_state\n')):
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w') as stream:
                    stream.write(content)
        if inspect() is None:
            command('docker', 'volume', 'create', '--label', LABEL + '=true', 'release-state-postgres')
            image = json.loads((ROOT / 'backend-versions.json').read_text())['postgres_image']
            command('docker', 'run', '--detach', '--name', NAME, '--label', LABEL + '=true',
                    '--memory=256m', '--cpus=0.5', '--pids-limit=128', '--publish=127.0.0.1:15432:5432',
                    '--mount=type=volume,source=release-state-postgres,target=/var/lib/postgresql/data',
                    '--env-file', str(SECRET_ROOT / 'postgres.env'), image,
                    'postgres', '-c', 'shared_buffers=32MB', '-c', 'max_connections=30')
    obj = inspect()
    if not obj:
        raise RuntimeError('Run setup before managing the backend')
    if args.action in ('start', 'setup'):
        if not obj['State']['Running']:
            command('docker', 'start', NAME)
        deadline = time.monotonic() + 90
        while subprocess.run(['docker', 'exec', NAME, 'pg_isready', '-U', 'release_state'], capture_output=True).returncode:
            if time.monotonic() > deadline:
                raise RuntimeError('PostgreSQL did not become ready')
            time.sleep(1)
    elif args.action == 'stop' and obj['State']['Running']:
        command('docker', 'stop', '--timeout=30', NAME)
    print(json.dumps({'container': NAME, 'running': inspect()['State']['Running'],
                      'config_file': str(CONFIG), 'volume_preserved': True}))


if __name__ == '__main__':
    main()
