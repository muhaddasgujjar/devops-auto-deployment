"""Promote healthy, inject a pod-local fault, observe autonomous Git recovery."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.collector import collect, execute, SourcesUnavailable
from backend.recovery_signals import Signals
from scripts.backend_runtime import SECRET_ROOT
from scripts.gitops_trial import Jenkins, queued_build_number
from scripts.render_release import ROOT


def command(*args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=30)
    if result.returncode:
        raise RuntimeError('Owned lab operation failed: '+args[0])
    return result.stdout.strip()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fault',choices=['error','latency'])
    parser.add_argument('--restart-writer',action='store_true')
    parser.add_argument('--stop-ci-after-build',action='store_true')
    args=parser.parse_args()
    folder=ROOT/'output'/('recovery-'+args.fault+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    folder.mkdir(parents=True,exist_ok=False)
    kubeconfig=ROOT/'output/lab.kubeconfig'
    kube=['kubectl','--kubeconfig',str(kubeconfig),'--context=k3d-release-lab','--request-timeout=5s']
    git='/var/lib/release-lab/git/environment.git'
    tokens=json.loads((SECRET_ROOT/'tokens.json').read_text())
    signals=Signals(SECRET_ROOT/'recovery.kubeconfig')
    client=httpx.Client(base_url='http://127.0.0.1:8090',headers={'X-API-Key':tokens['admin']},timeout=10,trust_env=False)
    def api(path):
        response=client.get(path); response.raise_for_status(); return response.json()
    stop=threading.Event(); threads=[]; injected=[]
    summary={'fault':args.fault,'passed':False,'started_at_utc':datetime.now(timezone.utc).isoformat(),
             'observer_source':command('git','-C',str(ROOT),'rev-parse','HEAD')}
    def traffic(service, filename):
        with (folder/filename).open('w') as stream:
            while not stop.is_set():
                stamp=time.monotonic(); row=signals.probe(service)
                stream.write(json.dumps({'timestamp':datetime.now(timezone.utc).isoformat(),
                    'client_monotonic_seconds':stamp,**row})+'\n'); stream.flush()
                stop.wait(.05)
    try:
        baseline=signals.probe('demo-stable')
        if not baseline['ok'] or baseline.get('mode')!='healthy':
            raise AssertionError('Establish a healthy serving baseline before post-promotion injection')
        summary['baseline_response']=baseline
        for service,name in [('demo-stable','stable.jsonl'),('demo-preview','preview.jsonl')]:
            thread=threading.Thread(target=traffic,args=(service,name),daemon=True); thread.start(); threads.append(thread)
        jenkins=Jenkins(); queue=jenkins.build('healthy','release-merged'); number=None
        deadline=time.monotonic()+1200
        while time.monotonic()<deadline:
            queued=jenkins.json(queue+'api/json'); number=queued_build_number(queued)
            if number: break
            if queued.get('cancelled'): raise RuntimeError('Jenkins build cancelled')
            time.sleep(2)
        if not number: raise TimeoutError('No Jenkins build started')
        summary['jenkins_build']=number
        print('Recovery trial: healthy Jenkins build '+str(number),flush=True)
        while time.monotonic()<deadline:
            build=jenkins.json(f'job/release-merged/{number}/api/json')
            if not build['building']:
                (folder/'jenkins-build.json').write_text(json.dumps(build,indent=2))
                (folder/'jenkins-console.txt').write_bytes(jenkins.request(f'job/release-merged/{number}/consoleText')[0])
                if build['result']!='SUCCESS': raise RuntimeError('Origin build did not pass CI')
                break
            time.sleep(3)
        else: raise TimeoutError('Origin build timed out')
        for name in ('source.json','scan.json','sbom.json','image-inspect.json','environment-commit.json'):
            (folder/name).write_bytes(jenkins.request(f'job/release-merged/{number}/artifact/output/{name}')[0])
        desired=json.loads((folder/'environment-commit.json').read_text()); summary['origin_publication']=desired
        scan=json.loads((folder/'scan.json').read_text())
        inspected=json.loads((folder/'image-inspect.json').read_text())[0]
        source=json.loads((folder/'source.json').read_text())
        assert scan['Metadata']['ImageID']==inspected['Id'] and desired['image'] in inspected['RepoDigests']
        assert inspected['Config']['User']=='10001:10001'
        assert source['source_commit']==desired['source_commit']
        assert 'APP_REVISION='+desired['source_commit']+'-'+desired['release_id'] in inspected['Config']['Env']
        assert not any(v.get('Severity') in ('HIGH','CRITICAL') for r in scan['Results'] for v in r.get('Vulnerabilities',[]))
        counts=re.findall(r'Ran (\d+) tests',(folder/'jenkins-console.txt').read_text())
        assert counts
        summary['tests_in_origin_snapshot']=int(counts[-1]); summary['reported_high_critical']=0
        if args.stop_ci_after_build:
            command('/opt/release-lab/venv/bin/python','-m','scripts.integration_runtime','stop')
        # Initial CI discovery uses the established local acceptance refresh.
        # Recovery itself receives no refresh/selector/rollout writes from this driver.
        command(*kube,'annotate','application','release-demo-dev','-n','argocd','argocd.argoproj.io/refresh=hard','--overwrite')
        expected_revision=desired['source_commit']+'-'+desired['release_id']
        deadline=time.monotonic()+480
        while time.monotonic()<deadline:
            state=api('/environment')
            if (state.get('desired') and state['desired']['build']['number']==number and
                state['desired']['environment_commit']==desired['environment_commit'] and
                state['desired']['status']=='promoted' and state['stable_revision']==expected_revision and state['freshness']=='current'):
                observation=collect(kubeconfig,Path(git))
                if observation.status=='promoted' and observation.environment_commit==desired['environment_commit']:
                    break
            time.sleep(3)
        else: raise TimeoutError('New healthy origin did not reach verified promotion')
        summary['promoted_before_fault']={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
            'environment':state,'observation':observation.model_dump(mode='json'),'http':signals.probe('demo-stable')}
        if not summary['promoted_before_fault']['http']['ok']: raise AssertionError('Origin was unhealthy before injection')
        pods=json.loads(command(*kube,'get','pods','-n','demo-dev','-l','app=release-demo,rollouts-pod-template-hash='+observation.stable_hash,'-o','json'))['items']
        if len(pods)!=2: raise AssertionError('Unexpected number of serving pods')
        for pod in pods:
            container=pod['spec']['containers'][0]
            revision=next(e['value'] for e in container['env'] if e['name']=='APP_REVISION')
            if revision!=expected_revision: raise AssertionError('Fault target differs from promoted origin')
            command(*kube,'exec','-n','demo-dev',pod['metadata']['name'],'--','python','-c',
                'from pathlib import Path; Path("/fault/mode").write_text("'+args.fault+'")')
            injected.append(pod['metadata']['name'])
        summary['fault_injected_at_utc']=datetime.now(timezone.utc).isoformat()
        injected_monotonic=time.monotonic()
        summary['injected_pods']=injected.copy()
        print('Origin promoted healthy; injected '+args.fault+' into its two serving pods',flush=True)
        deadline=time.monotonic()+850; incident=None; previous=None; restarted=False
        while time.monotonic()<deadline:
            incident=next((r for r in api('/recoveries') if r['origin']['id']==state['desired']['id']),None)
            if incident:
                if 'detection_seconds' not in summary:
                    summary['detection_seconds']=round(time.monotonic()-injected_monotonic,3)
                if incident['phase']!=previous:
                    print('Recovery '+incident['id'][:8]+': '+incident['phase'],flush=True); previous=incident['phase']
                if args.restart_writer and incident['phase']=='verifying' and not restarted:
                    before=command('systemctl','show','release-state-recovery','-p','MainPID','--value')
                    command('systemctl','kill','--signal=SIGKILL','--kill-whom=main','release-state-recovery')
                    summary['writer_restart']={'previous_pid':before}; restarted=True
                if incident['phase'] in ('recovered','failed','superseded'): break
            time.sleep(3)
        if not incident or incident['phase']!='recovered':
            if incident: summary['incident']=incident
            raise AssertionError('Recovery did not reach independently verified success')
        summary['incident']=incident
        if restarted:
            summary['writer_restart'].update(new_pid=command('systemctl','show','release-state-recovery','-p','MainPID','--value'),
                restarts=int(command('systemctl','show','release-state-recovery','-p','NRestarts','--value')))
            assert summary['writer_restart']['new_pid']!=summary['writer_restart']['previous_pid']
        final=collect(kubeconfig,Path(git)); final_state=api('/environment'); http=signals.probe('demo-stable')
        target=incident['target']; target_revision=target['build']['source_commit']+'-jenkins-'+str(target['build']['number'])
        assert final.environment_commit==incident['recovery_commit'] and final.status=='promoted'
        assert final.stable_revision==target_revision and final.stable_image==target['artifact']['image']
        assert http['ok'] and http['revision']==target_revision and http['mode']=='healthy'
        assert final_state['desired']['recovery_id']==incident['id']
        assert command('git','--git-dir',git,'rev-parse',incident['recovery_commit']+'^')==desired['environment_commit']
        marker='metadata/recoveries/'+incident['id']+'.json'
        commits=command('git','--git-dir',git,'log','--format=%H','main','--',marker).splitlines()
        assert commits==[incident['recovery_commit']], 'Duplicate recovery commit'
        summary.update(passed=True,final_observation=final.model_dump(mode='json'),final_environment=final_state,
                       final_http=http,recovery_git_commits=commits,finished_at_utc=datetime.now(timezone.utc).isoformat(),
                       fault_to_verified_seconds=round(time.monotonic()-injected_monotonic,3))
    except Exception as error:
        summary['failure_type']=type(error).__name__
        print(json.dumps({'passed':False,'failure_type':type(error).__name__,'raw_trial':folder.relative_to(ROOT).as_posix()}),flush=True)
        raise
    finally:
        stop.set()
        for thread in threads: thread.join(timeout=8)
        verification_error=None
        if summary['passed']:
            try:
                rows=[json.loads(line) for line in (folder/'stable.jsonl').read_text().splitlines()]
                gaps=[b['client_monotonic_seconds']-a['client_monotonic_seconds'] for a,b in zip(rows,rows[1:])]
                assert len(rows)>=100 and gaps and 0<=min(gaps) and max(gaps)<=10, 'Interrupted independent HTTP stream'
                affected=[r for r in rows if r['client_monotonic_seconds']>=injected_monotonic and r['revision']==expected_revision]
                assert any(r['status']==500 for r in affected) if args.fault=='error' else any(r['status']==200 and r['seconds']>=.5 for r in affected), 'Injected serving failure not observed'
                assert all(r['status']==200 and r['revision']==target_revision for r in rows[-100:]), 'Last 100 requests do not verify the accepted target'
                summary['independent_http']={'requests':len(rows),'non_200':sum(r['status']!=200 for r in rows),
                    'maximum_gap_seconds':round(max(gaps),4),'affected_revision_samples':len(affected),
                    'last_100_matching_target_200':True,'scope':'Finite functional experiment, not a production availability claim'}
            except (AssertionError,KeyError,ValueError) as error:
                summary['passed']=False; summary['excluded_reason']=str(error)
                verification_error=error
        # Remove only our own opt-in fault from surviving original pods. This is
        # test-injector cleanup, never an automated recovery or success claim.
        for name in injected:
            try:
                subprocess.run(kube+['exec','-n','demo-dev',name,'--','python','-c',
                    'from pathlib import Path; Path("/fault/mode").unlink(missing_ok=True)'],capture_output=True,timeout=15)
            except subprocess.TimeoutExpired:
                summary.setdefault('injector_cleanup_timeouts',[]).append(name)
        summary['artifact_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file() and p.name!='summary.json'}
        (folder/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
        client.close(); signals.client.close()
        if verification_error:
            raise AssertionError('Independent HTTP acceptance excluded this trial') from verification_error
        if summary['passed']:
            print(json.dumps({'passed':True,'fault':args.fault,'origin_build':number,'target_build':target['build']['number'],
                'recovery_commit':incident['recovery_commit'],'raw_trial':folder.relative_to(ROOT).as_posix()}),flush=True)


if __name__=='__main__': main()
