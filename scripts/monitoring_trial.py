"""Real alert firing/resolution, local outage/replay and retained TSDB acceptance."""
import hashlib
import json
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime,timezone
from pathlib import Path

import httpx

from backend.collector import collect
from backend.monitoring import canonical
from backend.recovery_signals import Signals
from scripts.backend_runtime import SECRET_ROOT
from scripts.gitops_trial import Jenkins,queued_build_number
from scripts.render_release import ROOT


def command(*args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=45)
    if result.returncode: raise RuntimeError('Owned monitoring trial operation failed: '+args[0])
    return result.stdout.strip()


def main():
    folder=ROOT/'output'/('monitoring-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')); folder.mkdir()
    config=json.loads((SECRET_ROOT/'notification.json').read_text()); tokens=json.loads((SECRET_ROOT/'tokens.json').read_text())
    client=httpx.Client(base_url='http://127.0.0.1:8090',headers={'X-API-Key':tokens['admin']},timeout=10,trust_env=False)
    service=httpx.Client(base_url='http://127.0.0.1:8090',headers={'X-API-Key':config['api_key']},timeout=10,trust_env=False)
    receiver=httpx.Client(base_url=config['receiver_url'],headers={'Authorization':'Bearer '+config['receiver_token']},timeout=5,trust_env=False)
    signals=Signals(SECRET_ROOT/'recovery.kubeconfig')
    kubeconfig=ROOT/'output/lab.kubeconfig'; kube=['kubectl','--kubeconfig',str(kubeconfig),'--context=k3d-release-lab','--request-timeout=5s']
    def get(path):
        response=client.get(path); response.raise_for_status(); return response.json()
    def post(path,payload=None):
        response=service.post(path,json=payload); response.raise_for_status(); return response.json()
    def wait(check,seconds,message):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            try: result=check()
            except httpx.TransportError: result=None
            if result: return result
            time.sleep(2)
        raise TimeoutError(message)
    summary={'passed':False,'started_at_utc':datetime.now(timezone.utc).isoformat(),
        'observer_source':command('git','-C',str(ROOT),'rev-parse','HEAD'),
        'observer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    stop=threading.Event(); threads=[]; injected=[]; receiver_stopped=False; notifier_stopped=False
    def traffic(name,index):
        with (folder/(name+'-'+str(index)+'.jsonl')).open('w') as stream:
            while not stop.is_set():
                start=time.monotonic(); row=signals.probe('demo-'+name)
                stream.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'start':start,
                    'end':time.monotonic(),**row})+'\n'); stream.flush(); stop.wait(.05)
    def inbox():
        with sqlite3.connect('/var/lib/release-notification-receiver/inbox.sqlite3') as conn:
            return {row[0]:row[1] for row in conn.execute('SELECT id,sha256 FROM receipts')}
    def notification(identity): return next((row for row in get('/monitoring')['notifications'] if row['id']==identity),None)
    try:
        if command('systemctl','show','release-state-recovery','-p','ActiveState','--value')!='inactive':
            raise RuntimeError('Keep the recovery actuator stopped during the monitoring-only fault trial')
        baseline=signals.probe('demo-stable'); assert baseline['ok'] and baseline['mode']=='healthy'
        for name in ('stable','preview'):
            for i in range(4):
                thread=threading.Thread(target=traffic,args=(name,i),daemon=True); thread.start(); threads.append(thread)
        jenkins=Jenkins(); queue=jenkins.build('healthy','release-merged')
        number=wait(lambda:queued_build_number(jenkins.json(queue+'api/json')),120,'Origin build not queued')
        print('Monitoring trial: healthy Jenkins build '+str(number),flush=True)
        build=wait(lambda:(lambda row:row if not row['building'] else None)(jenkins.json(f'job/release-merged/{number}/api/json')),900,'Origin CI timed out')
        assert build['result']=='SUCCESS'
        (folder/'jenkins-build.json').write_text(json.dumps(build,indent=2))
        (folder/'jenkins-console.txt').write_bytes(jenkins.request(f'job/release-merged/{number}/consoleText')[0])
        for name in ('source.json','scan.json','sbom.json','image-inspect.json','environment-commit.json'):
            (folder/name).write_bytes(jenkins.request(f'job/release-merged/{number}/artifact/output/{name}')[0])
        publication=json.loads((folder/'environment-commit.json').read_text()); summary['publication']=publication
        scan=json.loads((folder/'scan.json').read_text()); image=json.loads((folder/'image-inspect.json').read_text())[0]
        assert scan['Metadata']['ImageID']==image['Id'] and publication['image'] in image['RepoDigests']
        assert image['Config']['User']=='10001:10001'
        assert not any(v.get('Severity') in ('HIGH','CRITICAL') for row in scan['Results'] for v in row.get('Vulnerabilities',[]))
        command('/opt/release-lab/venv/bin/python','-m','scripts.integration_runtime','stop')
        command(*kube,'annotate','application','release-demo-dev','-n','argocd','argocd.argoproj.io/refresh=hard','--overwrite')
        def promoted():
            env=get('/environment')
            return env if env.get('desired') and env['desired']['build']['number']==number and env['desired']['status']=='promoted' and env['freshness']=='current' else None
        state=wait(promoted,420,'Healthy origin not promoted')
        observed=collect(kubeconfig,Path('/var/lib/release-lab/git/environment.git'))
        assert observed.status=='promoted' and observed.environment_commit==publication['environment_commit']
        assert signals.probe('demo-stable')['ok']
        summary['healthy_before_fault']=state
        # Let startup notifications drain, then fail only the local receiver.
        wait(lambda: get('/monitoring')['fresh'] and all(x['state']=='delivered' for x in get('/monitoring')['notifications']),90,'Startup delivery did not settle')
        before_ids=set(inbox()); command('systemctl','stop','release-notification-receiver'); receiver_stopped=True
        pods=json.loads(command(*kube,'get','pods','-n','demo-dev','-l','app=release-demo,rollouts-pod-template-hash='+observed.stable_hash,'-o','json'))['items']
        assert len(pods)==2
        revision=publication['source_commit']+'-'+publication['release_id']
        for pod in pods:
            assert next(e['value'] for e in pod['spec']['containers'][0]['env'] if e['name']=='APP_REVISION')==revision
            command(*kube,'exec','-n','demo-dev',pod['metadata']['name'],'--','python','-c','from pathlib import Path; Path("/fault/mode").write_text("error")')
            injected.append(pod['metadata']['name'])
        summary['fault_injected_at']=datetime.now(timezone.utc).isoformat()
        print('Promoted origin faulted; local receiver is stopped',flush=True)
        subject='DemoRequestErrors:'+observed.stable_hash
        def firing():
            return next((x for x in get('/monitoring')['alerts'] if x['kind']=='workload_signal' and x['subject']==subject and x['state']=='firing'),None)
        alert=wait(firing,150,'Real Prometheus error alert did not fire')
        def failed_delivery():
            return next((x for x in get('/monitoring')['notifications'] if x['payload'].get('alert_id')==alert['id'] and x['payload']['state']=='firing' and x['attempts']>=1 and x['state']=='pending'),None)
        pending=wait(failed_delivery,20,'Receiver outage did not retain pending retry')
        pid=command('systemctl','show','release-state-notifier','-p','MainPID','--value')
        command('systemctl','stop','release-state-notifier'); notifier_stopped=True
        command('systemctl','start','release-notification-receiver'); receiver_stopped=False
        wait(lambda:receiver.get('/health/live').status_code==200,20,'Receiver not ready')
        # Re-enact the uncertain ACK boundary with the real restricted API and
        # real receiver, while the service is stopped. Do not submit a result.
        claimed=wait(lambda:post('/notifications/claim'),30,'Pending notification did not become due')
        assert claimed['id']==pending['id']
        ack=receiver.post('/notifications',content=canonical(claimed['payload']),headers={'Content-Type':'application/json','Idempotency-Key':claimed['id']})
        ack.raise_for_status(); assert ack.json()=={'id':claimed['id'],'sha256':claimed['payload_sha256']}
        assert notification(claimed['id'])['state']=='leased'
        command('systemctl','restart','release-notification-receiver')
        command('systemctl','start','release-state-notifier'); notifier_stopped=False
        wait(lambda:notification(claimed['id'])['state']=='delivered',90,'Expired-lease replay did not deliver')
        assert inbox()[claimed['id']]==claimed['payload_sha256']
        summary['outage_replay']={'notification_id':claimed['id'],'receiver_ack':ack.json(),
            'outage_attempts':pending['attempts'],'manual_ack_attempt':claimed['attempts'],
            'delivered_attempts':notification(claimed['id'])['attempts'],
            'previous_pid':pid,'new_pid':command('systemctl','show','release-state-notifier','-p','MainPID','--value'),
            'receiver_restarted':True,'one_inbox_entry':True,'scope':'Real ACK received, result intentionally omitted, then service restarted and lease expired normally'}
        assert summary['outage_replay']['previous_pid']!=summary['outage_replay']['new_pid']
        print('Local outage and uncertain ACK replay passed without duplicate inbox entry',flush=True)
        for name in injected:
            command(*kube,'exec','-n','demo-dev',name,'--','python','-c','from pathlib import Path; Path("/fault/mode").unlink(missing_ok=True)')
        injected.clear()
        wait(lambda:next((x for x in get('/monitoring')['alerts'] if x['id']==alert['id'] and x['state']=='resolved'),None),150,'Error alert did not resolve after healthy traffic')
        def resolved_delivery():
            return next((x for x in get('/monitoring')['notifications'] if x['payload'].get('alert_id')==alert['id'] and x['payload']['state']=='resolved' and x['state']=='delivered'),None)
        resolved=wait(resolved_delivery,30,'Resolution notification did not deliver')
        assert resolved['id'] in inbox()
        summary['alert_id']=alert['id']; summary['resolved_notification_id']=resolved['id']
        # Exact historical samples must survive replacement, not merely new scrapes.
        stamp=int(time.time())-15; query='/api/v1/query?query=demo_requests_total%7Bnamespace%3D%22demo-dev%22%7D&time='+str(stamp)
        path='/api/v1/namespaces/monitoring/services/prometheus:9090/proxy'
        previous=signals.raw(path+query)['data']['result']; assert previous
        pod=json.loads(command(*kube,'get','pods','-n','monitoring','-l','app=prometheus','-o','json'))['items'][0]
        pvc=json.loads(command(*kube,'get','pvc','prometheus-data','-n','monitoring','-o','json'))
        pv=json.loads(command(*kube,'get','pv','release-lab-prometheus','-o','json'))
        assert pvc['status']['phase']=='Bound' and pv['spec']['persistentVolumeReclaimPolicy']=='Retain'
        command(*kube,'delete','pod',pod['metadata']['name'],'-n','monitoring','--wait=false')
        def replaced():
            items=json.loads(command(*kube,'get','pods','-n','monitoring','-l','app=prometheus','-o','json'))['items']
            return next((x for x in items if x['metadata']['uid']!=pod['metadata']['uid'] and any(c['type']=='Ready' and c['status']=='True' for c in x.get('status',{}).get('conditions',[]))),None)
        new_pod=wait(replaced,120,'Replacement monitoring pod not ready')
        after=signals.raw(path+query)['data']['result']
        assert sorted(previous,key=lambda x:str(x['metric']))==sorted(after,key=lambda x:str(x['metric']))
        assert json.loads(command(*kube,'get','pvc','prometheus-data','-n','monitoring','-o','json'))['metadata']['uid']==pvc['metadata']['uid']
        summary['persistence']={'old_pod_uid':pod['metadata']['uid'],'new_pod_uid':new_pod['metadata']['uid'],
            'pvc_uid':pvc['metadata']['uid'],'pv_uid':pv['metadata']['uid'],'reclaim_policy':'Retain',
            'query':query,'historical_result':previous,'historical_result_after':after,'historical_series_verified':len(previous),
            'storage_request':'1Gi','retention_time':'24h','retention_size':'512MB',
            'disk_usage_kib':int(command(*kube,'exec','-n','monitoring',new_pod['metadata']['name'],'--','du','-sk','/prometheus').split()[0])}
        wait(lambda: get('/monitoring')['fresh'] and get('/monitoring')['probe']['telemetry_available'],30,'Probe did not recover')
        wait(lambda:all(x['state']=='delivered' for x in get('/monitoring')['notifications']),90,'Final notification queue did not drain')
        summary['final_monitoring']=get('/monitoring'); summary['final_environment']=get('/environment')
        assert summary['final_environment']['desired']['environment_commit']==publication['environment_commit']
        assert command('git','--git-dir','/var/lib/release-lab/git/environment.git','rev-parse','main')==publication['environment_commit']
        summary['new_receiver_receipts']=len(set(inbox())-before_ids)
        summary['final_http']=signals.probe('demo-stable'); assert summary['final_http']['ok'] and summary['final_http']['mode']=='healthy'
        summary['passed']=True
    except Exception as error:
        summary['failure_type']=type(error).__name__; raise
    finally:
        stop.set()
        for thread in threads: thread.join(timeout=7)
        for name in injected:
            subprocess.run(kube+['exec','-n','demo-dev',name,'--','python','-c','from pathlib import Path; Path("/fault/mode").unlink(missing_ok=True)'],capture_output=True,timeout=15)
        if receiver_stopped: command('systemctl','start','release-notification-receiver')
        if notifier_stopped: command('systemctl','start','release-state-notifier')
        summary['finished_at_utc']=datetime.now(timezone.utc).isoformat()
        summary['artifact_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
        (folder/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        client.close(); service.close(); receiver.close(); signals.client.close()
        print(json.dumps({'passed':summary['passed'],'raw_trial':folder.relative_to(ROOT).as_posix()}),flush=True)


if __name__=='__main__': main()
