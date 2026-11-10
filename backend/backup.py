"""Custom-format PostgreSQL backup; restore only into a new named database."""
import argparse
import os
import re
import subprocess
from pathlib import Path

from scripts.backend_runtime import NAME, inspect


def owned():
    obj = inspect()
    if not obj or not obj['State']['Running']:
        raise RuntimeError('Start the labelled backend PostgreSQL container')


def backup(path):
    owned()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        result = subprocess.run(['docker', 'exec', NAME, 'pg_dump', '-U', 'release_state',
                                 '--format=custom', '--no-owner', 'release_state'], stdout=stream, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError('pg_dump failed; preserve the partial file for diagnosis')


def restore(path, database):
    owned()
    if not re.fullmatch(r'release_state_restore_[a-z0-9_]{8,40}', database):
        raise ValueError('Restore requires a new release_state_restore_ database name')
    # createdb fails if the destination already exists: never clean or overwrite it.
    result = subprocess.run(['docker', 'exec', NAME, 'createdb', '-U', 'release_state', database], capture_output=True)
    if result.returncode:
        raise RuntimeError('Could not create a new empty restore database; refusing to overwrite')
    with Path(path).open('rb') as stream:
        result = subprocess.run(['docker', 'exec', '-i', NAME, 'pg_restore', '-U', 'release_state',
            '--exit-on-error', '--no-owner', '--no-acl', '-d', database], stdin=stream, capture_output=True)
    if result.returncode:
        raise RuntimeError('Restore failed; the new destination is retained for diagnosis')
    from backend.security import configure_database, connect, load_url
    from sqlalchemy.engine import make_url
    bootstrap = make_url(load_url('RELEASE_BOOTSTRAP_CONFIG_FILE')).set(database=database)
    with connect(bootstrap.render_as_string(hide_password=False)) as conn:
        configure_database(conn)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'restore'])
    parser.add_argument('archive', type=Path)
    parser.add_argument('--database')
    args = parser.parse_args()
    if args.action == 'backup':
        backup(args.archive)
    else:
        if not args.database:
            parser.error('--database is required for restore')
        restore(args.archive, args.database)
    print('PostgreSQL ' + args.action + ' completed')


if __name__ == '__main__':
    main()
