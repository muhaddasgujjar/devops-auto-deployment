"""Rehearse the populated migration on a restored copy before upgrading the lab."""
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from backend.backup import backup, restore
from backend.db import Database
from backend.security import configure_database, connect, load_url, private_json
from scripts.render_release import ROOT


def snapshot(url):
    with connect(url) as conn:
        return {'counts':{t:conn.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(t))).fetchone()[0]
                          for t in ('builds','artifacts','releases','observations','incoming_events','audit')},
                'environments':conn.execute('SELECT id,version,desired_release_id,stable_release_id,stable_revision,stable_hash FROM environments ORDER BY id').fetchall(),
                'releases':conn.execute('SELECT id,environment_id,build_id,environment_commit,status FROM releases ORDER BY id').fetchall()}


def main():
    bootstrap=load_url('RELEASE_BOOTSTRAP_CONFIG_FILE')
    migration=load_url('RELEASE_MIGRATION_CONFIG_FILE')
    runtime=load_url('RELEASE_CONFIG_FILE')
    with connect(bootstrap) as conn:
        revision=conn.execute('SELECT version_num FROM alembic_version').fetchone()[0]
    if revision!='0001_release_state':
        raise RuntimeError('This populated rehearsal expects the preserved milestone-6 schema')
    before=snapshot(bootstrap)
    suffix=uuid.uuid4().hex[:12]
    archive=ROOT/'output'/('before-recovery-'+suffix+'.dump')
    backup(archive)
    database='release_state_restore_recovery_'+suffix
    restore(archive,database)
    previous=os.environ['RELEASE_MIGRATION_CONFIG_FILE']
    try:
        with tempfile.TemporaryDirectory(prefix='release-recovery-migration-') as temporary:
            path=Path(temporary)/'migration.json'
            private_json(path,{'database_url':make_url(migration).set(database=database).render_as_string(hide_password=False)})
            os.environ['RELEASE_MIGRATION_CONFIG_FILE']=str(path)
            command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
            copy_url=make_url(bootstrap).set(database=database).render_as_string(hide_password=False)
            with connect(copy_url) as conn: configure_database(conn)
            assert snapshot(copy_url)==before, 'Restored migration changed existing data or identities'
            check=Database(make_url(runtime).set(database=database).render_as_string(hide_password=False))
            assert check.ready(); check.close()
    finally:
        os.environ['RELEASE_MIGRATION_CONFIG_FILE']=previous
        with connect(bootstrap,autocommit=True) as conn:
            assert database=='release_state_restore_recovery_'+suffix
            conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
    command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
    with connect(bootstrap) as conn: configure_database(conn)
    assert snapshot(bootstrap)==before, 'Main migration changed existing data or identities'
    check=Database(runtime); assert check.ready(); check.close()
    result={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'passed':True,
            'from_revision':revision,'to_revision':'0002_recovery','restored_copy_checked_before_main':True,
            'existing_counts':before['counts'],'original_environment_and_release_identities_preserved':True,
            'restricted_runtime_ready':True,'disposable_copy_removed':True,
            'backup':archive.relative_to(ROOT).as_posix(),'backup_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
    (ROOT/'docs/evidence/recovery-migration.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__': main()
