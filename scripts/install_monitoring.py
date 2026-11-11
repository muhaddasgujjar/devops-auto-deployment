"""Prepare only the labelled lab node's retained local Prometheus directory."""
import json
import subprocess
from scripts.render_release import ROOT


def main():
    node='k3d-release-lab-server-0'
    item=json.loads(subprocess.check_output(['docker','inspect',node]))[0]
    if item['Config']['Labels'].get('k3d.cluster')!='release-lab' or not item['State']['Running']:
        raise RuntimeError('Only the running release-lab server is supported')
    subprocess.run(['docker','exec',node,'mkdir','-p','/var/lib/release-lab/prometheus'],check=True)
    subprocess.run(['docker','exec',node,'chown','65534:65534','/var/lib/release-lab/prometheus'],check=True)
    base=['kubectl','--kubeconfig',str(ROOT/'output/lab.kubeconfig'),'--context=k3d-release-lab']
    subprocess.run(base+['apply','-f',str(ROOT/'platform/monitoring.yaml')],check=True)
    subprocess.run(base+['rollout','status','deployment/prometheus','-n','monitoring','--timeout=120s'],check=True)
    print('Retained single-node monitoring installed; existing PVC/data are never deleted')


if __name__=='__main__': main()
