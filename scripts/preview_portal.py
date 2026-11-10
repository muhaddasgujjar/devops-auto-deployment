"""Visual QA against a disposable copy of real PostgreSQL records, using fixture keys."""
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from psycopg import sql
from sqlalchemy.engine import make_url

from backend.backup import backup, restore
from backend.security import connect, load_url, private_json
from scripts.backend_runtime import CONFIG, SECRET_ROOT
from scripts.render_release import ROOT

READ_KEY = 'portal-preview-read-key-01234567890123456789'
ADMIN_KEY = 'portal-preview-admin-key-01234567890123456789'


def main():
    suffix = uuid.uuid4().hex[:12]
    database = 'release_state_restore_portal_' + suffix
    archive = ROOT / 'output' / ('portal-preview-' + suffix + '.dump')
    backup(archive)
    restore(archive, database)
    config = json.loads(CONFIG.read_text())
    config['database_url'] = make_url(config['database_url']).set(database=database).render_as_string(hide_password=False)
    config['api_keys'] = {hashlib.sha256(key.encode()).hexdigest(): role for key, role in ((READ_KEY, 'read'), (ADMIN_KEY, 'admin'))}
    config['callback_secret'] = 'preview-only-callback-fixture-' + suffix
    path = SECRET_ROOT / ('portal-preview-' + suffix + '.json')
    private_json(path, config)
    env = {**os.environ, 'RELEASE_CONFIG_FILE': str(path)}
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.api:create_app', '--factory',
        '--host', '127.0.0.1', '--port', '8093', '--no-access-log'], cwd=ROOT, env=env)
    def stop(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print('Portal QA: http://127.0.0.1:8093 (disposable database; fixture keys only)', flush=True)
    try:
        process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
        with connect(load_url('RELEASE_BOOTSTRAP_CONFIG_FILE'), autocommit=True) as conn:
            if not database.startswith('release_state_restore_portal_'):
                raise ValueError('Unsafe preview database name')
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
        path.unlink()


if __name__ == '__main__':
    main()
