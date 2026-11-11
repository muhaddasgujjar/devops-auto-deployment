"""Quiesced platform bundle and isolated restoration; never overwrite the lab."""
import argparse
import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
import tarfile
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path

import httpx
from psycopg import sql
from sqlalchemy.engine import make_url

from backend.backup import backup,restore
from backend.security import TABLES,connect,load_url,private_json
from scripts.backend_runtime import CONFIG,SECRET_ROOT
from scripts.render_release import ROOT

GIT='/var/lib/release-lab/git/environment.git'
KUBE=['kubectl','--kubeconfig',str(ROOT/'output/lab.kubeconfig'),'--context=k3d-release-lab','--request-timeout=15s']
FILES={'database.dump','environment.bundle','configuration.tar','prometheus.tar','receiver.sqlite3'}


def run(*args): return subprocess.check_output(args,text=True,stderr=subprocess.PIPE,timeout=120).strip()
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value): path.write_text(json.dumps(value,indent=2,default=str)+'\n'); path.chmod(0o600)
def location(path):
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def database_snapshot(url,tables=None):
    result={}
    with connect(url) as conn:
        for table in tables or TABLES:
            if table=='alembic_version' or not conn.execute('SELECT to_regclass(%s)',('public.'+table,)).fetchone()[0]: continue
            rows=conn.execute(sql.SQL('SELECT row_to_json(t) FROM {} t').format(sql.Identifier(table))).fetchall()
            encoded=sorted(json.dumps(row[0],sort_keys=True,separators=(',',':'),default=str) for row in rows)
            result[table]={'count':len(encoded),'sha256':hashlib.sha256('\n'.join(encoded).encode()).hexdigest()}
    return result


def refs(repository):
    return run('git','--git-dir',str(repository),'for-each-ref','--format=%(refname) %(objectname)').splitlines()


def quiet():
    for service in ('release-state-api','release-state-collector','release-state-recovery','release-state-notifier','release-notification-receiver'):
        state=run('systemctl','show',service,'-p','ActiveState','--value')
        if state not in ('inactive','failed'): raise RuntimeError('Stop platform writers and receiver before backup')
    for name in ('release-agent','release-jenkins'):
        item=json.loads(run('docker','inspect',name))[0]
        if item['Config'].get('Labels',{}).get('release-lab.managed')!='true' or item['State']['Running']:
            raise RuntimeError('Stop the managed CI publishers before backup')


def prometheus(path,method='get'):
    prefix='/api/v1/namespaces/monitoring/services/prometheus:9090/proxy'
    if method=='post':
        result=subprocess.run(KUBE+['create','--raw',prefix+path,'-f','-'],input='{}',capture_output=True,text=True,timeout=30)
        if result.returncode: raise RuntimeError('Prometheus snapshot API rejected')
        return json.loads(result.stdout)
    return json.loads(run(*KUBE,'get','--raw',prefix+path))


def create_bundle():
    quiet(); folder=Path('/var/lib/release-lab/platform-backups')/uuid.uuid4().hex[:12]
    folder.mkdir(mode=0o700,parents=True,exist_ok=False)
    before=database_snapshot(load_url('RELEASE_BOOTSTRAP_CONFIG_FILE')); git_refs=refs(GIT)
    backup(folder/'database.dump')
    run('git','--git-dir',GIT,'bundle','create',str(folder/'environment.bundle'),'--all')
    source=run('git','-C',str(ROOT),'rev-parse','HEAD')
    if run('git','-C',str(ROOT),'status','--porcelain','--','backend','frontend','platform','ci','scripts',
           ':(top,glob)*.json',':(top,glob)*.txt',':(top,glob)*.lock','alembic.ini'):
        raise RuntimeError('Commit the reviewed platform configuration before backup')
    with (folder/'configuration.tar').open('xb') as stream:
        subprocess.run(['git','-C',str(ROOT),'archive','--format=tar',source],stdout=stream,check=True)
    inbox=Path('/var/lib/release-notification-receiver/inbox.sqlite3')
    if not inbox.exists(): raise RuntimeError('Initialize the real local receiver before platform backup')
    with sqlite3.connect(inbox) as origin,sqlite3.connect(folder/'receiver.sqlite3') as destination: origin.backup(destination)
    stamp=int(time.time())-15
    query='/api/v1/query?query=demo_requests_total%7Bnamespace%3D%22demo-dev%22%7D&time='+str(stamp)
    data=prometheus(query)
    if data.get('status')!='success' or not data['data']['result']: raise RuntimeError('Need retained workload samples before snapshot')
    snapshot=prometheus('/api/v1/admin/tsdb/snapshot?skip_head=false','post')
    name=snapshot.get('data',{}).get('name','')
    if snapshot.get('status')!='success' or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',name): raise RuntimeError('Invalid Prometheus snapshot identity')
    pod=json.loads(run(*KUBE,'get','pods','-n','monitoring','-l','app=prometheus','-o','json'))['items'][0]['metadata']['name']
    with (folder/'prometheus.tar').open('xb') as stream:
        subprocess.run(KUBE+['exec','-n','monitoring',pod,'--','tar','-C','/prometheus/snapshots/'+name,'-cf','-','.'],stdout=stream,check=True,timeout=120)
    if database_snapshot(load_url('RELEASE_BOOTSTRAP_CONFIG_FILE'))!=before or refs(GIT)!=git_refs:
        raise RuntimeError('A source writer changed state during the quiesced backup')
    for item in folder.iterdir(): item.chmod(0o600)
    manifest={'format':1,'source_commit':source,'created_at_utc':datetime.now(timezone.utc).isoformat(),
        'database':before,'git_refs':git_refs,'git_head':run('git','--git-dir',GIT,'symbolic-ref','HEAD'),
        'prometheus_query':query,'prometheus_result':data['data']['result'],
        'prometheus_snapshot':name,'sha256':{name:digest(folder/name) for name in sorted(FILES)},
        'scope':'Quiesced API/CI writers; consistent PostgreSQL, immutable Git refs, SQLite backup and Prometheus head-inclusive snapshot. Runtime credentials are excluded.'}
    write(folder/'manifest.json',manifest)
    write(ROOT/'docs/evidence/platform-backup.json',{'passed':True,
        'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'backup':location(folder),
        'manifest_sha256':digest(folder/'manifest.json'),'sha256':manifest['sha256'],
        'configuration_source_commit':source,'database_tables':before,'git_refs':git_refs,
        'prometheus_snapshot':name,'historical_series':len(data['data']['result']),
        'writers_quiesced':True,'runtime_credentials_included':False})
    # Only this newly created, validated snapshot directory is removed after its
    # archive is complete; the retained TSDB and all other snapshots are untouched.
    run(*KUBE,'exec','-n','monitoring',pod,'--','rm','-r','--','/prometheus/snapshots/'+name)
    return folder,manifest


def verified(folder):
    folder=Path(folder).resolve(); manifest=json.loads((folder/'manifest.json').read_text())
    if manifest['format']!=1 or set(manifest['sha256'])!=FILES: raise ValueError('Unexpected platform archive file list')
    for name,expected in manifest['sha256'].items():
        if (folder/name).is_symlink() or digest(folder/name)!=expected: raise ValueError('Platform archive hash mismatch: '+name)
    return manifest


def extract(archive,destination):
    destination.mkdir(mode=0o700)
    with tarfile.open(archive) as content:
        for member in content.getmembers():
            value=Path(member.name)
            if value.is_absolute() or '..' in value.parts or member.issym() or member.isdev():
                raise ValueError('Unsafe archive entry')
        content.extractall(destination,filter='data')


def restore_bundle(folder):
    folder=Path(folder).resolve(); manifest=verified(folder); quiet()
    suffix=uuid.uuid4().hex[:12]; target=Path('/var/lib/release-lab/platform-restores')/suffix
    target.mkdir(parents=True,mode=0o700,exist_ok=False)
    database='release_state_restore_platform_'+suffix; container='release-platform-restore-'+suffix
    bootstrap=load_url('RELEASE_BOOTSTRAP_CONFIG_FILE'); before=database_snapshot(bootstrap); original_refs=refs(GIT)
    restored_url=make_url(bootstrap).set(database=database).render_as_string(hide_password=False)
    restore(folder/'database.dump',database)
    if database_snapshot(restored_url)!=manifest['database']: raise RuntimeError('Restored database identities/content differ')
    run('git','clone','--bare',str(folder/'environment.bundle'),str(target/'environment.git'))
    if refs(target/'environment.git')!=manifest['git_refs']: raise RuntimeError('Restored Git refs differ')
    if run('git','--git-dir',str(target/'environment.git'),'symbolic-ref','HEAD')!=manifest['git_head']:
        raise RuntimeError('Restored default Git branch differs')
    run('git','--git-dir',str(target/'environment.git'),'fsck','--full')
    extract(folder/'configuration.tar',target/'configuration')
    extract(folder/'prometheus.tar',target/'prometheus')
    for parent,dirs,files in os.walk(target/'prometheus'):
        os.chown(parent,65534,65534); os.chmod(parent,0o755)
        for name in files: os.chown(Path(parent)/name,65534,65534)
    config=target/'prometheus.yml'; config.write_text('global:\n  scrape_interval: 5s\nscrape_configs: []\n'); config.chmod(0o644)
    image=json.loads((target/'configuration/versions.json').read_text())['prometheus_image']
    run('docker','run','-d','--name',container,'--label','release-lab.restore='+suffix,'--memory=192m','--cpus=0.5',
        '--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--user','65534:65534',
        '--publish=127.0.0.1::9090','--mount','type=bind,src='+str(target/'prometheus')+',dst=/prometheus',
        '--mount','type=bind,src='+str(config)+',dst=/etc/prometheus/prometheus.yml,readonly',image,
        '--config.file=/etc/prometheus/prometheus.yml','--storage.tsdb.path=/prometheus')
    process=None
    try:
        inspected=json.loads(run('docker','inspect',container))[0]
        port=inspected['NetworkSettings']['Ports']['9090/tcp'][0]['HostPort']
        with httpx.Client(base_url='http://127.0.0.1:'+port,timeout=5,trust_env=False) as client:
            deadline=time.monotonic()+60
            while True:
                try:
                    if client.get('/-/ready').status_code==200: break
                except httpx.HTTPError: pass
                if time.monotonic()>deadline: raise RuntimeError('Restored Prometheus not ready')
                time.sleep(1)
            result=client.get(manifest['prometheus_query']).json()
            if sorted(result.get('data',{}).get('result',[]),key=lambda x:str(x['metric']))!=sorted(manifest['prometheus_result'],key=lambda x:str(x['metric'])):
                raise RuntimeError('Restored Prometheus does not reproduce retained historical samples')
        runtime=json.loads(CONFIG.read_text()); runtime['database_url']=make_url(runtime['database_url']).set(database=database).render_as_string(hide_password=False)
        private_json(target/'api.json',runtime)
        with socket.socket() as sock: sock.bind(('127.0.0.1',0)); api_port=sock.getsockname()[1]
        env={**os.environ,'RELEASE_CONFIG_FILE':str(target/'api.json'),'PYTHONDONTWRITEBYTECODE':'1'}
        process=subprocess.Popen(['/opt/release-lab/backend-venv/bin/python','-m','uvicorn','backend.api:create_app','--factory',
            '--host','127.0.0.1','--port',str(api_port),'--no-access-log'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        key=json.loads((SECRET_ROOT/'tokens.json').read_text())['admin']
        with httpx.Client(base_url='http://127.0.0.1:'+str(api_port),headers={'X-API-Key':key},timeout=5,trust_env=False) as client:
            deadline=time.monotonic()+30
            while True:
                try:
                    if client.get('/health/ready').status_code==200: break
                except httpx.HTTPError: pass
                if process.poll() is not None or time.monotonic()>deadline: raise RuntimeError('Isolated restored API not ready')
                time.sleep(.5)
            state=client.get('/environment'); incidents=client.get('/recoveries?limit=100'); monitor=client.get('/monitoring'); audit=client.get('/audit?limit=100')
            for response in (state,incidents,monitor,audit): response.raise_for_status()
        with sqlite3.connect(folder/'receiver.sqlite3') as conn:
            receipts=conn.execute('SELECT id,sha256,payload FROM receipts ORDER BY id').fetchall()
        copy=target/'receiver.sqlite3'
        with sqlite3.connect(folder/'receiver.sqlite3') as origin,sqlite3.connect(copy) as destination: origin.backup(destination)
        with sqlite3.connect(copy) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or conn.execute('SELECT id,sha256,payload FROM receipts ORDER BY id').fetchall()!=receipts:
                raise RuntimeError('Restored receiver receipts differ')
        if database_snapshot(restored_url)!=manifest['database'] or database_snapshot(bootstrap)!=before or refs(GIT)!=original_refs:
            raise RuntimeError('Restore changed source or restored durable state')
        report={'passed':True,'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'backup':location(folder),
            'manifest_sha256':digest(folder/'manifest.json'),'database_tables':manifest['database'],
            'git_refs_identical':True,'git_fsck_passed':True,'configuration_source_commit':manifest['source_commit'],
            'historical_prometheus_series_verified':len(manifest['prometheus_result']),'restored_prometheus_has_no_scrape_jobs':True,
            'receiver_receipts_verified':len(receipts),'independent_api':{'ready':True,'desired_id':state.json()['desired_release_id'],
                'stable_id':state.json()['stable_release_id'],'recoveries':len(incidents.json()),'monitoring_alerts':len(monitor.json()['alerts']),
                'audit_records_in_bounded_view':len(audit.json())},'source_unchanged':True,'restore_directory':str(target)}
    finally:
        if process is not None:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        if (target/'api.json').exists(): (target/'api.json').unlink()
        item=json.loads(run('docker','inspect',container))[0]
        if item['Config']['Labels'].get('release-lab.restore')!=suffix: raise RuntimeError('Unowned restore container')
        run('docker','stop','--timeout=10',container); run('docker','rm',container)
    # Only our freshly created isolated database is removed after all checks pass.
    with connect(bootstrap,autocommit=True) as conn:
        assert re.fullmatch(r'release_state_restore_platform_[a-f0-9]{12}',database)
        conn.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database)))
    report['disposable_database_and_processes_removed']=True
    write(ROOT/'docs/evidence/platform-restore.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['backup','restore']); parser.add_argument('--bundle',type=Path)
    args=parser.parse_args()
    if args.action=='backup':
        folder,_=create_bundle(); print(json.dumps({'backup':location(folder),'manifest_sha256':digest(folder/'manifest.json')}))
    else:
        if args.bundle is None: parser.error('restore requires --bundle')
        result=restore_bundle(args.bundle); print(json.dumps({'passed':result['passed'],'historical_series':result['historical_prometheus_series_verified']}))


if __name__=='__main__': main()
