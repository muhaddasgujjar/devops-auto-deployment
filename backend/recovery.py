"""Transactional recovery ledger. Only the separately authorized writer can actuate."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.recovery_policy import POLICY, as_time, measured, sustained
from backend.service import Conflict

ACTIVE = ('proposed', 'applying', 'verifying')


class InvalidRecovery(ValueError):
    pass


def transition(service, conn, env, row, event_id, phase, *, commit=None, outcome=None, evidence=None):
    if row['recovery_commit'] and commit and row['recovery_commit'] != commit:
        raise Conflict('Recovery Git commit is immutable')
    table = service.t('recoveries')
    changes = {'phase': phase, 'version': row['version'] + 1,
               'recovery_commit': row['recovery_commit'] or commit, 'outcome': outcome,
               'evidence': evidence or {}, 'updated_at': datetime.now(timezone.utc)}
    conn.execute(table.update().where(table.c.id == row['id']).values(**changes))
    conn.execute(service.t('recovery_events').insert().values(id=str(uuid.uuid4()), recovery_id=row['id'],
                 event_id=event_id, phase=phase, data={'commit': changes['recovery_commit'],
                 'outcome': outcome, 'evidence': evidence or {}}))


def supersede_changed(service, conn, env, event_id):
    row = conn.execute(select(service.t('recoveries')).where(
        service.t('recoveries').c.environment_id == service.env_id,
        service.t('recoveries').c.phase.in_(ACTIVE))).mappings().first()
    if not row or not env['desired_release_id'] or env['desired_release_id'] == row['origin_release_id']:
        return
    desired = conn.execute(select(service.t('releases')).where(
        service.t('releases').c.id == env['desired_release_id'])).mappings().one()
    if desired['recovery_id'] != row['id']:
        transition(service, conn, env, row, event_id, 'superseded', outcome='newer_release')


def authorize_deployment(service, conn, env, item, source):
    if not item.recovery_id:
        return None
    table = service.t('recoveries')
    row = conn.execute(select(table).where(table.c.id == item.recovery_id,
        table.c.environment_id == service.env_id).with_for_update()).mappings().first()
    if source == 'import' or not row or row['phase'] not in ('applying', 'verifying', 'recovered', 'failed'):
        raise Conflict('Recovery deployment is not authorized')
    if row['phase'] == 'failed' and not row['recovery_commit']:
        raise Conflict('An unpublished failed recovery cannot authorize a deployment')
    if row['recovery_commit'] and row['recovery_commit'] != item.environment_commit:
        raise Conflict('Recovery deployment Git identity differs')
    target = service.release(conn, row['target_release_id'])
    if not target or (item.build_number, item.source_commit, item.image) != (
            target['build']['number'], target['build']['source_commit'], target['artifact']['image']):
        raise Conflict('Recovery deployment target differs')
    # A replay of a completed recovery cannot replace a later desired release.
    if row['phase'] in ('recovered', 'failed') and env['desired_release_id']:
        desired = service.release(conn, env['desired_release_id'])
        if desired['recovery_id'] != row['id'] and not (row['phase'] == 'failed' and desired['id'] == row['origin_release_id']):
            raise Conflict('Recovery was superseded by later desired state')
    return row


class RecoveryService:
    def __init__(self, service):
        self.service, self.db, self.t, self.env_id = service, service.db, service.t, service.env_id

    def _begin(self, conn, envelope, actor):
        envs, events = self.t('environments'), self.t('incoming_events')
        env = dict(conn.execute(select(envs).where(envs.c.id == self.env_id).with_for_update()).mappings().one())
        payload = envelope.model_dump(mode='json')
        digest = hashlib.sha256(json.dumps({k: v for k, v in payload.items() if k != 'expected_version'},
                                          sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        external = 'recovery:' + envelope.event_id
        prior = conn.execute(select(events).where(events.c.environment_id == self.env_id,
                             events.c.external_id == external)).mappings().first()
        if prior:
            if prior['payload_hash'] != digest:
                raise Conflict('Recovery event ID was reused with different content')
            return env, None, {**prior['result'], 'duplicate': True}
        if env['version'] != envelope.expected_version:
            raise Conflict('Environment version changed; read current state and retry')
        event_id = str(uuid.uuid4())
        conn.execute(events.insert().values(id=event_id, environment_id=self.env_id, external_id=external,
                     payload_hash=digest, request_hash=digest, payload=payload, actor=actor, source='recovery', result={}))
        return env, event_id, None

    def _finish(self, conn, env, event_id, action, data):
        data = {**data, 'actor': conn.scalar(select(self.t('incoming_events').c.actor).where(
                self.t('incoming_events').c.id == event_id)), 'source': 'recovery'}
        env['version'] += 1
        conn.execute(self.t('environments').update().where(self.t('environments').c.id == self.env_id).values(version=env['version']))
        result = {'version': env['version'], 'duplicate': False, **data}
        conn.execute(self.t('incoming_events').update().where(self.t('incoming_events').c.id == event_id).values(result=result))
        conn.execute(self.t('audit').insert().values(environment_id=self.env_id, event_id=event_id,
                     action=action, version=env['version'], data=data))
        from backend.monitoring import MonitoringService
        MonitoringService(self.service).evaluate(conn, data['actor'])
        return result

    def _target(self, conn, origin, now):
        releases, recoveries = self.t('releases'), self.t('recoveries')
        bad = select(recoveries.c.origin_release_id).where(recoveries.c.environment_id == self.env_id)
        rows = conn.scalars(select(releases.c.id).where(releases.c.environment_id == self.env_id,
            releases.c.id != origin['id'], releases.c.status == 'promoted', releases.c.id.not_in(bad),
            releases.c.promoted_at >= now - timedelta(seconds=POLICY['target_retention_seconds']),
            releases.c.promoted_at < origin['promoted_at']).order_by(releases.c.promoted_at.desc()))
        for release_id in rows:
            item = self.service.release(conn, release_id)
            artifact = item['artifact']
            if (artifact['reported_high_critical'] == 0 and artifact['scanned_image_id'] and
                all(name in artifact['refs'] for name in ('scan.json', 'sbom.json')) and
                any(a['phase'] == 'Successful' for a in item['analyses']) and
                any(o['quality'] == 'accepted' and o['stable_requests'] >= POLICY['minimum_requests'] and
                    o['stable_non_200'] == 0 for o in item['observations'])):
                return item
        return None

    def windows(self, release_id, limit=3, conn=None):
        if conn is None:
            with self.db.engine.connect() as active:
                return self.windows(release_id, limit, active)
        table = self.t('health_windows')
        return [dict(r) for r in conn.execute(select(table).where(table.c.environment_id == self.env_id,
                    table.c.release_id == release_id).order_by(table.c.window_end.desc()).limit(limit)).mappings()]

    def observe(self, envelope, actor):
        now = datetime.now(timezone.utc)
        end = envelope.window_end
        if (end.tzinfo is None or end.timestamp() % POLICY['window_seconds'] or
            not 0 <= (now - end).total_seconds() <= POLICY['maximum_sample_age_seconds']):
            raise InvalidRecovery('Health window must be a recent completed UTC policy boundary')
        if envelope.quality == 'measured' and not measured(envelope.data):
            raise InvalidRecovery('Incomplete, nonfinite or insufficient health measurements')
        with self.db.engine.begin() as conn:
            env, event_id, prior = self._begin(conn, envelope, actor)
            if prior:
                return prior
            origin = self.service.release(conn, env['desired_release_id'])
            if (not origin or origin['id'] != envelope.release_id or origin['status'] != 'promoted' or
                env['stable_release_id'] != origin['id'] or env['stable_hash'] != envelope.pod_hash or
                env['freshness'] != 'current' or not env['last_observed_at'] or
                not 0 <= (now - env['last_observed_at']).total_seconds() <= self.service.settings.stale_seconds):
                raise Conflict('Health sample does not match a current promoted serving deployment')
            if not origin['promoted_at'] or end - timedelta(seconds=POLICY['window_seconds']) < origin['promoted_at']:
                raise Conflict('Health window starts before promotion')
            table = self.t('health_windows')
            if conn.scalar(select(table.c.id).where(table.c.release_id == origin['id'], table.c.window_end == end)):
                raise Conflict('Health window already recorded; read the retained sample')
            conn.execute(table.insert().values(id=str(uuid.uuid4()), environment_id=self.env_id,
                         release_id=origin['id'], window_end=end, quality=envelope.quality,
                         data={**envelope.data, 'pod_hash': envelope.pod_hash}))
            incident = None
            recent = conn.execute(select(self.t('recoveries')).where(self.t('recoveries').c.environment_id == self.env_id)
                        .order_by(self.t('recoveries').c.created_at.desc()).limit(1)).mappings().first()
            existing = conn.scalar(select(self.t('recoveries').c.id).where(
                self.t('recoveries').c.origin_release_id == origin['id'], self.t('recoveries').c.policy == POLICY['id']))
            if (not existing and (now - origin['promoted_at']).total_seconds() <= POLICY['monitor_seconds'] and
                (not recent or (recent['phase'] not in ACTIVE and
                    (now - recent['updated_at']).total_seconds() >= POLICY['cooldown_seconds'])) and
                sustained(self.windows(origin['id'], conn=conn), 'breach', now=now)):
                target = self._target(conn, origin, now)
                incident = str(uuid.uuid4())
                phase = 'proposed' if target else 'failed'
                conn.execute(self.t('recoveries').insert().values(id=incident, environment_id=self.env_id,
                    origin_release_id=origin['id'], target_release_id=target['id'] if target else None,
                    base_commit=origin['environment_commit'], policy=POLICY['id'],
                    trigger={'windows': [dict(window_end=r['window_end'].isoformat(), data=r['data'])
                             for r in self.windows(origin['id'], conn=conn)]},
                    phase=phase, outcome=None if target else 'no_accepted_target'))
                conn.execute(self.t('recovery_events').insert().values(id=str(uuid.uuid4()), recovery_id=incident,
                    event_id=event_id, phase=phase, data={'actor': actor, 'policy': POLICY['id']}))
            return self._finish(conn, env, event_id, 'post_promotion_health', {'recovery_id': incident,
                                'release_id': origin['id'], 'quality': envelope.quality})

    def event(self, recovery_id, envelope, actor):
        now = datetime.now(timezone.utc)
        with self.db.engine.begin() as conn:
            env, event_id, prior = self._begin(conn, envelope, actor)
            if prior:
                return prior
            row = conn.execute(select(self.t('recoveries')).where(self.t('recoveries').c.id == recovery_id,
                self.t('recoveries').c.environment_id == self.env_id).with_for_update()).mappings().first()
            if not row or row['version'] != envelope.expected_recovery_version:
                raise Conflict('Recovery version changed or recovery not found')
            allowed = {'proposed': ('applying', 'failed', 'superseded'),
                       'applying': ('verifying', 'failed', 'superseded'),
                       'verifying': ('recovered', 'failed', 'superseded')}
            if envelope.phase not in allowed.get(row['phase'], ()):
                raise Conflict('Recovery transition is not allowed')
            if envelope.phase in ('applying', 'verifying') and not 0 <= (now - row['created_at']).total_seconds() < POLICY['recovery_timeout_seconds']:
                raise Conflict('Recovery publication deadline expired')
            desired = self.service.release(conn, env['desired_release_id'])
            if envelope.phase in ('applying', 'verifying') and desired and desired['id'] != row['origin_release_id'] and desired['recovery_id'] != row['id']:
                raise Conflict('A newer release superseded this recovery')
            if envelope.phase == 'verifying' and not envelope.recovery_commit:
                raise InvalidRecovery('Verification needs the published Git commit')
            if envelope.phase == 'recovered':
                windows = self.windows(desired['id'], conn=conn) if desired else []
                if (not desired or desired['recovery_id'] != row['id'] or desired['status'] != 'promoted' or
                    env['stable_release_id'] != desired['id'] or desired['environment_commit'] != row['recovery_commit'] or
                    env['freshness'] != 'current' or not env['last_observed_at'] or
                    not 0 <= (now - env['last_observed_at']).total_seconds() <= POLICY['maximum_sample_age_seconds'] or
                    (now - row['created_at']).total_seconds() > POLICY['recovery_timeout_seconds'] or
                    not sustained(windows, 'healthy', now=now) or
                    min((w['window_end'] for w in windows), default=now) - timedelta(seconds=30) < row['updated_at']):
                    raise Conflict('Recovery lacks current promoted target and sustained healthy evidence')
                proof = envelope.evidence
                target = self.service.release(conn, row['target_release_id'])
                if (type(proof.get('requests')) is not int or proof['requests'] < POLICY['minimum_requests'] or proof.get('non_200') != 0 or
                    proof.get('identity_mismatches') != 0 or proof.get('target_requests') != proof['requests'] or
                    proof.get('environment_commit') != row['recovery_commit'] or proof.get('controller_uid') != env['source_uid'] or
                    not isinstance(proof.get('maximum_gap_seconds'), (int, float)) or
                    not 0 <= proof['maximum_gap_seconds'] <= 10 or
                    proof.get('revision') != f"{target['build']['source_commit']}-jenkins-{target['build']['number']}" or
                    proof.get('image') != target['artifact']['image'] or proof.get('pod_hash') != env['stable_hash']):
                    raise InvalidRecovery('Independent serving HTTP proof is incomplete or mismatched')
            transition(self.service, conn, env, row, event_id, envelope.phase, commit=envelope.recovery_commit,
                       outcome=envelope.outcome, evidence=envelope.evidence)
            return self._finish(conn, env, event_id, 'recovery_' + envelope.phase,
                                {'recovery_id': row['id'], 'phase': envelope.phase, 'actor': actor})

    def history(self, limit=50):
        with self.db.engine.connect() as conn:
            table = self.t('recoveries')
            result = []
            for row in conn.execute(select(table).where(table.c.environment_id == self.env_id)
                                   .order_by(table.c.created_at.desc()).limit(limit)).mappings():
                item = dict(row)
                item['origin'] = self.service.release(conn, row['origin_release_id'])
                item['target'] = self.service.release(conn, row['target_release_id'])
                events = self.t('recovery_events')
                item['events'] = [dict(r) for r in conn.execute(select(events).where(events.c.recovery_id == row['id'])
                                  .order_by(events.c.created_at, events.c.id)).mappings()]
                result.append(item)
            return result
