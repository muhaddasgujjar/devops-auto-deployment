import hashlib
import json
from datetime import datetime
from sqlalchemy import select

from .models import (Project, Environment, Build, Artifact, Release, Analysis, RecoveryAttempt,
                     EvidenceRun, Observation, AuditEvent, InboxEvent, OutboxEvent, utcnow)


def put(session, model, identity, **values):
    obj = session.get(model, identity)
    if obj is None:
        obj = model(id=identity, **values)
        session.add(obj)
    else:
        for key, value in values.items():
            setattr(obj, key, value)
    return obj


def seed(session):
    put(session, Project, 'release-demo', name='Release demo',
        repository='https://github.com/muhaddasgujjar/devops-auto-deployment', branch='main')
    session.flush()
    put(session, Environment, 'demo-dev', project_id='release-demo', name='Development', namespace='demo-dev')
    session.flush()


def ingest(session, snapshot):
    seed(session)
    components = snapshot.get('components', {})
    for build in components.get('builds', {}).get('items', []):
        put(session, Build, build['id'], project_id='release-demo', number=build['number'], state=build['state'], data=build)
    for run in components.get('evidence', {}).get('runs', []):
        summary = run['summary']
        put(session, EvidenceRun, run['id'], verdict=run['verdict'], data=run)
        if summary.get('environment_commit') and summary.get('release_id'):
            image = summary.get('image')
            artifact_id = hashlib.sha256(image.encode()).hexdigest() if image else None
            if image:
                put(session, Artifact, artifact_id, image=image, source_commit=summary.get('source_commit'))
                session.flush()
            put(session, Release, run['id'], environment_id='demo-dev', artifact_id=artifact_id,
                state=run['verdict'], data=summary)
        state = summary.get('phase')
        if run['id'].startswith('recovery-') and state:
            put(session, RecoveryAttempt, run['id'], environment_id='demo-dev', data=summary)
    for run in components.get('analyses', {}).get('items', []):
        data = {'name': run['metadata']['name'], 'revision': run['metadata'].get('labels', {}).get('rollouts-pod-template-hash'),
                'stage': run['metadata'].get('labels', {}).get('rollout-type'), 'status': run.get('status', {}),
                'created_at': run['metadata'].get('creationTimestamp')}
        put(session, Analysis, data['name'], environment_id='demo-dev', data=data)
    # Only state transitions produce durable audit/outbox events. Repeated polls
    # refresh the cached observation without pretending to be new releases.
    rollout = components.get('rollout', {}).get('status', {})
    recovery = components.get('recovery', {})
    identity = {'rollout': {k: rollout.get(k) for k in ('phase', 'currentPodHash', 'stableRS', 'observedGeneration')},
                'recovery': {k: recovery.get(k) for k in ('phase', 'deployment_commit', 'attempt')},
                'builds': [(b['number'], b['state']) for b in components.get('builds', {}).get('items', [])],
                'errors': sorted(snapshot.get('errors', {}))}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    previous = session.get(Observation, 1)
    if previous is None or previous.fingerprint != fingerprint:
        session.add(AuditEvent(kind='lab.state.observed', actor='lab-observer', data=identity))
        # Each transition is its own event, including a later return to an earlier
        # state. The local outbox is pending until a real receiver is configured.
        import uuid
        session.add(OutboxEvent(deduplication_key=str(uuid.uuid4()), kind='lab.state.observed', data=identity))
    put(session, Observation, 1, collected_at=datetime.fromisoformat(snapshot['collected_at']),
        fingerprint=fingerprint, data=snapshot)


def drain_inbox(session):
    events = session.scalars(select(InboxEvent).where(InboxEvent.processed_at.is_(None)).with_for_update(skip_locked=True).limit(50))
    for event in events:
        session.add(AuditEvent(kind='callback.received', actor='signed-integration', data={'event_id': event.id, **event.data}))
        session.add(OutboxEvent(deduplication_key='callback:' + event.id, kind='callback.received', data=event.data))
        event.processed_at = utcnow()


def overview(session):
    observation = session.get(Observation, 1)
    if not observation:
        return {'status': 'connecting', 'collected_at': None, 'components': {}, 'errors': {}}
    payload = observation.data
    components = payload['components']
    rollout = components.get('rollout', {})
    spec, status = rollout.get('spec', {}), rollout.get('status', {})
    container = spec.get('template', {}).get('spec', {}).get('containers', [{}])[0]
    service = components.get('services', {}).get('spec', {}).get('selector', {})
    app_status = components.get('application', {}).get('status', {})
    serving = service.get('rollouts-pod-template-hash')
    targets = [t for t in components.get('monitoring', {}).get('targets', []) if t['revision'] == serving]
    recovery = components.get('recovery', {})
    return {'status': 'observed', 'collected_at': payload['collected_at'], 'errors': payload.get('errors', {}),
            'rollout': {'phase': status.get('phase', 'Unknown'), 'strategy': 'Blue / green', 'desired_replicas': spec.get('replicas'),
                        'ready_replicas': status.get('readyReplicas', 0), 'candidate_hash': status.get('currentPodHash'),
                        'serving_hash': serving, 'image': container.get('image'),
                        'revision': next((e.get('value') for e in container.get('env', []) if e['name'] == 'APP_REVISION'), None)},
            'gitops': {'status': app_status.get('sync', {}).get('status', 'Unknown'),
                       'revision': app_status.get('sync', {}).get('revision'),
                       'health': app_status.get('health', {}).get('status')},
            'targets': targets,
            'recovery': {k: recovery.get(k) for k in ('phase', 'attempt', 'updated_at', 'failure_stage', 'error', 'deadline', 'release_id')},
            'builds': components.get('builds', {}),
            'evidence': {k: v for k, v in components.get('evidence', {}).items() if k != 'runs'}}
