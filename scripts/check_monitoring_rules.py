"""Run the actual selected Prometheus binary's rule fixtures, not a PromQL mock."""
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime,timezone
from pathlib import Path
import yaml
from scripts.render_release import ROOT


def main():
    config=next(doc for doc in yaml.safe_load_all((ROOT/'platform/monitoring.yaml').read_text()) if doc['kind']=='ConfigMap')
    image=json.loads((ROOT/'versions.json').read_text())['prometheus_image']
    with tempfile.TemporaryDirectory(prefix='release-promtool-') as directory:
        folder=Path(directory)
        (folder/'release-alerts.yml').write_text(config['data']['release-alerts.yml'])
        (folder/'prometheus.yml').write_text(config['data']['prometheus.yml'])
        tests=(ROOT/'platform/monitoring-rule-tests.yaml').read_bytes(); (folder/'tests.yml').write_bytes(tests)
        folder.chmod(0o755)
        command=['docker','run','--rm','--memory=192m','--cpus=1','--network=none','--read-only','--tmpfs','/tmp:size=32m',
            '--mount','type=bind,src='+str(folder)+',dst=/etc/prometheus,readonly','--workdir','/etc/prometheus','--entrypoint','/bin/promtool',image]
        outputs=[]
        for args in (['check','rules','release-alerts.yml'],['test','rules','tests.yml']):
            result=subprocess.run(command+args,capture_output=True,text=True,timeout=90)
            outputs.append(result.stdout+result.stderr)
            if result.returncode: raise RuntimeError(outputs[-1])
        (ROOT/'output/monitoring-rule-tests.log').write_text('\n'.join(outputs))
    report={'passed':True,'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'image':image,
        'rules_sha256':hashlib.sha256(config['data']['release-alerts.yml'].encode()).hexdigest(),
        'test_source_sha256':hashlib.sha256(tests).hexdigest(),'rule_names':['DemoPodsUnavailable','DemoRequestErrors','DemoRequestLatency'],
        'cases':['sustained errors fire','healthy rates resolve','available scrapes do not fire unavailable',
                 'absent scrapes fire','latency with traffic fires','low traffic cannot fire latency']}
    (ROOT/'docs/evidence/monitoring-rules.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps({'passed':True,'cases':len(report['cases'])}))


if __name__=='__main__': main()
