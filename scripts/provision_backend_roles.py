"""Preserve bootstrap credentials; migrate the existing database to restricted roles."""
import json
import os
import secrets

from sqlalchemy.engine import make_url

from backend.security import MIGRATOR, RUNTIME, configure_database, connect, private_json, provision_roles
from scripts.backend_runtime import CONFIG, SECRET_ROOT


def main():
    bootstrap_file = SECRET_ROOT / 'bootstrap-config.json'
    migration_file = SECRET_ROOT / 'migration-config.json'
    runtime_file = SECRET_ROOT / 'runtime-config.json'
    if not bootstrap_file.exists():
        original = json.loads(CONFIG.read_text())
        if make_url(original['database_url']).username != 'release_state':
            raise RuntimeError('Original bootstrap configuration is missing; refusing credential replacement')
        private_json(bootstrap_file, {'database_url': original['database_url']})
    original_url = json.loads(bootstrap_file.read_text())['database_url']
    for path, name in ((migration_file, MIGRATOR), (runtime_file, RUNTIME)):
        if not path.exists():
            url = make_url(original_url).set(username=name, password=secrets.token_urlsafe(32))
            private_json(path, {'database_url': url.render_as_string(hide_password=False)})
    runtime_url = json.loads(runtime_file.read_text())['database_url']
    migration_url = json.loads(migration_file.read_text())['database_url']
    with connect(original_url) as conn:
        provision_roles(conn, runtime_url, migration_url)
        configure_database(conn)
    # Test both independent logins before changing the normal API configuration.
    for url in (runtime_url, migration_url):
        with connect(url) as conn:
            conn.execute('SELECT 1')
    current = json.loads(CONFIG.read_text())
    current['database_url'] = runtime_url
    pending = CONFIG.with_suffix('.pending')
    if pending.exists():
        raise RuntimeError('Pending configuration exists; inspect before retrying')
    private_json(pending, current)
    os.replace(pending, CONFIG)
    print(json.dumps({'runtime_role': RUNTIME, 'migration_role': MIGRATOR,
                      'bootstrap_preserved': True, 'data_preserved': True}))


if __name__ == '__main__':
    main()
