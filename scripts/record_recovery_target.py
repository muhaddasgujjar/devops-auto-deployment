"""Bind missing scan identity from the preserved, hash-verified healthy trial."""
import hashlib
import json
from datetime import datetime, timezone

from scripts.render_release import ROOT


def main():
    source=ROOT/'docs/evidence/runtime-failure-validation.json'
    original=json.loads(source.read_text())
    target=next(t for t in original['trials'] if t['scenario']=='healthy')
    folder=ROOT/target['raw_trial']
    for name in ('scan.json','sbom.json','image-inspect.json','analysisrun.json','stable.jsonl'):
        assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==target['artifact_sha256'][name], name
    scan=json.loads((folder/'scan.json').read_text())
    inspected=json.loads((folder/'image-inspect.json').read_text())[0]
    assert scan['Metadata']['ImageID']==inspected['Id']
    assert target['image'] in inspected['RepoDigests']
    assert not any(v.get('Severity') in ('HIGH','CRITICAL') for r in scan['Results'] for v in r.get('Vulnerabilities',[]))
    analysis=json.loads((folder/'analysisrun.json').read_text())
    if 'items' in analysis:
        analysis=next(a for a in analysis['items'] if a['metadata']['name']==target['analyses'][0]['name'])
    assert analysis['status']['phase']=='Successful'
    assert analysis['metadata']['labels']['rollouts-pod-template-hash']==target['candidate_hash']
    assert target['stable_requests']>=100 and target['stable_non_200']==0 and target['sampling_gate_passed']
    target={**target,'scanned_image_id':scan['Metadata']['ImageID']}
    result={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'passed':True,
            'source_report_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'target':target,
            'scope':'Supplemental binding of preserved healthy-trial scan identity; no historical report rewritten or new experiment claimed'}
    (ROOT/'docs/evidence/recovery-target-acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'passed':True,'target_build':target['jenkins_build'],'scanned_image_id':target['scanned_image_id']}))


if __name__=='__main__': main()
