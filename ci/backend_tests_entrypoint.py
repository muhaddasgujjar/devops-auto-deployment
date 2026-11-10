"""Use ephemeral CI credentials only; never read the real lab's bootstrap secret."""
import base64
import json
import os
from pathlib import Path

from backend.security import configure_database, connect, private_json, provision_roles

config = json.loads(base64.b64decode(os.environ.pop('RELEASE_CI_CONFIG_B64')))
directory = Path('/tmp/backend-ci-secrets')
directory.mkdir(mode=0o700)
for name in ('runtime', 'migration', 'bootstrap'):
    path = directory / (name + '.json')
    private_json(path, config[name])
    variable = {'runtime': 'RELEASE_CONFIG_FILE', 'migration': 'RELEASE_MIGRATION_CONFIG_FILE',
                'bootstrap': 'RELEASE_BOOTSTRAP_CONFIG_FILE'}[name]
    os.environ[variable] = str(path)
with connect(config['bootstrap']['database_url']) as conn:
    provision_roles(conn, config['runtime']['database_url'], config['migration']['database_url'])
    configure_database(conn)
from alembic import command
from alembic.config import Config
command.upgrade(Config('/app/alembic.ini'), 'head')
with connect(config['bootstrap']['database_url']) as conn:
    configure_database(conn)
os.environ['RELEASE_TEST_REPORT'] = '/tmp/backend-tests.json'
from scripts.validate_backend import main
main()
