"""Install the pinned, headless Argo CD reconciliation profile on the named lab."""
import hashlib
import json
import os
import subprocess
from pathlib import Path
from urllib.request import urlopen

import yaml

from scripts.live_trial import kube
from scripts.render_release import ROOT


def main():
    os.environ['KUBECONFIG'] = str(ROOT / 'output/lab.kubeconfig')
    if kube('config', 'current-context').strip() != 'k3d-release-lab':
        raise SystemExit('Only the named disposable lab is supported')
    versions = json.loads((ROOT / 'versions.json').read_text())
    folder = ROOT / 'output/gitops'
    folder.mkdir(parents=True, exist_ok=True)
    url = f'https://raw.githubusercontent.com/argoproj/argo-cd/{versions["argo_cd"]}/manifests/core-install.yaml'
    with urlopen(url, timeout=60) as response:
        content = response.read()
    if hashlib.sha256(content).hexdigest() != versions['argo_cd_core_sha256']:
        raise SystemExit('Upstream core manifest checksum mismatch')
    namespace = folder / 'namespace.yaml'
    namespace.write_text('apiVersion: v1\nkind: Namespace\nmetadata:\n  name: argocd\n')
    print(kube('apply', '-f', str(namespace)), flush=True)
    known_hosts = kube('get', 'configmap', 'argocd-ssh-known-hosts-cm', '-n', 'argocd', '--ignore-not-found', '-o', 'name').strip()
    documents = []
    for doc in yaml.safe_load_all(content):
        if not doc:
            continue
        # This lab manages one Application directly; ApplicationSets are unnecessary.
        if doc['metadata']['name'].startswith('argocd-applicationset-controller'):
            continue
        if doc['metadata']['name'] == 'argocd-ssh-known-hosts-cm' and known_hosts:
            continue  # Preserve pinned host keys during engine reinstalls.
        if doc['kind'] in ('Deployment', 'StatefulSet'):
            if doc['kind'] == 'Deployment':
                doc['spec']['progressDeadlineSeconds'] = 1800
            pod = doc['spec']['template']['spec']
            for container in pod.get('containers', []) + pod.get('initContainers', []):
                redis = container['name'] == 'redis'
                container['resources'] = {'requests': {'cpu': '50m', 'memory': '32Mi' if redis else '128Mi'},
                                          'limits': {'memory': '96Mi' if redis else '384Mi'}}
        documents.append(doc)
    manifest = folder / 'core-install.yaml'
    manifest.write_text(yaml.safe_dump_all(documents, sort_keys=False))
    print(kube('apply', '--server-side', '-n', 'argocd', '-f', str(manifest)), flush=True)
    for kind, name in [('deployment', 'argocd-redis'), ('deployment', 'argocd-repo-server'),
                       ('statefulset', 'argocd-application-controller')]:
        for attempt in range(6):
            result = subprocess.run(['kubectl', 'wait', 'pod', '-l', 'app.kubernetes.io/name=' + name,
                                     '--for=condition=Ready', '-n', 'argocd', '--timeout=120s'],
                                    capture_output=True, text=True, timeout=140)
            if result.returncode == 0:
                print(result.stdout, flush=True)
                break
            print(f'Waiting for {name}; image pull/startup attempt {attempt + 1}/6', flush=True)
        else:
            raise SystemExit(f'{name} did not become ready; inspect namespace argocd events')


if __name__ == '__main__':
    main()
