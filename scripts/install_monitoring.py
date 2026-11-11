"""Adopt the retained lab claim only after validating its immutable binding."""
import json
import subprocess
from scripts.render_release import ROOT


def validate_storage(claim,storage_class,volume):
    if storage_class and (storage_class.get('provisioner')!='rancher.io/local-path' or
            storage_class.get('reclaimPolicy')!='Retain' or storage_class.get('volumeBindingMode')!='WaitForFirstConsumer'):
        raise RuntimeError('Existing release-retain class differs; preserving it and stopping')
    if claim:
        spec=claim['spec']
        if spec.get('storageClassName')!='release-retain' or spec['resources']['requests']['storage']!='2Gi' or spec['accessModes']!=['ReadWriteOnce']:
            raise RuntimeError('Existing claim differs; preserve its size and binding before changing configuration')
        if spec.get('volumeName'):
            if not volume or volume['spec'].get('persistentVolumeReclaimPolicy')!='Retain':
                raise RuntimeError('Existing bound volume must retain its data')
            ref=volume['spec'].get('claimRef',{})
            if (ref.get('namespace'),ref.get('name'),ref.get('uid'))!=('monitoring','prometheus-data',claim['metadata']['uid']):
                raise RuntimeError('Existing volume is bound to another claim')


def main():
    node='k3d-release-lab-server-0'
    item=json.loads(subprocess.check_output(['docker','inspect',node]))[0]
    if item['Config']['Labels'].get('k3d.cluster')!='release-lab' or not item['State']['Running']:
        raise RuntimeError('Only the running release-lab server is supported')
    base=['kubectl','--kubeconfig',str(ROOT/'output/lab.kubeconfig'),'--context=k3d-release-lab']
    def get(kind,name,namespace=None):
        result=subprocess.run(base+['get',kind,name]+(['-n',namespace] if namespace else [])+
            ['--ignore-not-found','-o','json'],capture_output=True,text=True,timeout=15)
        if result.returncode: raise RuntimeError('Cannot inspect retained storage before applying changes')
        return json.loads(result.stdout) if result.stdout.strip() else None
    claim=get('pvc','prometheus-data','monitoring'); storage_class=get('storageclass','release-retain')
    volume=get('pv',claim['spec']['volumeName']) if claim and claim['spec'].get('volumeName') else None
    validate_storage(claim,storage_class,volume)
    subprocess.run(base+['apply','-f',str(ROOT/'platform/monitoring.yaml')],check=True)
    subprocess.run(base+['rollout','status','deployment/prometheus','-n','monitoring','--timeout=120s'],check=True)
    print('Retained single-node monitoring installed; existing PVC/data are never deleted')


if __name__=='__main__': main()
