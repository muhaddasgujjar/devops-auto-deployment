import copy
import hashlib
import hmac
import json
import os
import tempfile
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from apps.api.main import create_app
from apps.api.models import Base, AuditEvent, InboxEvent, OutboxEvent, Release
from apps.api.service import drain_inbox, ingest
from scripts.evidence import EvidenceStore
from scripts.render_release import ROOT


def fixture():
    return {'collected_at': '2026-10-23T12:00:00+00:00', 'errors': {}, 'components': {
        'builds': {'items': [{'id': 'release-main-1', 'number': 1, 'state': 'SUCCESS'}]},
        'rollout': {'spec': {'replicas': 2}, 'status': {'phase': 'Healthy', 'currentPodHash': 'abc'}},
        'services': {'spec': {'selector': {'rollouts-pod-template-hash': 'abc'}}},
        'monitoring': {'targets': [{'pod': 'one', 'up': True, 'revision': 'abc', 'age_seconds': 3},
                                  {'pod': 'two', 'up': True, 'revision': 'abc', 'age_seconds': 3}]},
        'recovery': {'phase': 'healthy'},
        'evidence': {'runs': [{'id': 'gitops-healthy-test', 'verdict': 'candidate-promoted-through-gitops',
            'summary': {'environment_commit': 'a' * 40, 'source_commit': 'b' * 40, 'release_id': 'jenkins-1',
                        'image': 'localhost:5001/demo@sha256:' + 'c' * 64}, 'archived_at': '2026-10-23T12:00:00Z'}]}}}


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        self.pg = None
        if os.environ.get('PORTAL_TEST_POSTGRES') == '1':
            from scripts.portal import environment
            root_url = environment()['RELEASE_DATABASE_URL']
            self.pg = create_engine(root_url)
            self.schema = 'portal_test_' + uuid.uuid4().hex
            with self.pg.begin() as connection:
                connection.execute(text('CREATE SCHEMA ' + self.schema))
            self.url = make_url(root_url).update_query_dict({'options': '-csearch_path=' + self.schema}).render_as_string(hide_password=False)
        else:
            self.url = 'sqlite:///' + str(self.base / 'product.db')
        with patch.dict(os.environ, {'RELEASE_DATABASE_URL': self.url}):
            command.upgrade(Config(str(ROOT / 'apps/api/alembic.ini')), 'head')
        self.app = create_app(self.url, observer=False, evidence_root=self.base / 'evidence')
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.sessions = self.app.state.sessions

    def tearDown(self):
        self.client.__exit__(None, None, None)
        if self.pg:
            with self.pg.begin() as connection:
                # The schema is generated here from a UUID and never comes from
                # a user path or an environment variable.
                connection.execute(text('DROP SCHEMA ' + self.schema + ' CASCADE'))
            self.pg.dispose()
        self.directory.cleanup()

    def sign(self, body, identity='delivery-1', timestamp=None):
        timestamp = str(timestamp or int(time.time()))
        signature = hmac.new(b'test-secret', timestamp.encode() + b'.' + identity.encode() + b'.' + body, hashlib.sha256).hexdigest()
        return {'x-release-event-id': identity, 'x-release-timestamp': timestamp,
                'x-release-signature': 'sha256=' + signature, 'content-type': 'application/json'}

    def test_migration_health_and_loopback_host_guard(self):
        self.assertEqual(self.client.get('/readyz').status_code, 200)
        self.assertEqual(self.client.get('/healthz').json(), {'status': 'ok'})
        self.assertEqual(self.client.get('/api/overview', headers={'host': 'attacker.example'}).status_code, 400)
        self.assertEqual(self.client.get('/api/overview').json()['status'], 'connecting')

    def test_readiness_fails_when_database_migrations_are_behind(self):
        with self.sessions.begin() as session:
            session.execute(text("UPDATE alembic_version SET version_num='obsolete-revision'"))
        self.assertEqual(self.client.get('/readyz').status_code, 503)
        self.assertEqual(self.client.get('/healthz').status_code, 200)

    def test_reconciliation_is_idempotent_and_transitions_are_durable(self):
        original = fixture()
        with self.sessions.begin() as session:
            ingest(session, original)
        with self.sessions.begin() as session:
            ingest(session, {**original, 'collected_at': '2026-10-23T12:01:00+00:00'})
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(AuditEvent)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(OutboxEvent)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Release)), 1)
        changed = copy.deepcopy(original)
        changed['components']['builds']['items'][0]['state'] = 'FAILURE'
        with self.sessions.begin() as session:
            ingest(session, changed)
        self.assertEqual(len(self.client.get('/api/activity').json()['items']), 2)
        self.assertEqual(self.client.get('/api/builds').json()[0]['state'], 'FAILURE')
        self.assertEqual(self.client.get('/api/overview').json()['rollout']['phase'], 'Healthy')
        self.assertEqual(len(self.client.get('/api/releases').json()), 1)
        self.assertEqual(len(self.client.get('/api/projects').json()), 1)

    def test_signed_events_deduplicate_across_restart_and_reject_payload_conflicts(self):
        body = b'{"kind":"release.observed","resource_id":"release-1","state":"healthy"}'
        with patch.dict(os.environ, {'RELEASE_CALLBACK_SECRET': 'test-secret'}):
            self.assertFalse(self.client.post('/api/integrations/events', content=body, headers=self.sign(body)).json()['duplicate'])
            with TestClient(create_app(self.url, observer=False)) as restarted:
                self.assertTrue(restarted.post('/api/integrations/events', content=body, headers=self.sign(body)).json()['duplicate'])
            other = body.replace(b'healthy', b'failed')
            self.assertEqual(self.client.post('/api/integrations/events', content=other, headers=self.sign(other)).status_code, 409)
        with self.sessions.begin() as session:
            drain_inbox(session)
        with self.sessions.begin() as session:
            drain_inbox(session)
        self.assertEqual(self.client.get('/api/activity').json()['pending_outbox'], 1)
        self.assertEqual(len(self.client.get('/api/activity').json()['items']), 1)

    def test_release_history_uses_time_instead_of_scenario_name(self):
        snapshot = fixture()
        snapshot['components']['evidence']['runs'] = [
            {'id': identity, 'verdict': 'test-verified', 'archived_at': started,
             'summary': {'release_id': identity, 'environment_commit': 'a' * 40, 'started': started}}
            for identity, started in [('zzz-old', '2026-10-22T12:00:00Z'), ('aaa-new', '2026-10-23T12:00:00Z')]]
        with self.sessions.begin() as session:
            ingest(session, snapshot)
        self.assertEqual([r['id'] for r in self.client.get('/api/releases').json()], ['aaa-new', 'zzz-old'])
        self.assertEqual([r['id'] for r in self.client.get('/api/evidence').json()], ['aaa-new', 'zzz-old'])

    def test_invalid_signature_stale_delivery_and_arbitrary_payload_are_rejected(self):
        body = b'{"kind":"build.observed","resource_id":"build-1","state":"success"}'
        with patch.dict(os.environ, {'RELEASE_CALLBACK_SECRET': 'test-secret'}):
            self.assertEqual(self.client.post('/api/integrations/events', content=body).status_code, 401)
            self.assertEqual(self.client.post('/api/integrations/events', content=body, headers=self.sign(body, timestamp=int(time.time())-400)).status_code, 401)
            headers = self.sign(body)
            headers['x-release-event-id'] = 'changed-identity'
            self.assertEqual(self.client.post('/api/integrations/events', content=body, headers=headers).status_code, 401)
            private = b'{"password":"do-not-store"}'
            self.assertEqual(self.client.post('/api/integrations/events', content=private, headers=self.sign(private)).status_code, 422)
            headers = self.sign(body)
            headers['x-release-timestamp'] = '9' * 5000
            self.assertEqual(self.client.post('/api/integrations/events', content=body, headers=headers).status_code, 401)
            self.assertEqual(self.client.post('/api/integrations/events', content=b'x' * 262145).status_code, 413)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(InboxEvent)), 0)

    def test_concurrent_duplicate_delivery_has_one_durable_receipt(self):
        body = b'{"kind":"build.observed","resource_id":"build-1","state":"success"}'
        with patch.dict(os.environ, {'RELEASE_CALLBACK_SECRET': 'test-secret'}):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self.client.post('/api/integrations/events', content=body, headers=self.sign(body)), range(2)))
        self.assertTrue(all(r.status_code == 202 for r in results))
        self.assertEqual(sum(not r.json()['duplicate'] for r in results), 1)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(InboxEvent)), 1)

    def test_evidence_download_is_catalogue_bound_and_detects_corruption(self):
        source = self.base / 'source'
        run = source / 'test-evidence'
        run.mkdir(parents=True)
        (run / 'summary.json').write_text('{"verdict":"test-verified"}')
        store = EvidenceStore(self.base / 'evidence')
        try:
            store.archive(run, source_root=source)
        finally:
            store.close()
        files = self.client.get('/api/evidence/test-evidence/files').json()
        sha = files[0]['sha256']
        self.assertEqual(self.client.get('/api/evidence/test-evidence/files/' + sha).status_code, 200)
        self.assertEqual(self.client.get('/api/evidence/another-run/files/' + sha).status_code, 404)
        (self.base / 'evidence/objects' / sha).write_bytes(b'corrupt')
        self.assertEqual(self.client.get('/api/evidence/test-evidence/files/' + sha).status_code, 409)
        self.assertEqual(self.client.get('/api/evidence/test-evidence/files/not-a-hash').status_code, 404)


if __name__ == '__main__':
    unittest.main()
