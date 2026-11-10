import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from backend.api import content_hash, create_app
from backend.config import load_settings
from backend.contracts import ReleaseObservation
from backend.imports import normalize
from backend.service import Conflict
from backend.security import configure_database, connect, load_url
from scripts.render_release import ROOT


class PostgreSQLStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = load_settings()
        cls.bootstrap_url = load_url('RELEASE_BOOTSTRAP_CONFIG_FILE')
        cls.migration_url = load_url('RELEASE_MIGRATION_CONFIG_FILE')
        cls.db_name = 'release_state_test_' + uuid.uuid4().hex[:12]
        cls.admin = create_engine(cls.bootstrap_url, isolation_level='AUTOCOMMIT')
        with cls.admin.connect() as conn:
            conn.execute(text('CREATE DATABASE ' + cls.db_name))
        test_bootstrap = make_url(cls.bootstrap_url).set(database=cls.db_name).render_as_string(hide_password=False)
        with connect(test_bootstrap) as conn:
            configure_database(conn)
        cls.tokens = {role: 'test-' + role + '-key-01234567890123456789' for role in ('read', 'developer', 'admin')}
        cls.settings = replace(cls.base,
            database_url=make_url(cls.base.database_url).set(database=cls.db_name).render_as_string(hide_password=False),
            api_keys={hashlib.sha256(value.encode()).hexdigest(): role for role, value in cls.tokens.items()},
            callback_secret='test-callback-secret-' * 3)
        cls.previous_config = os.environ['RELEASE_CONFIG_FILE']
        cls.previous_migration = os.environ['RELEASE_MIGRATION_CONFIG_FILE']
        cls.private_directory = tempfile.TemporaryDirectory(prefix='release-backend-test-')
        cls.config_path = Path(cls.private_directory.name) / 'runtime.json'
        fd = os.open(cls.config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(asdict(cls.settings), stream)
        os.environ['RELEASE_CONFIG_FILE'] = str(cls.config_path)
        cls.test_migration = make_url(cls.migration_url).set(database=cls.db_name).render_as_string(hide_password=False)
        migration_path = Path(cls.private_directory.name) / 'migration.json'
        fd = os.open(migration_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'database_url': cls.test_migration}, stream)
        os.environ['RELEASE_MIGRATION_CONFIG_FILE'] = str(migration_path)
        command.upgrade(Config(str(ROOT / 'alembic.ini')), 'head')
        with connect(test_bootstrap) as conn:
            configure_database(conn)
        cls.clean_engine = create_engine(test_bootstrap)

    @classmethod
    def tearDownClass(cls):
        cls.clean_engine.dispose()
        assert cls.db_name.startswith('release_state_test_') and len(cls.db_name) == 31
        with cls.admin.connect() as conn:
            conn.execute(text('DROP DATABASE ' + cls.db_name + ' WITH (FORCE)'))
        cls.admin.dispose()
        os.environ['RELEASE_CONFIG_FILE'] = cls.previous_config
        os.environ['RELEASE_MIGRATION_CONFIG_FILE'] = cls.previous_migration
        cls.private_directory.cleanup()

    def setUp(self):
        with self.clean_engine.begin() as conn:
            conn.execute(text('TRUNCATE projects CASCADE'))
        self.context = TestClient(create_app(self.settings), base_url='http://127.0.0.1')
        self.client = self.context.__enter__()
        self.client.headers['X-API-Key'] = self.tokens['admin']
        self.service = self.client.app.state.service

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def version(self):
        return self.client.get('/environment').json()['version']

    def report(self, kind='ci_acceptance', event='report'):
        file = 'ci-gitops-acceptance.json' if kind == 'ci_acceptance' else 'runtime-failure-validation.json'
        return {'event_id': event, 'expected_version': self.version(), 'kind': kind,
                'report': json.loads((ROOT / 'docs/evidence' / file).read_text())}

    def import_report(self, kind='ci_acceptance', event='report'):
        response = self.client.post('/imports', json=self.report(kind, event))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def counts(self):
        with self.service.db.engine.connect() as conn:
            return {name: conn.scalar(text('SELECT count(*) FROM ' + name))
                    for name in ('builds', 'releases', 'incoming_events', 'observations', 'audit')}

    def observation(self, build=20, seq=100):
        sha = 'a' * 40
        return ReleaseObservation(build_number=build, source_commit=sha,
            image='localhost:5001/release-demo@sha256:' + 'b' * 64, environment_commit='c' * 40,
            candidate_hash='abcde12345', status='promoted', observation_sequence=seq, source_uid='test-rollout-uid',
            observed_at=datetime.now(timezone.utc), stable_revision=f'{sha}-jenkins-{build}',
            stable_hash='abcde12345')

    def signed(self, payload, stamp=None, forged=False):
        raw = json.dumps(payload, separators=(',', ':')).encode()
        stamp = str(int(time.time())) if stamp is None else str(stamp)
        signature = 'v1=' + hmac.new(self.settings.callback_secret.encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
        return self.client.post('/callbacks', content=raw, headers={'Content-Type': 'application/json',
            'X-Release-Timestamp': stamp, 'X-Release-Signature': 'v1=bad' if forged else signature})

    def observe(self, item, event=None):
        return self.signed({'event_id': event or uuid.uuid4().hex, 'expected_version': self.version(),
                            'release': item.model_dump(mode='json')})

    def test_reimport_is_durable_and_version_independent(self):
        self.import_report()
        response = self.client.post('/imports', json=self.report())
        self.assertTrue(response.json()['duplicate'])
        self.assertEqual(self.counts(), dict(builds=1, releases=1, incoming_events=1, observations=1, audit=1))

    def test_conflicting_event_id_is_rejected(self):
        self.import_report()
        payload = self.report(); payload['report']['ci_duration_ms'] += 1
        self.assertEqual(self.client.post('/imports', json=payload).status_code, 409)
        self.assertEqual(self.counts()['incoming_events'], 1)

    def test_real_reports_preserve_excluded_attempt_and_stable_state(self):
        self.import_report()
        self.import_report('runtime_acceptance', 'runtime')
        state = self.client.get('/environment').json()
        self.assertEqual(state['desired']['build']['number'], 16)
        self.assertEqual(state['stable']['build']['number'], 16)
        self.assertEqual(state['freshness'], 'historical')
        self.assertEqual(self.counts()['releases'], 9)
        rejected = next(x for x in self.client.get('/releases').json() if x['build']['number'] == 12)
        self.assertEqual(rejected['observations'][0]['quality'], 'excluded')
        self.assertIn('538.000s', rejected['observations'][0]['data']['exclusion_reason'])

    def test_rejected_candidate_and_stable_are_distinct(self):
        self.import_report()
        item = normalize('runtime_acceptance', self.report('runtime_acceptance')['report'])[0]
        item = item.model_copy(update={'quality': 'not_measured', 'observation_sequence': 100, 'source_uid': 'test-rollout-uid'})
        self.assertEqual(self.observe(item).status_code, 200)
        state = self.client.get('/environment').json()
        self.assertEqual(state['desired']['build']['number'], 9)
        self.assertEqual(state['desired']['status'], 'rejected')
        self.assertEqual(state['stable']['build']['number'], 8)

    def test_old_build_cannot_overwrite_new_environment(self):
        self.assertEqual(self.observe(self.observation(21)).status_code, 200)
        self.assertEqual(self.observe(self.observation(20, 999)).status_code, 200)
        self.assertEqual(self.client.get('/environment').json()['desired']['build']['number'], 21)

    def test_out_of_order_same_release_cannot_regress_promotion(self):
        item = self.observation()
        self.observe(item)
        old = item.model_copy(update={'status': 'progressing', 'observation_sequence': 90})
        self.assertFalse(self.observe(old).json()['changes'][0]['state_applied'])
        self.assertEqual(self.client.get('/environment').json()['desired']['status'], 'promoted')

    def race(self, duplicate):
        barrier = threading.Barrier(2)
        def apply(index):
            item = self.observation(20 if duplicate else 20 + index)
            # Identical event content, including observation time, for duplicate delivery.
            payload = {'event_id': 'same' if duplicate else 'event' + str(index), 'release': item.model_dump(mode='json')}
            if duplicate:
                payload = fixed_payload
                item = fixed_item
            barrier.wait(timeout=10)
            try:
                return self.service.ingest(external_id=payload['event_id'], expected_version=0, payload=payload,
                    payload_hash=content_hash(payload), releases=[item], actor='test-race', source='callback')
            except Conflict:
                return 'conflict'
        fixed_item = self.observation()
        fixed_payload = {'event_id': 'same', 'release': fixed_item.model_dump(mode='json')}
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(apply, (0, 1)))

    def test_postgres_serializes_competing_environment_writers(self):
        results = self.race(False)
        self.assertEqual(results.count('conflict'), 1)
        self.assertEqual(self.counts()['incoming_events'], 1)
        self.assertEqual(self.version(), 1)

    def test_concurrent_duplicates_have_one_durable_effect(self):
        results = self.race(True)
        self.assertEqual(sorted(x['duplicate'] for x in results), [False, True])
        self.assertEqual(self.counts()['audit'], 1)

    def test_database_conflict_rolls_back_entire_batch(self):
        self.import_report()
        bad = normalize('ci_acceptance', self.report()['report'])[0].model_copy(update={
            'source_commit': 'd' * 40, 'stable_revision': 'd' * 40 + '-jenkins-8'})
        before = self.counts()
        with self.assertRaises(Conflict):
            self.service.ingest(external_id='rollback', expected_version=self.version(), payload={},
                payload_hash='e' * 64, releases=[self.observation(22), bad], actor='test', source='import')
        self.assertEqual(self.counts(), before)

    def test_malformed_report_does_not_partially_import(self):
        payload = self.report('runtime_acceptance')
        payload['report']['trials'][-1]['source_commit'] = 'malformed'
        self.assertEqual(self.client.post('/imports', json=payload).status_code, 422)
        self.assertEqual(self.counts()['builds'], 0)

    def test_authentication_roles_and_forged_signature(self):
        self.assertEqual(self.client.get('/environment', headers={'X-API-Key': 'bad'}).status_code, 401)
        self.assertEqual(self.client.post('/imports', json=self.report(), headers={'X-API-Key': self.tokens['read']}).status_code, 403)
        self.assertEqual(self.client.get('/audit', headers={'X-API-Key': self.tokens['developer']}).status_code, 403)
        payload = {'event_id': 'signed', 'expected_version': 0, 'release': self.observation().model_dump(mode='json')}
        self.assertEqual(self.signed(payload, forged=True).status_code, 401)
        raw = json.dumps(payload).encode()
        malformed = self.client.post('/callbacks', content=raw, headers={
            b'X-Release-Timestamp': str(int(time.time())).encode(), b'X-Release-Signature': b'\xff'})
        self.assertEqual(malformed.status_code, 401)
        self.assertEqual(self.signed(payload, stamp=int(time.time()) - 600).status_code, 401)
        self.assertEqual(self.signed(payload).status_code, 200)

    def test_streaming_body_limit(self):
        response = self.client.post('/imports', content=(b'x' * 65536 for _ in range(17)))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.counts()['incoming_events'], 0)

    def test_restart_preserves_identity_and_deduplication(self):
        self.import_report()
        before = self.client.get('/environment').json()
        with TestClient(create_app(self.settings)) as restarted:
            restarted.headers['X-API-Key'] = self.tokens['admin']
            self.assertEqual(restarted.get('/environment').json()['desired']['id'], before['desired']['id'])
            self.assertTrue(restarted.post('/imports', json=self.report()).json()['duplicate'])
        self.assertEqual(self.counts()['incoming_events'], 1)

    def test_outage_and_same_resource_version_refresh(self):
        item = self.observation()
        self.observe(item)
        payload = {'event_id': 'outage', 'expected_version': self.version(), 'unavailable': 'sources_unavailable'}
        self.assertEqual(self.signed(payload).status_code, 200)
        state = self.client.get('/environment').json()
        self.assertEqual(state['freshness'], 'unavailable')
        self.assertEqual(state['stable']['build']['number'], 20)
        refreshed = item.model_copy(update={'observed_at': datetime.now(timezone.utc)})
        self.assertTrue(self.observe(refreshed).json()['changes'][0]['state_applied'])
        self.assertEqual(self.client.get('/environment').json()['freshness'], 'current')

    def test_controller_replacement_is_not_silently_adopted(self):
        item = self.observation()
        self.observe(item)
        replacement = item.model_copy(update={'source_uid': 'different-controller', 'observation_sequence': 200})
        self.assertEqual(self.observe(replacement).status_code, 409)
        self.assertEqual(self.client.get('/environment').json()['source_uid'], item.source_uid)

    def test_old_observation_is_shown_as_stale(self):
        old = self.observation().model_copy(update={'observed_at': datetime.now(timezone.utc) - timedelta(hours=1)})
        self.observe(old)
        self.assertEqual(self.client.get('/environment').json()['freshness'], 'stale')

    def test_ci_publication_does_not_promote(self):
        self.import_report()
        item = self.observation(9).model_copy(update={'status': 'published', 'candidate_hash': None,
                                                     'stable_hash': None, 'stable_revision': None})
        self.assertEqual(self.observe(item).status_code, 200)
        state = self.client.get('/environment').json()
        self.assertEqual(state['desired']['status'], 'published')
        self.assertEqual(state['stable']['build']['number'], 8)

    def test_failed_ci_gate_has_no_artifact_or_release(self):
        payload = {'event_id': 'negative', 'expected_version': 0, 'kind': 'ci_negative_gate',
                   'report': json.loads((ROOT / 'docs/evidence/ci-negative-gate.json').read_text())}
        self.assertEqual(self.client.post('/imports', json=payload).status_code, 200)
        builds = self.client.get('/builds').json()
        self.assertEqual(builds[0]['result'], 'FAILURE')
        self.assertIsNone(builds[0]['artifact'])
        self.assertEqual(self.counts()['releases'], 0)
        self.assertIsNone(self.client.get('/environment').json()['desired'])

    def test_nonfinite_json_is_rejected_before_ingestion(self):
        raw = json.dumps(self.report()).replace('45262', 'NaN')
        self.assertIn('NaN', raw)
        self.assertEqual(self.client.post('/imports', content=raw).status_code, 422)

    def test_openapi_publishes_streamed_request_contracts(self):
        schema = self.client.get('/openapi.json').json()
        for path, name in (('/imports', 'ImportRequest'), ('/callbacks', 'CallbackRequest')):
            body = schema['paths'][path]['post']['requestBody']
            self.assertTrue(body['required'])
            self.assertEqual(body['content']['application/json']['schema']['$ref'], '#/components/schemas/' + name)
        def check_references(value):
            if isinstance(value, dict):
                if '$ref' in value:
                    target = schema
                    for part in value['$ref'].removeprefix('#/').split('/'):
                        target = target[part]
                for child in value.values():
                    check_references(child)
            elif isinstance(value, list):
                for child in value:
                    check_references(child)
        check_references(schema)

    def denied(self, statement):
        with self.assertRaises(DBAPIError):
            with self.service.db.engine.begin() as conn:
                conn.execute(text(statement))

    def test_runtime_has_no_administrative_role_flags(self):
        with self.service.db.engine.connect() as conn:
            row = conn.execute(text('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls '
                                    'FROM pg_roles WHERE rolname=current_user')).one()
            self.assertFalse(any(row))

    def test_runtime_cannot_create_or_alter_schema(self):
        self.denied('CREATE TABLE public.forbidden_probe (id integer)')
        self.denied('ALTER TABLE public.projects ADD COLUMN forbidden_probe integer')
        self.denied('CREATE DATABASE forbidden_probe')

    def test_runtime_cannot_rewrite_or_remove_audit(self):
        self.import_report()
        self.denied("UPDATE audit SET action='rewritten'")
        self.denied('DELETE FROM audit')
        self.denied('TRUNCATE audit')
        self.assertEqual(self.counts()['audit'], 1)

    def test_runtime_cannot_rewrite_event_identity_or_migration_revision(self):
        self.import_report()
        self.denied("UPDATE incoming_events SET payload_hash='" + '0' * 64 + "'")
        self.denied("UPDATE alembic_version SET version_num='forged'")
        self.denied('SET ROLE release_state_migrator')

    def test_migration_role_can_change_schema_without_superuser(self):
        engine = create_engine(self.test_migration)
        try:
            with engine.begin() as conn:
                self.assertFalse(conn.scalar(text('SELECT rolsuper FROM pg_roles WHERE rolname=current_user')))
                conn.execute(text('CREATE TABLE public.migration_probe (id integer)'))
                conn.execute(text('ALTER TABLE public.migration_probe ADD COLUMN value text'))
                conn.execute(text('DROP TABLE public.migration_probe'))
        finally:
            engine.dispose()

    def browser_login(self, role='read'):
        self.client.headers.pop('X-API-Key', None)
        response = self.client.post('/auth/session', json={'key': self.tokens[role]}, headers={'Origin': 'http://127.0.0.1'})
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_browser_cookie_logout_and_credential_non_disclosure(self):
        response = self.browser_login('admin')
        cookie = response.headers['set-cookie'].lower()
        self.assertIn('httponly', cookie)
        self.assertIn('samesite=strict', cookie)
        self.assertNotIn(self.tokens['admin'], response.text)
        self.assertEqual(self.client.get('/environment').status_code, 200)
        self.assertEqual(self.client.get('/audit').status_code, 200)
        self.assertEqual(self.client.delete('/auth/session').status_code, 403)
        logout = self.client.delete('/auth/session', headers={'Origin': 'http://127.0.0.1', 'X-CSRF-Token': response.json()['csrf_token']})
        self.assertEqual(logout.status_code, 200)
        self.assertEqual(self.client.get('/environment').status_code, 401)
        self.assertEqual(self.counts()['incoming_events'], 0)

    def test_browser_role_checks_apply_to_direct_api_requests(self):
        info = self.browser_login('read').json()
        self.assertEqual(self.client.get('/audit').status_code, 403)
        response = self.client.post('/imports', json=self.report(), headers={'Origin': 'http://127.0.0.1', 'X-CSRF-Token': info['csrf_token']})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.counts()['builds'], 0)

    def test_browser_writes_need_both_origin_and_csrf(self):
        info = self.browser_login('developer').json()
        payload = self.report()
        self.assertEqual(self.client.post('/imports', json=payload).status_code, 403)
        self.assertEqual(self.client.post('/imports', json=payload, headers={'Origin': 'http://127.0.0.1', 'X-CSRF-Token': 'wrong'}).status_code, 403)
        self.assertEqual(self.client.post('/imports', json=payload, headers={'Origin': 'http://evil.example', 'X-CSRF-Token': info['csrf_token']}).status_code, 403)
        response = self.client.post('/imports', json=payload, headers={'Origin': 'http://127.0.0.1', 'X-CSRF-Token': info['csrf_token']})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.service.audit()[0]['data']['actor'].startswith('browser:developer:'))

    def test_browser_login_requires_same_origin_and_rejects_bad_keys(self):
        self.client.headers.pop('X-API-Key', None)
        body = {'key': self.tokens['admin']}
        self.assertEqual(self.client.post('/auth/session', json=body).status_code, 403)
        self.assertEqual(self.client.post('/auth/session', json=body, headers={'Origin': 'http://evil.example'}).status_code, 403)
        self.assertEqual(self.client.post('/auth/session', json={'key': 'x' * 40}, headers={'Origin': 'http://127.0.0.1'}).status_code, 401)

    def test_browser_expiry_and_key_revocation(self):
        self.browser_login()
        self.client.app.state.browser_sessions.clock = lambda: time.time() + 4000
        self.assertEqual(self.client.get('/environment').status_code, 401)
        self.client.app.state.browser_sessions.clock = time.time
        self.browser_login()
        digest = hashlib.sha256(self.tokens['read'].encode()).hexdigest()
        role = self.settings.api_keys.pop(digest)
        try:
            self.assertEqual(self.client.get('/environment').status_code, 401)
        finally:
            self.settings.api_keys[digest] = role

    def test_browser_rotation_and_restart_reject_old_cookie(self):
        self.browser_login()
        old = self.client.cookies.get('release_lab_session')
        self.browser_login()
        response = self.client.get('/environment', headers={'Cookie': 'release_lab_session=' + old})
        self.assertEqual(response.status_code, 401)
        with TestClient(create_app(self.settings), base_url='http://127.0.0.1') as restarted:
            response = restarted.get('/environment', headers={'Cookie': 'release_lab_session=' + self.client.cookies.get('release_lab_session')})
            self.assertEqual(response.status_code, 401)

    def test_browser_login_body_bound_and_headers(self):
        response = self.client.post('/auth/session', content=b'x' * 5000, headers={'Origin': 'http://127.0.0.1', 'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')

    def test_portal_assets_are_served_without_database_or_key_material(self):
        self.client.headers.pop('X-API-Key', None)
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Release Lab', response.text)
        for token in self.tokens.values():
            self.assertNotIn(token, response.text)
        self.assertEqual(self.client.get('/environment').status_code, 401)
        self.assertEqual(self.client.get('/portal/../../backend/config.py').status_code, 404)
