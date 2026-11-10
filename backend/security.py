"""Explicit PostgreSQL ownership and runtime grants for the release-state database."""
import json
import os
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

RUNTIME = 'release_state_runtime'
MIGRATOR = 'release_state_migrator'
TABLES = ('projects', 'environments', 'builds', 'artifacts', 'releases', 'analyses',
          'observations', 'incoming_events', 'audit', 'alembic_version')
UPDATES = {
    'environments': ('version', 'desired_release_id', 'stable_release_id', 'stable_revision', 'stable_hash',
                     'stable_image', 'source_uid', 'last_observed_at', 'freshness', 'detail'),
    'artifacts': ('scanned_image_id', 'reported_high_critical', 'refs'),
    'releases': ('candidate_hash', 'status', 'observation_sequence', 'source_uid', 'observed_at'),
    'analyses': ('phase', 'data'), 'incoming_events': ('result',),
}


def connect(url, **kwargs):
    value = make_url(url)
    return psycopg.connect(host=value.host, port=value.port, dbname=value.database,
                           user=value.username, password=value.password, connect_timeout=5, **kwargs)


def private_json(path, payload):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(payload, stream)


def provision_roles(conn, runtime_url, migration_url):
    for name, url in ((RUNTIME, runtime_url), (MIGRATOR, migration_url)):
        value = make_url(url)
        if value.username != name:
            raise ValueError('Role URL does not match the expected managed role')
        row = conn.execute('SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls '
                           'FROM pg_roles WHERE rolname=%s', (name,)).fetchone()
        if row is None:
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT '
                                 'NOREPLICATION NOBYPASSRLS PASSWORD {}').format(
                                     sql.Identifier(name), sql.Literal(value.password)))
        elif any(row):
            raise RuntimeError('Refusing to reuse an unexpectedly privileged role')
        memberships = conn.execute('SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON m.member=r.oid '
                                   'WHERE r.rolname=%s', (name,)).fetchone()[0]
        if memberships:
            raise RuntimeError('Managed role has unexpected memberships')


def configure_database(conn):
    database = conn.execute('SELECT current_database()').fetchone()[0]
    if database != 'release_state' and not database.startswith(('release_state_test_', 'release_state_restore_')):
        raise ValueError('Only the named backend, isolated test or new restore databases are supported')
    conn.execute(sql.SQL('REVOKE CREATE, TEMPORARY ON DATABASE {} FROM PUBLIC').format(sql.Identifier(database)))
    conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}, {}').format(
        sql.Identifier(database), sql.Identifier(RUNTIME), sql.Identifier(MIGRATOR)))
    conn.execute('REVOKE ALL ON SCHEMA public FROM PUBLIC')
    conn.execute(sql.SQL('ALTER SCHEMA public OWNER TO {}').format(sql.Identifier(MIGRATOR)))
    conn.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(RUNTIME)))
    for table in TABLES:
        if conn.execute('SELECT to_regclass(%s)', ('public.' + table,)).fetchone()[0] is None:
            continue
        conn.execute(sql.SQL('ALTER TABLE public.{} OWNER TO {}').format(sql.Identifier(table), sql.Identifier(MIGRATOR)))
        conn.execute(sql.SQL('REVOKE ALL ON public.{} FROM PUBLIC, {}').format(sql.Identifier(table), sql.Identifier(RUNTIME)))
        conn.execute(sql.SQL('GRANT SELECT ON public.{} TO {}').format(sql.Identifier(table), sql.Identifier(RUNTIME)))
        if table != 'alembic_version':
            conn.execute(sql.SQL('GRANT INSERT ON public.{} TO {}').format(sql.Identifier(table), sql.Identifier(RUNTIME)))
        if table in UPDATES:
            conn.execute(sql.SQL('GRANT UPDATE ({}) ON public.{} TO {}').format(
                sql.SQL(',').join(map(sql.Identifier, UPDATES[table])), sql.Identifier(table), sql.Identifier(RUNTIME)))
    if conn.execute("SELECT to_regclass('public.audit_id_seq')").fetchone()[0]:
        conn.execute(sql.SQL('ALTER SEQUENCE public.audit_id_seq OWNER TO {}').format(sql.Identifier(MIGRATOR)))
        conn.execute(sql.SQL('GRANT USAGE, SELECT ON SEQUENCE public.audit_id_seq TO {}').format(sql.Identifier(RUNTIME)))
    # Future migrations must explicitly grant write access to new tables/columns.
    conn.execute(sql.SQL('ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT ON TABLES TO {}').format(
        sql.Identifier(MIGRATOR), sql.Identifier(RUNTIME)))


def load_url(variable):
    path = os.environ.get(variable)
    if not path:
        raise RuntimeError('Set ' + variable + ' to its protected configuration file')
    return json.loads(Path(path).read_text())['database_url']
