"""Independently check raw post-promotion trials, Git lineage and serving proof."""
import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from backend.recovery_policy import POLICY
from backend.security import connect
from scripts.backend_runtime import CONFIG
from scripts.render_release import ROOT


def manifest(digest):
    assert re.fullmatch('sha256:[a-f0-9]{64}',digest)
    request=Request('http://127.0.0.1:5001/v2/release-demo/manifests/'+digest,headers={
        'Accept':'application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json'})
    with urlopen(request,timeout=10) as response:
        raw=response.read()
        assert response.headers['Docker-Content-Digest']==digest=='sha256:'+hashlib.sha256(raw).hexdigest()
    result=json.loads(raw)
    if 'manifests' in result:
        children=[m for m in result['manifests'] if m.get('platform',{}).get('os')=='linux' and m.get('platform',{}).get('architecture')=='amd64']
        assert len(children)==1
        return manifest(children[0]['digest'])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial',action='append',required=True)
    parser.add_argument('--failed-trial',action='append',default=[])
    args=parser.parse_args()
    trials=[]; git='/var/lib/release-lab/git/environment.git'
    def revision(*args): return subprocess.check_output(['git','--git-dir',git,*args],text=True).strip()
    settings=json.loads(CONFIG.read_text())
    for name in args.trial:
        folder=ROOT/name; summary=json.loads((folder/'summary.json').read_text())
        assert summary['passed'] is True
        for artifact,digest in summary['artifact_sha256'].items():
            assert hashlib.sha256((folder/artifact).read_bytes()).hexdigest()==digest, artifact
        observer=subprocess.check_output(['git','-C',str(ROOT),'show',summary['observer_source']+':scripts/recovery_trial.py'])
        assert hashlib.sha256(observer).hexdigest()==summary['observer_sha256'], 'Uncommitted trial observer'
        publication=summary['origin_publication']; incident=summary['incident']; target=incident['target']
        assert incident['phase']=='recovered' and incident['outcome']=='healthy_target_verified'
        assert incident['base_commit']==publication['environment_commit']
        assert revision('rev-parse',incident['recovery_commit']+'^')==incident['base_commit']
        marker='metadata/recoveries/'+incident['id']+'.json'
        assert revision('log','--format=%H','main','--',marker).splitlines()==[incident['recovery_commit']]
        changed=set(revision('diff','--name-only',incident['base_commit'],incident['recovery_commit']).splitlines())
        assert changed=={'environments/dev/rollout.yaml',marker}
        recorded=json.loads(revision('show',incident['recovery_commit']+':'+marker))
        assert recorded['target_release_id']==target['id'] and recorded['image']==target['artifact']['image']
        assert target['artifact']['reported_high_critical']==0 and target['artifact']['scanned_image_id']
        assert any(a['phase']=='Successful' for a in target['analyses'])
        assert any(o['quality']=='accepted' and o['stable_requests']>=100 and o['stable_non_200']==0 for o in target['observations'])
        assert summary['final_environment']['desired']['id']!=target['id'], 'Original deployment was overwritten'
        assert summary['final_environment']['desired']['recovery_id']==incident['id']
        assert summary['final_observation']['stable_image']==target['artifact']['image']
        assert summary['final_http']['status']==200 and summary['final_http']['mode']=='healthy'
        rows=[json.loads(line) for line in (folder/'stable.jsonl').read_text().splitlines()]
        offsets=[datetime.fromisoformat(r['timestamp']).timestamp()-r['completed_monotonic_seconds'] for r in rows]
        assert max(offsets)-min(offsets)<=2, 'Host clock changed during the trial'
        gaps=[b['client_monotonic_seconds']-a['client_monotonic_seconds'] for a,b in zip(rows,rows[1:])]
        assert len(rows)>=100 and 0<=min(gaps) and max(gaps)<=10
        expected=target['build']['source_commit']+'-jenkins-'+str(target['build']['number'])
        assert all(row['status']==200 and row['revision']==expected for row in rows[-100:])
        assert summary['promoted_before_fault']['http']['status']==200
        scan=json.loads((folder/'scan.json').read_text()); image=json.loads((folder/'image-inspect.json').read_text())[0]
        assert scan['Metadata']['ImageID']==image['Id'] and publication['image'] in image['RepoDigests']
        assert not any(v.get('Severity') in ('HIGH','CRITICAL') for r in scan['Results'] for v in r.get('Vulnerabilities',[]))
        assert image['Config']['User']=='10001:10001'
        assert summary['tests_in_origin_snapshot']>=56
        image_digest=publication['image'].split('@')[1]; body=manifest(image_digest)
        with connect(settings['database_url']) as conn:
            actors=conn.execute('SELECT r.phase,e.actor,e.source FROM recovery_events r JOIN incoming_events e ON e.id=r.event_id '
                               'WHERE r.recovery_id=%s ORDER BY r.created_at,r.id',(incident['id'],)).fetchall()
        assert [a[0] for a in actors]==['proposed','applying','verifying','recovered']
        assert all(actor.startswith('api:recovery:') or (phase=='verifying' and actor=='signed-collector') for phase,actor,source in actors)
        proof=next(e['data']['evidence'] for e in incident['events'] if e['phase']=='recovered')
        assert proof['requests']>=100 and proof['target_requests']==proof['requests']
        assert proof['non_200']==proof['identity_mismatches']==0 and proof['maximum_gap_seconds']<=10
        assert proof['environment_commit']==incident['recovery_commit']
        if summary['fault']=='error':
            gap=summary['telemetry_gap']; restart=summary['writer_restart']
            assert len(gap['unavailable_windows'])>=3 and gap['incidents_while_unavailable']==0 and gap['permission_restored']
            assert restart['previous_pid']!=restart['new_pid'] and restart['restarts']>=1
        trials.append({'fault':summary['fault'],'origin_build':summary['jenkins_build'],'target_build':target['build']['number'],
            'published_source_commit':publication['source_commit'],'observer_source_commit':summary['observer_source'],
            'incident_id':incident['id'],'phases':[a[0] for a in actors],'phase_actors':[{'phase':p,'actor':a,'source':s} for p,a,s in actors],
            'base_commit':incident['base_commit'],'recovery_commit':incident['recovery_commit'],'recovery_commits':1,
            'origin_image':publication['image'],'origin_oci_config_digest':body['config']['digest'],
            'target_image':target['artifact']['image'],'independent_http':summary['independent_http'],
            'detection_seconds':summary['detection_seconds'],'fault_to_verified_seconds':summary['fault_to_verified_seconds'],
            'telemetry_gap':summary.get('telemetry_gap'),'writer_restart':summary.get('writer_restart'),
            'actual_verification_requests':proof['requests'],'raw_trial':folder.relative_to(ROOT).as_posix(),
            'summary_sha256':hashlib.sha256((folder/'summary.json').read_bytes()).hexdigest()})
    assert len(trials)==2 and {t['fault'] for t in trials}=={'error','latency'}
    failed=[]
    for name in args.failed_trial:
        folder=ROOT/name; summary=json.loads((folder/'summary.json').read_text())
        assert summary['passed'] is False
        for artifact,digest in summary['artifact_sha256'].items():
            assert hashlib.sha256((folder/artifact).read_bytes()).hexdigest()==digest
        rows=[json.loads(line) for line in (folder/'stable.jsonl').read_text().splitlines()]
        offsets=[datetime.fromisoformat(r['timestamp']).timestamp()-r.get('completed_monotonic_seconds',r['client_monotonic_seconds']) for r in rows]
        span=max(offsets)-min(offsets)
        failed.append({'raw_trial':name,'origin_build':summary.get('jenkins_build'),
            'outcome':summary.get('incident',{}).get('outcome'),'counted_as_success':False,
            'clock_offset_span_seconds':round(span,3),'clock_discontinuity':span>2,
            'summary_sha256':hashlib.sha256((folder/'summary.json').read_bytes()).hexdigest()})
    result={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'passed':True,'policy':POLICY,'trials':trials,
            'failed_attempts':failed,
            'limitations':['Two local functional trials, not a repeated benchmark or production availability result',
                'Error trial includes a deliberate telemetry gap and writer restart; timings include those injections',
                'No-target, Git failure, timeout, competing writers and uncertain publication replay are exercised separately in real PostgreSQL/temporary Git tests',
                'Initial CI discovery uses the existing manual Argo refresh; recovery discovery uses ordinary controller polling']}
    (ROOT/'docs/evidence/recovery-acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'passed':True,'trials':len(trials),'origin_builds':[t['origin_build'] for t in trials]}))


if __name__=='__main__': main()
