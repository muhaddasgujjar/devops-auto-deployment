"""Seed environment Git from the verified serving release and hand ownership to Argo."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

from scripts.live_trial import kube, resource
from scripts.render_release import ROOT


def apply(document):
    result = subprocess.run(['kubectl', '--request-timeout=30s', 'apply', '-f', '-'],
                            input=yaml.safe_dump(document), text=True, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr)
    print(result.stdout.strip(), flush=True)


def main():
    os.environ['KUBECONFIG'] = str(ROOT / 'output/lab.kubeconfig')
    if kube('config', 'current-context').strip() != 'k3d-release-lab':
        raise SystemExit('Expected the dedicated lab')
    folder = ROOT / 'output/gitops'
    config = json.loads((folder / 'local-git.json').read_text())
    url = config['repository_url']
    secrets = Path('/opt/release-lab/secrets')
    os.environ['GIT_SSH_COMMAND'] = f'ssh -i {secrets}/environment-write -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile={secrets}/known_hosts'
    existing = kube('get', 'application', 'release-demo-dev', '-n', 'argocd', '--ignore-not-found', '-o', 'name').strip()
    if not existing:
        from scripts.doctor import inspect
        health = inspect()
        rollout = resource('rollout', 'release-demo')
        if not health['ok'] or rollout['status'].get('phase') != 'Healthy':
            raise SystemExit('A healthy stable release and telemetry are required before handoff')
        remote = subprocess.run(['git', 'ls-remote', url, 'refs/heads/main'], check=True, capture_output=True, text=True)
        if remote.stdout.strip():
            raise SystemExit('Environment main already exists; refusing to overwrite or adopt an unreviewed repository')
        with tempfile.TemporaryDirectory(prefix='seed-env-') as directory:
            def git(*args):
                subprocess.run(['git', '-C', directory, *args], check=True, capture_output=True, text=True)
            git('init', '--initial-branch=main')
            git('config', 'user.name', 'release-lab-bootstrap')
            git('config', 'user.email', 'release-lab@localhost')
            target = Path(directory) / 'environments/dev'
            target.mkdir(parents=True)
            objects = [('rollout', 'release-demo', 'rollout.yaml'), ('analysistemplate', 'candidate-health', 'analysis.yaml')]
            for kind, name, filename in objects:
                obj = resource(kind, name)
                clean = {'apiVersion': obj['apiVersion'], 'kind': obj['kind'],
                         'metadata': {'name': name, 'namespace': 'demo-dev'}, 'spec': obj['spec']}
                (target / filename).write_text(yaml.safe_dump(clean, sort_keys=False))
            services = []
            for name in ('demo-stable', 'demo-preview'):
                obj = resource('service', name)
                spec = {key: obj['spec'][key] for key in ('type', 'ports', 'selector')}
                spec['selector'].pop('rollouts-pod-template-hash', None)
                services.append({'apiVersion': 'v1', 'kind': 'Service', 'metadata': {'name': name, 'namespace': 'demo-dev'}, 'spec': spec})
            (target / 'services.yaml').write_text(yaml.safe_dump_all(services, sort_keys=False))
            git('add', '.')
            git('commit', '-m', 'Adopt the verified healthy lab release')
            git('remote', 'add', 'origin', url)
            git('push', 'origin', 'HEAD:main')
    apply({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'argocd-ssh-known-hosts-cm', 'namespace': 'argocd',
           'labels': {'app.kubernetes.io/part-of': 'argocd'}}, 'data': {'ssh_known_hosts': (secrets / 'known_hosts').read_text()}})
    apply({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'release-environment-read', 'namespace': 'argocd',
           'labels': {'argocd.argoproj.io/secret-type': 'repository'}}, 'stringData': {
           'type': 'git', 'url': url, 'sshPrivateKey': (secrets / 'environment-read').read_text()}})
    content = (ROOT / 'platform/argocd/application.yaml').read_text().replace('__ENV_REPO_URL__', url)
    for doc in yaml.safe_load_all(content):
        apply(doc)
    print('Ownership handed to Argo CD. Use environment Git for subsequent releases.', flush=True)


if __name__ == '__main__':
    main()
