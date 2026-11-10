"""Read-only bounded snapshot of environment Git and the owned Kubernetes objects."""
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from backend.contracts import ReleaseObservation


class SourcesUnavailable(RuntimeError):
    pass


def execute(args):
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=20)
        if result.returncode:
            raise SourcesUnavailable('sources_unavailable')
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        raise SourcesUnavailable('sources_unavailable')


def collect(kubeconfig, environment_git):
    kube = ['kubectl', '--kubeconfig', str(kubeconfig), '--context=k3d-release-lab', '--request-timeout=5s']

    def get(kind, name=None, namespace='demo-dev', selector=None):
        args = kube + ['get', kind]
        if name:
            args.append(name)
        args += ['-n', namespace, '-o', 'json']
        if selector:
            args += ['-l', selector]
        return json.loads(execute(args))

    def head():
        value = execute(['git', '--git-dir', str(environment_git), 'rev-parse', 'refs/heads/main'])
        if not re.fullmatch('[a-f0-9]{40}', value):
            raise SourcesUnavailable('sources_unavailable')
        return value

    desired_git = head()
    application = get('application', 'release-demo-dev', 'argocd')
    sync = application.get('status', {}).get('sync', {})
    if sync.get('status') != 'Synced' or sync.get('revision') != desired_git:
        raise SourcesUnavailable('sources_changing')
    rollout = get('rollout', 'release-demo')
    state, spec, metadata = rollout['status'], rollout['spec'], rollout['metadata']
    if str(state.get('observedGeneration')) != str(metadata['generation']):
        raise SourcesUnavailable('sources_changing')
    container = spec['template']['spec']['containers'][0]
    revision = next(e['value'] for e in container['env'] if e['name'] == 'APP_REVISION')
    match = re.fullmatch(r'([a-f0-9]{40})-jenkins-([1-9][0-9]*)', revision)
    if not match:
        raise SourcesUnavailable('sources_unavailable')
    stable_hash = get('service', 'demo-stable')['spec']['selector']['rollouts-pod-template-hash']
    pods = get('pods', selector='app=release-demo,rollouts-pod-template-hash=' + stable_hash)['items']
    if len(pods) != spec['replicas'] or not all(any(c['type'] == 'Ready' and c['status'] == 'True'
            for c in p.get('status', {}).get('conditions', [])) for p in pods):
        raise SourcesUnavailable('sources_changing')
    stable_revisions = {next(e['value'] for e in p['spec']['containers'][0]['env'] if e['name'] == 'APP_REVISION') for p in pods}
    stable_images = {p['spec']['containers'][0]['image'] for p in pods}
    if len(stable_revisions) != 1 or len(stable_images) != 1:
        raise SourcesUnavailable('sources_changing')
    candidate = state.get('currentPodHash')
    analysis_name = state.get('blueGreen', {}).get('prePromotionAnalysisRunStatus', {}).get('name')
    analyses = []
    if analysis_name:
        analysis = get('analysisrun', analysis_name)
        if (analysis['metadata'].get('labels', {}).get('rollouts-pod-template-hash') != candidate or
                not any(o.get('uid') == metadata['uid'] and o.get('kind') == 'Rollout'
                        for o in analysis['metadata'].get('ownerReferences', []))):
            raise SourcesUnavailable('sources_changing')
        analyses.append({'name': analysis_name, 'phase': analysis['status']['phase'],
                         'metrics': analysis['status'].get('metricResults', [])})
    phase = analyses[0]['phase'] if analyses else None
    if state.get('abort'):
        status = 'readiness_aborted' if 'timed out progressing' in state.get('message', '') else (
            'rejected' if phase == 'Failed' else ('telemetry_error' if phase == 'Error' else 'aborted'))
    elif phase == 'Inconclusive':
        status = 'inconclusive'
    elif phase == 'Error':
        status = 'telemetry_error'
    elif state.get('phase') == 'Healthy' and candidate == stable_hash and phase == 'Successful':
        status = 'promoted'
    else:
        status = 'progressing'
    again, application_again = get('rollout', 'release-demo'), get('application', 'release-demo-dev', 'argocd')
    if (again['metadata']['uid'] != metadata['uid'] or again['metadata']['resourceVersion'] != metadata['resourceVersion'] or
            application_again.get('status', {}).get('sync', {}) != sync or head() != desired_git):
        raise SourcesUnavailable('sources_changing')
    return ReleaseObservation(build_number=int(match[2]), source_commit=match[1], image=container['image'],
        environment_commit=desired_git, candidate_hash=candidate, status=status,
        observation_sequence=int(metadata['resourceVersion']), source_uid=metadata['uid'],
        observed_at=datetime.now(timezone.utc), stable_revision=stable_revisions.pop(),
        stable_hash=stable_hash, stable_image=stable_images.pop(), analyses=analyses,
        observation_details={'source': 'read-only-kubernetes-and-environment-git', 'rollout_generation': metadata['generation']})
