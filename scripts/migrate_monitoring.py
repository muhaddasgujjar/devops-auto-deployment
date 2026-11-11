"""Restore and rehearse the populated monitoring upgrade before changing the lab."""
import hashlib
import json
import os
import tempfile
import uuid
from datetime import datetime,timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.engine import make_url

from backend.backup import backup,restore
from backend.db import Database
from backend.platform_backup import database_snapshot
from backend.security import configure_database,connect,load_url,private_json
from scripts.render_release import ROOT


def main():
    bootstrap=load_url('RELEASE_BOOTSTRAP_CONFIG_FILE'); migration=load_url('RELEASE_MIGRATION_CONFIG_FILE'); runtime=load_url('RELEASE_CONFIG_FILE')
    with connect(bootstrap) as conn:
        previous=conn.execute('SELECT version_num FROM alembic_version').fetchone()[0]
    if previous!='0002_recovery': raise RuntimeError('This rehearsal expects the accepted milestone-7 schema')
    before=database_snapshot(bootstrap); suffix=uuid.uuid4().hex[:12]
    archive=ROOT/'output'/('before-monitoring-'+suffix+'.dump'); backup(archive)
    database='release_state_restore_monitoring_'+suffix
    restore(archive,database)
    old_path=os.environ['RELEASE_MIGRATION_CONFIG_FILE']
    try:
        with tempfile.TemporaryDirectory(prefix='release-monitoring-upgrade-') as directory:
            path=Path(directory)/'migration.json'
            private_json(path,{'database_url':make_url(migration).set(database=database).render_as_string(hide_password=False)})
            os.environ['RELEASE_MIGRATION_CONFIG_FILE']=str(path)
            command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
            copy_url=make_url(bootstrap).set(database=database).render_as_string(hide_password=False)
            with connect(copy_url) as conn: configure_database(conn)
            if database_snapshot(copy_url,before)!=before: raise RuntimeError('Populated restore upgrade changed original data')
            check=Database(make_url(runtime).set(database=database).render_as_string(hide_password=False)); assert check.ready(); check.close()
    finally:
        os.environ['RELEASE_MIGRATION_CONFIG_FILE']=old_path
    # A failed rehearsal retains its database; main is upgraded only after success.
    command.upgrade(Config(str(ROOT/'alembic.ini')),'head')
    with connect(bootstrap) as conn: configure_database(conn)
    if database_snapshot(bootstrap,before)!=before: raise RuntimeError('Main upgrade changed original data')
    check=Database(runtime); assert check.ready(); check.close()
    with connect(bootstrap,autocommit=True) as conn:
        assert database=='release_state_restore_monitoring_'+suffix
        conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
    result={'passed':True,'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
        'from_revision':previous,'to_revision':'0003_monitoring','restored_copy_checked_before_main':True,
        'original_tables_identical':before,'restricted_runtime_ready':True,'disposable_copy_removed':True,
        'backup':archive.relative_to(ROOT).as_posix(),'backup_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
    (ROOT/'docs/evidence/monitoring-migration.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'passed':True,'original_tables_verified':len(before),'backup':result['backup']}))


if __name__=='__main__': main()
