"""Correlate committed observer, real HTTP streams, immutable events and inbox."""
import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
from datetime import datetime,timezone

from backend.monitoring import canonical
from backend.security import connect,load_url
from scripts.render_release import ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--trial',required=True); args=parser.parse_args()
    folder=(ROOT/args.trial).resolve(); assert folder.is_relative_to(ROOT/'output')
    summary=json.loads((folder/'summary.json').read_text()); assert summary['passed']
    for name,digest in summary['artifact_sha256'].items():
        assert (folder/name).parent==folder and hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest
    source=summary['observer_source']; assert re.fullmatch('[a-f0-9]{40}',source)
    observer=subprocess.check_output(['git','-C',str(ROOT),'show',source+':scripts/monitoring_trial.py'])
    assert hashlib.sha256(observer).hexdigest()==summary['observer_sha256']
    scan=json.loads((folder/'scan.json').read_text()); image=json.loads((folder/'image-inspect.json').read_text())[0]
    publication=summary['publication']
    assert scan['Metadata']['ImageID']==image['Id'] and publication['image'] in image['RepoDigests']
    assert image['Config']['User']=='10001:10001'
    assert not any(v.get('Severity') in ('HIGH','CRITICAL') for r in scan['Results'] for v in r.get('Vulnerabilities',[]))
    assert json.loads((folder/'source.json').read_text())['source_commit']==publication['source_commit']
    counts=re.findall(r'Ran (\d+) tests',(folder/'jenkins-console.txt').read_text()); assert counts and int(counts[-1])>=56
    rows=[json.loads(line) for path in folder.glob('stable-*.jsonl') for line in path.read_text().splitlines()]
    rows.sort(key=lambda r:r['start']); assert len(rows)>=100
    gaps=[b['start']-a['start'] for a,b in zip(rows,rows[1:])]; assert max(gaps)<=10
    offsets=[datetime.fromisoformat(r['at']).timestamp()-r['end'] for r in rows]; span=max(offsets)-min(offsets); assert span<=2
    revision=publication['source_commit']+'-'+publication['release_id']
    fault_samples=sum(r['status']==500 and r['revision']==revision for r in rows); assert fault_samples>0
    assert all(r['status']==200 and r['revision']==revision and r['mode']=='healthy' for r in rows[-100:])
    persist=summary['persistence']; assert persist['old_pod_uid']!=persist['new_pod_uid']
    assert persist['reclaim_policy']=='Retain' and persist['historical_series_verified']>0
    assert sorted(persist['historical_result'],key=lambda x:str(x['metric']))==sorted(persist['historical_result_after'],key=lambda x:str(x['metric']))
    replay=summary['outage_replay']; assert replay['previous_pid']!=replay['new_pid']
    assert replay['delivered_attempts']>replay['manual_ack_attempt']>=2 and replay['delivered_attempts']<=5
    with connect(load_url('RELEASE_CONFIG_FILE')) as conn:
        transitions=conn.execute('SELECT e.state,e.generation,e.actor,o.id,o.payload,o.payload_sha256,o.state,o.attempts '
            'FROM monitoring_events e JOIN notification_outbox o ON o.event_id=e.id WHERE e.alert_id=%s ORDER BY o.sequence',
            (summary['alert_id'],)).fetchall()
        events=conn.execute('SELECT attempt,phase,data FROM notification_events WHERE notification_id=%s ORDER BY created_at,id',
            (replay['notification_id'],)).fetchall()
    assert [r[0] for r in transitions]==['firing','resolved'] and all(r[1]==1 for r in transitions)
    assert all(r[2].startswith('api:notifier:') and r[6]=='delivered' for r in transitions)
    with sqlite3.connect('/var/lib/release-notification-receiver/inbox.sqlite3') as conn:
        for state,generation,actor,identity,payload,digest,delivery,attempts in transitions:
            received=conn.execute('SELECT sha256,payload FROM receipts WHERE id=?',(identity,)).fetchall()
            assert len(received)==1 and received[0][0]==digest==hashlib.sha256(canonical(payload)).hexdigest()
            assert json.loads(received[0][1])==payload
    assert any(phase=='retry' for attempt,phase,data in events) and any(phase=='expired' for attempt,phase,data in events)
    assert sum(phase=='delivered' for attempt,phase,data in events)==1
    assert summary['final_environment']['desired']['id']==summary['final_environment']['stable']['id']
    assert summary['final_environment']['desired']['environment_commit']==publication['environment_commit']
    head=subprocess.check_output(['git','--git-dir','/var/lib/release-lab/git/environment.git','rev-parse','main'],text=True).strip()
    assert head==publication['environment_commit']
    result={'passed':True,'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'raw_trial':args.trial,
        'observer_source_commit':source,'origin_source_commit':publication['source_commit'],
        'origin_build':summary['healthy_before_fault']['desired']['build']['number'],'image':publication['image'],
        'reported_high_critical':0,'core_tests_in_origin':int(counts[-1]),'actual_fault_samples':fault_samples,
        'stable_requests':len(rows),'maximum_sample_gap_seconds':round(max(gaps),6),'clock_offset_span_seconds':round(span,6),
        'final_100_matching_healthy_200':True,'alert_id':summary['alert_id'],
        'alert_transitions':[{'state':r[0],'generation':r[1],'actor':r[2],'notification_id':r[3],'attempts':r[7]} for r in transitions],
        'firing_delivery_events':[{'attempt':a,'phase':p,'data':d} for a,p,d in events],
        'outage_replay':replay,'persistence':persist,'environment_git_unchanged_by_monitoring':True,
        'summary_sha256':hashlib.sha256((folder/'summary.json').read_bytes()).hexdigest(),
        'limitations':['One functional laptop experiment, not a benchmark or production availability result',
            'Uncertain receiver ACK is deliberately left unreported by a real client while the service is stopped; lease expiry/replay uses normal service behavior',
            'Recovery actuator remains stopped to isolate monitoring; monitoring cannot publish Git or mutate workloads',
            'Prometheus data survives a pod replacement on one retained local node; node loss requires the separate backup/restore proof']}
    (ROOT/'docs/evidence/monitoring-acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'passed':True,'stable_requests':len(rows),'fault_samples':fault_samples,'historical_series':persist['historical_series_verified']}))


if __name__=='__main__': main()
