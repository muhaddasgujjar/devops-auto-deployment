import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert


class Conflict(ValueError):
    pass


def identity(value):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'release-lab:' + value))


class StateService:
    def __init__(self, database, settings):
        self.db, self.settings = database, settings
        self.env_id = settings.project + ':' + settings.environment
        self.t = database.table
        with self.db.engine.begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(hashtext(:scope))'), {'scope': self.env_id})
            conn.execute(insert(self.t('projects')).values(slug=settings.project).on_conflict_do_nothing())
            conn.execute(insert(self.t('environments')).values(id=self.env_id, project=settings.project,
                         name=settings.environment, job=settings.job).on_conflict_do_nothing())
            if conn.scalar(select(self.t('environments').c.job).where(self.t('environments').c.id == self.env_id)) != settings.job:
                raise Conflict('Environment is bound to a different CI job')

    def ingest(self, *, external_id, expected_version, payload, payload_hash, releases, actor, source, unavailable=None, request_hash=None, failed_builds=()):
        envs, events = self.t('environments'), self.t('incoming_events')
        with self.db.engine.begin() as conn:
            env = dict(conn.execute(select(envs).where(envs.c.id == self.env_id).with_for_update()).mappings().one())
            prior = conn.execute(select(events).where(events.c.environment_id == self.env_id,
                                                     events.c.external_id == external_id)).mappings().first()
            if prior:
                if prior['payload_hash'] != payload_hash:
                    raise Conflict('Event ID was reused with different content')
                return {**prior['result'], 'duplicate': True}
            if env['version'] != expected_version:
                raise Conflict('Environment version changed; read current state and retry')
            event_id = str(uuid.uuid4())
            conn.execute(events.insert().values(id=event_id, environment_id=self.env_id, external_id=external_id,
                         payload_hash=payload_hash, request_hash=request_hash or payload_hash,
                         payload=payload, actor=actor, source=source, result={}))
            changes = []
            for failed in failed_builds:
                table = self.t('builds')
                build_id = identity(f'{self.settings.project}/{self.settings.job}/{failed.build_number}')
                prior_build = conn.execute(select(table).where(table.c.id == build_id)).mappings().first()
                if prior_build and (prior_build['source_commit'] != failed.source_commit or prior_build['result'] != 'FAILURE'):
                    raise Conflict('Failed build identity conflicts with an existing build')
                if not prior_build:
                    conn.execute(table.insert().values(id=build_id, project=self.settings.project, job=self.settings.job,
                                 number=failed.build_number, source_commit=failed.source_commit, result='FAILURE'))
                changes.append({'build': failed.build_number, 'build_id': build_id, 'state_applied': False,
                                'status': 'ci_failed', 'reason': 'synthetic_test_gate; publication blocked'})
            for item in releases:
                changes.append(self._release(conn, env, event_id, item, source))
            from backend.recovery import supersede_changed
            supersede_changed(self, conn, env, event_id)
            if unavailable is not None:
                env.update(freshness='unavailable', detail=unavailable)
            env['version'] += 1
            updates = {key: env[key] for key in ('version', 'desired_release_id', 'stable_release_id',
                       'stable_revision', 'stable_hash', 'stable_image', 'source_uid', 'last_observed_at', 'freshness', 'detail', 'observation_sequence')}
            conn.execute(envs.update().where(envs.c.id == self.env_id).values(**updates))
            from backend.monitoring import MonitoringService
            MonitoringService(self).evaluate(conn, actor)
            result = {'event_id': external_id, 'version': env['version'], 'duplicate': False,
                      'changes': changes, 'source': source}
            conn.execute(events.update().where(events.c.id == event_id).values(result=result))
            conn.execute(self.t('audit').insert().values(environment_id=self.env_id, event_id=event_id,
                         action='source_unavailable' if unavailable is not None else 'evidence_ingested',
                         version=env['version'], data={'changes': changes, 'actor': actor, 'source': source,
                                                     'detail': unavailable}))
            return result

    def _release(self, conn, env, event_id, item, source):
        builds, artifacts, releases = self.t('builds'), self.t('artifacts'), self.t('releases')
        build_id = identity(f'{self.settings.project}/{self.settings.job}/{item.build_number}')
        deployment = conn.execute(select(releases).where(releases.c.environment_id == self.env_id,
                     releases.c.build_id == build_id, releases.c.environment_commit == item.environment_commit)).mappings().first()
        release_id = deployment['id'] if deployment else identity(f'{self.env_id}/{build_id}/{item.environment_commit}')
        build = conn.execute(select(builds).where(builds.c.id == build_id)).mappings().first()
        static_refs = {key: value for key, value in item.artifacts.items()
                       if key in {'scan.json', 'sbom.json', 'source.json', 'image-inspect.json'}}
        if build:
            if build['result'] != 'SUCCESS':
                raise Conflict('A failed build cannot acquire a release artifact')
            artifact = conn.execute(select(artifacts).where(artifacts.c.build_id == build_id)).mappings().one()
            if build['source_commit'] != item.source_commit or artifact['image'] != item.image:
                raise Conflict('Build source/image identity is immutable')
            if item.scanned_image_id and artifact['scanned_image_id'] not in (None, item.scanned_image_id):
                raise Conflict('Scanned image identity is immutable')
            if any(key in artifact['refs'] and artifact['refs'][key] != value for key, value in static_refs.items()):
                raise Conflict('Build artifact hash changed')
            conn.execute(artifacts.update().where(artifacts.c.build_id == build_id).values(
                scanned_image_id=artifact['scanned_image_id'] or item.scanned_image_id,
                reported_high_critical=artifact['reported_high_critical'] if item.reported_high_critical is None else item.reported_high_critical,
                refs={**artifact['refs'], **static_refs}))
        else:
            conn.execute(builds.insert().values(id=build_id, project=self.settings.project, job=self.settings.job,
                         number=item.build_number, source_commit=item.source_commit, result='SUCCESS'))
            conn.execute(artifacts.insert().values(id=identity(build_id + '/artifact'), build_id=build_id, image=item.image,
                         scanned_image_id=item.scanned_image_id, reported_high_critical=item.reported_high_critical, refs=static_refs))
        row = deployment
        if row and (row['environment_commit'] != item.environment_commit or
                    (row['candidate_hash'] and item.candidate_hash and row['candidate_hash'] != item.candidate_hash) or
                    (row['source_uid'] and item.source_uid and row['source_uid'] != item.source_uid)):
            raise Conflict('Release Git/candidate/controller identity changed')
        if row and row['recovery_id'] != item.recovery_id:
            raise Conflict('Deployment recovery identity changed')
        from backend.recovery import authorize_deployment
        recovery = authorize_deployment(self, conn, env, item, source)
        newer = row is None or item.observation_sequence > row['observation_sequence']
        values = dict(candidate_hash=item.candidate_hash or (row['candidate_hash'] if row else None),
                      status=item.status, observation_sequence=item.observation_sequence,
                      source_uid=item.source_uid or (row['source_uid'] if row else None), observed_at=item.observed_at,
                      promoted_at=(row['promoted_at'] if row else None) or (item.observed_at if item.status == 'promoted' else None))
        if row is None:
            conn.execute(releases.insert().values(id=release_id, environment_id=self.env_id, build_id=build_id,
                         environment_commit=item.environment_commit, recovery_id=item.recovery_id, **values))
        elif newer:
            conn.execute(releases.update().where(releases.c.id == release_id).values(**values))
        if newer:
            for analysis in item.analyses:
                conn.execute(insert(self.t('analyses')).values(id=identity(release_id + '/' + analysis.name),
                             release_id=release_id, name=analysis.name, phase=analysis.phase,
                             data=analysis.model_dump(mode='json')).on_conflict_do_update(
                                 index_elements=['release_id', 'name'], set_={'phase': analysis.phase, 'data': analysis.model_dump(mode='json')}))
        conn.execute(self.t('observations').insert().values(id=str(uuid.uuid4()), release_id=release_id, event_id=event_id,
                     quality=item.quality, stable_requests=item.stable_requests, stable_non_200=item.stable_non_200,
                     data={**item.observation_details, 'artifacts': item.artifacts, 'status': item.status,
                           'observation_sequence': item.observation_sequence, 'source_uid': item.source_uid,
                           'observed_at': item.observed_at.isoformat(), 'stable_revision': item.stable_revision,
                           'stable_hash': item.stable_hash}))
        latest_number = 0
        if env['desired_release_id']:
            latest_number = conn.scalar(select(builds.c.number).join(releases, releases.c.build_id == builds.c.id)
                                        .where(releases.c.id == env['desired_release_id']))
        live_refresh = (row is not None and source != 'import' and item.source_uid is not None and
                        item.observation_sequence == row['observation_sequence'] and item.status == row['status'] and
                        item.candidate_hash == row['candidate_hash'] and item.source_uid == row['source_uid'] and
                        item.stable_hash == env['stable_hash'] and item.stable_revision == env['stable_revision'])
        sequence_ok = item.observation_sequence >= env['observation_sequence'] if source != 'import' else not env['source_uid']
        applied = (newer or live_refresh) and sequence_ok and (item.build_number >= latest_number or recovery is not None)
        if applied:
            if source != 'import' and item.source_uid:
                if env['source_uid'] not in (None, item.source_uid):
                    raise Conflict('Controller identity changed; explicit environment re-enrollment is required')
                env['source_uid'] = item.source_uid
                env['observation_sequence'] = item.observation_sequence
            env['desired_release_id'] = release_id
            if item.stable_revision:
                stable_sha, stable_number = item.stable_revision.split('-jenkins-')
                stable_id = release_id if item.status == 'promoted' else conn.scalar(
                    select(releases.c.id).join(builds, releases.c.build_id == builds.c.id).where(
                        releases.c.environment_id == self.env_id, builds.c.number == int(stable_number),
                        builds.c.source_commit == stable_sha, releases.c.candidate_hash == item.stable_hash)
                    .order_by(releases.c.observed_at.desc()).limit(1))
                env.update(stable_release_id=stable_id, stable_revision=item.stable_revision,
                           stable_hash=item.stable_hash, stable_image=item.stable_image)
            if source == 'import':
                env.update(freshness='historical', last_observed_at=item.observed_at, detail='Imported historical evidence')
            elif item.status != 'published' and item.stable_revision:
                observed = max(env['last_observed_at'], item.observed_at) if live_refresh and env['last_observed_at'] else item.observed_at
                env.update(freshness='current', last_observed_at=observed, detail=None)
            if recovery and recovery['phase'] == 'applying':
                from backend.recovery import transition
                transition(self, conn, env, recovery, event_id, 'verifying',
                           commit=item.environment_commit, evidence={'source': 'signed-observer'})
        return {'release_id': release_id, 'build': item.build_number, 'status': item.status,
                'quality': item.quality, 'state_applied': applied}

    def release(self, conn, release_id):
        if release_id is None:
            return None
        row = conn.execute(select(self.t('releases')).where(self.t('releases').c.id == release_id)).mappings().first()
        if not row or row['environment_id'] != self.env_id:
            return None
        result = dict(row)
        result['build'] = dict(conn.execute(select(self.t('builds')).where(self.t('builds').c.id == row['build_id'])).mappings().one())
        result['artifact'] = dict(conn.execute(select(self.t('artifacts')).where(self.t('artifacts').c.build_id == row['build_id'])).mappings().one())
        result['analyses'] = [dict(x) for x in conn.execute(select(self.t('analyses')).where(self.t('analyses').c.release_id == release_id).order_by(self.t('analyses').c.name)).mappings()]
        result['observations'] = [dict(x) for x in conn.execute(select(self.t('observations')).where(self.t('observations').c.release_id == release_id).order_by(self.t('observations').c.id)).mappings()]
        return result

    def state(self):
        with self.db.engine.connect() as conn:
            row = dict(conn.execute(select(self.t('environments')).where(self.t('environments').c.id == self.env_id)).mappings().one())
            row['desired'] = self.release(conn, row['desired_release_id'])
            row['stable'] = self.release(conn, row['stable_release_id'])
            if row['freshness'] == 'current':
                age = (datetime.now(timezone.utc) - row['last_observed_at']).total_seconds()
                row['freshness'] = 'stale' if age > self.settings.stale_seconds else ('unknown' if age < -30 else 'current')
            return row

    def history(self, limit=50, offset=0):
        releases, builds = self.t('releases'), self.t('builds')
        with self.db.engine.connect() as conn:
            ids = conn.scalars(select(releases.c.id).join(builds, releases.c.build_id == builds.c.id)
                               .where(releases.c.environment_id == self.env_id).order_by(builds.c.number.desc()).limit(limit).offset(offset))
            return [self.release(conn, value) for value in ids]

    def audit(self, limit=50):
        table = self.t('audit')
        with self.db.engine.connect() as conn:
            return [dict(x) for x in conn.execute(select(table).where(table.c.environment_id == self.env_id)
                                                 .order_by(table.c.id.desc()).limit(limit)).mappings()]

    def builds(self, limit=50):
        table = self.t('builds')
        with self.db.engine.connect() as conn:
            result = []
            for row in conn.execute(select(table).where(table.c.project == self.settings.project)
                                    .order_by(table.c.number.desc()).limit(limit)).mappings():
                item = dict(row)
                artifact = conn.execute(select(self.t('artifacts')).where(self.t('artifacts').c.build_id == row['id'])).mappings().first()
                item['artifact'] = dict(artifact) if artifact else None
                result.append(item)
            return result
