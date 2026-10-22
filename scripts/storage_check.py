"""Install lab persistence and prove Prometheus pod replacement and isolated restore."""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import yaml

from scripts.evidence import finalize_archive, digest
from scripts.live_trial import kube, resource
from scripts.render_release import ROOT


def apply(document):
    result = subprocess.run(['kubectl', 'apply', '-f', '-'], input=yaml.safe_dump(document),
                            text=True, capture_output=True, check=True, timeout=60)
    print(result.stdout.strip(), flush=True)


def query(expression, timestamp=None, pod=None):
    path = (f'/api/v1/namespaces/monitoring/pods/{pod}:9090/proxy/' if pod else
            '/api/v1/namespaces/monitoring/services/prometheus:9090/proxy/')
    params = {'query': expression}
    if timestamp is not None:
        params['time'] = str(timestamp)
    data = json.loads(kube('get', '--raw', path + 'api/v1/query?' + urlencode(params)))
    if data.get('status') != 'success':
        raise ValueError('Prometheus query failed')
    return data['data']['result']


def scale(name, replicas):
    kube('scale', 'deployment/' + name, '-n', 'monitoring', '--replicas=' + str(replicas))
    if replicas:
        kube('rollout', 'status', 'deployment/' + name, '-n', 'monitoring', '--timeout=120s')
    else:
        for _ in range(60):
            pods = json.loads(kube('get', 'pods', '-n', 'monitoring', '-l', 'app=' + name, '-o', 'json'))['items']
            if not pods:
                return
            time.sleep(1)
        raise TimeoutError('Prometheus pods did not stop')


def helper(name, claim, image, readonly):
    apply({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': 'monitoring',
           'labels': {'release-lab.managed': 'storage-copy'}}, 'spec': {
           'restartPolicy': 'Never', 'activeDeadlineSeconds': 1800, 'terminationGracePeriodSeconds': 1,
           'automountServiceAccountToken': False,
           'securityContext': {'runAsNonRoot': True, 'runAsUser': 65534, 'fsGroup': 65534,
                               'seccompProfile': {'type': 'RuntimeDefault'}},
           'containers': [{'name': 'copy', 'image': image, 'command': ['python', '-c', 'import time; time.sleep(3600)'],
                           'resources': {'requests': {'cpu': '25m', 'memory': '32Mi'}, 'limits': {'memory': '128Mi', 'cpu': '500m'}},
                           'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True,
                                               'capabilities': {'drop': ['ALL']}},
                           'volumeMounts': [{'name': 'data', 'mountPath': '/data', 'readOnly': readonly}]}],
           'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': claim}}]}})
    kube('wait', 'pod/' + name, '-n', 'monitoring', '--for=condition=Ready', '--timeout=120s')


def main():
    os.environ['KUBECONFIG'] = str(ROOT / 'output/lab.kubeconfig')
    if kube('config', 'current-context').strip() != 'k3d-release-lab':
        raise SystemExit('Only the dedicated lab is supported')
    rollout = resource('rollout', 'release-demo')
    if (rollout['status'].get('phase') != 'Healthy'
            or str(rollout['status'].get('observedGeneration')) != str(rollout['metadata']['generation'])):
        raise SystemExit('Finish the active candidate before monitoring maintenance')
    from scripts.gitops_trial import Jenkins
    if (ROOT / 'output/gitops/local-git.json').exists():
        client = Jenkins()
        for job in ('release-local', 'release-main'):
            latest = client.json(f'job/{job}/api/json').get('lastBuild')
            if latest and client.json(f'job/{job}/{latest["number"]}/api/json')['building']:
                raise SystemExit('Wait for CI builds before monitoring maintenance')
    tag = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ').lower()
    folder = ROOT / 'output' / ('storage-' + tag)
    folder.mkdir(parents=True, exist_ok=False)
    summary = {'started': datetime.now(timezone.utc).isoformat(), 'scenario': 'persistent-storage'}
    helpers = []
    restore_name = 'prometheus-restore-' + tag
    try:
        # Retain a readable export of available ephemeral application samples at cutover.
        before = query('{namespace="demo-dev"}[2h]')
        (folder / 'prometheus-before.json').write_text(json.dumps(before))
        print('Preserved pre-migration application samples; installing retained PVC', flush=True)
        kube('apply', '-f', str(ROOT / 'platform/storage.yaml'))
        kube('apply', '-f', str(ROOT / 'platform/monitoring.yaml'))
        kube('rollout', 'status', 'deployment/prometheus', '-n', 'monitoring', '--timeout=120s')
        pvc = json.loads(kube('get', 'pvc', 'prometheus-data', '-n', 'monitoring', '-o', 'json'))
        pv = json.loads(kube('get', 'pv', pvc['spec']['volumeName'], '-o', 'json'))
        if pvc['status']['phase'] != 'Bound' or pv['spec']['persistentVolumeReclaimPolicy'] != 'Retain':
            raise AssertionError('Storage must be Bound with Retain policy')
        summary['pvc_uid'] = pvc['metadata']['uid']
        summary['volume'] = pv['metadata']['name']
        expression = 'sum(demo_requests_total{namespace="demo-dev"})'
        for _ in range(30):
            kube('get', '--raw', '/api/v1/namespaces/demo-dev/services/demo-stable:80/proxy/')
            result = query(expression)
            if result and float(result[0]['value'][1]) > 0:
                break
            time.sleep(1)
        else:
            raise AssertionError('No application samples available for persistence check')
        timestamp, value = result[0]['value']
        summary['historical_sample'] = {'query': expression, 'time': timestamp, 'value': value}
        old_pod = json.loads(kube('get', 'pods', '-n', 'monitoring', '-l', 'app=prometheus', '-o', 'json'))['items'][0]
        print('Checking that historical samples survive pod replacement', flush=True)
        scale('prometheus', 0)
        scale('prometheus', 1)
        new_pod = json.loads(kube('get', 'pods', '-n', 'monitoring', '-l', 'app=prometheus', '-o', 'json'))['items'][0]
        recovered = query(expression, timestamp)
        if old_pod['metadata']['uid'] == new_pod['metadata']['uid'] or not recovered or recovered[0]['value'][1] != value:
            raise AssertionError('Historical sample did not survive pod replacement')
        summary['pod_replacement_verified'] = True
        (folder / 'prometheus-after.json').write_text(json.dumps(recovered))
        python_image = json.loads((ROOT / 'versions.json').read_text())['python_image']
        backup_pod = 'prometheus-copy-' + tag
        helpers.append(backup_pod)
        helper(backup_pod, 'prometheus-data', python_image, True)
        print('Taking a clean offline TSDB backup', flush=True)
        scale('prometheus', 0)
        archive = folder / 'prometheus-backup.tar.gz'
        code = "import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz');t.add('/data',arcname='.');t.close()"
        with archive.open('wb') as stream:
            subprocess.run(['kubectl', 'exec', '-n', 'monitoring', backup_pod, '--', 'python', '-c', code],
                           stdout=stream, stderr=subprocess.PIPE, check=True, timeout=180)
        summary['backup_sha256'] = digest(archive)
        scale('prometheus', 1)
        claim = {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': restore_name, 'namespace': 'monitoring'},
                 'spec': {'storageClassName': 'release-retain', 'accessModes': ['ReadWriteOnce'],
                          'resources': {'requests': {'storage': '2Gi'}}}}
        apply(claim)
        copy_pod = 'prometheus-load-' + tag
        helpers.append(copy_pod)
        helper(copy_pod, restore_name, python_image, False)
        code = '''import pathlib,sys,tarfile
target=pathlib.Path('/data')
if any(target.iterdir()): raise SystemExit('Restore target is not empty')
with tarfile.open(fileobj=sys.stdin.buffer,mode='r|gz') as tar:
 for member in tar:
  if member.issym() or member.islnk() or '..' in pathlib.PurePosixPath(member.name).parts or member.name.startswith('/'):
   raise SystemExit('Unsafe TSDB archive entry')
  tar.extract(member,target,filter='data')
'''
        with archive.open('rb') as stream:
            subprocess.run(['kubectl', 'exec', '-i', '-n', 'monitoring', copy_pod, '--', 'python', '-c', code],
                           stdin=stream, capture_output=True, check=True, timeout=180)
        deployment = next(doc for doc in yaml.safe_load_all((ROOT / 'platform/monitoring.yaml').read_text()) if doc['kind'] == 'Deployment')
        deployment['metadata']['name'] = restore_name
        deployment['spec']['selector']['matchLabels']['app'] = restore_name
        deployment['spec']['template']['metadata']['labels']['app'] = restore_name
        deployment['spec']['template']['spec']['volumes'][1]['persistentVolumeClaim']['claimName'] = restore_name
        apply(deployment)
        kube('rollout', 'status', 'deployment/' + restore_name, '-n', 'monitoring', '--timeout=120s')
        restored_pod = json.loads(kube('get', 'pods', '-n', 'monitoring', '-l', 'app=' + restore_name, '-o', 'json'))['items'][0]['metadata']['name']
        restored = query(expression, timestamp, restored_pod)
        if not restored or restored[0]['value'][1] != value:
            raise AssertionError('Restored TSDB does not return the original historical sample')
        summary.update(verdict='persistence-and-restore-verified', isolated_restore_verified=True,
                       restored_claim=restore_name, restored_value=restored[0]['value'][1])
        (folder / 'storage.json').write_text(json.dumps({'pvc': pvc, 'pv': pv}, indent=2))
        print('Historical sample verified from the independent restored TSDB', flush=True)
    except Exception as exc:
        summary.update(verdict='storage-check-failed', error=str(exc))
        raise
    finally:
        cleanup_errors = []
        try:
            scale('prometheus', 1)
            if kube('get', 'deployment', restore_name, '-n', 'monitoring', '--ignore-not-found', '-o', 'name').strip():
                scale(restore_name, 0)
        except Exception as exc:
            cleanup_errors.append(str(exc))
        for name in helpers:
            try:
                kube('delete', 'pod', name, '-n', 'monitoring', '--ignore-not-found', '--wait=false')
            except Exception as exc:
                cleanup_errors.append(str(exc))
        if cleanup_errors:
            summary.update(verdict='storage-check-failed', cleanup_errors=cleanup_errors)
        summary['finished'] = datetime.now(timezone.utc).isoformat()
        (folder / 'summary.json').write_text(json.dumps(summary, indent=2))
        finalize_archive(folder)
        if cleanup_errors:
            raise RuntimeError('Storage cleanup needs attention: ' + '; '.join(cleanup_errors))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
