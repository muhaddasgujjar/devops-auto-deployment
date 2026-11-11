import hashlib
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from pathlib import Path

import httpx
from sqlalchemy import text

import backend_tests.test_state as fixtures
import backend_tests.test_recovery as recovery_fixtures
from backend.monitoring import canonical
from backend.notification_receiver import create_receiver
from backend.notification_worker import local_url


class MonitoringPostgreSQLTests(unittest.TestCase):
    setUpClass=classmethod(fixtures.PostgreSQLStateTests.setUpClass.__func__)
    tearDownClass=classmethod(fixtures.PostgreSQLStateTests.tearDownClass.__func__)
    setUp=fixtures.PostgreSQLStateTests.setUp
    tearDown=fixtures.PostgreSQLStateTests.tearDown
    version=fixtures.PostgreSQLStateTests.version
    report=fixtures.PostgreSQLStateTests.report
    import_report=fixtures.PostgreSQLStateTests.import_report
    signed=fixtures.PostgreSQLStateTests.signed
    observation=fixtures.PostgreSQLStateTests.observation
    denied=fixtures.PostgreSQLStateTests.denied
    seed=recovery_fixtures.RecoveryPostgreSQLTests.seed
    windows=recovery_fixtures.RecoveryPostgreSQLTests.windows
    incident=recovery_fixtures.RecoveryPostgreSQLTests.incident
    move=recovery_fixtures.RecoveryPostgreSQLTests.move

    def tick(self,available=True,alerts=None):
        return self.client.post('/monitoring/tick',json={'observed_at':datetime.now(timezone.utc).isoformat(),
            'telemetry_available':available,'alerts':alerts or []})

    def view(self): return self.client.get('/monitoring').json()
    def claim(self): return self.client.post('/notifications/claim').json()
    def finish(self,row,success=True,**changes):
        return self.client.post('/notifications/'+row['id']+'/result',json={
            'lease_id':row['lease_id'],'delivered':success,'result':'receiver_acknowledged' if success else 'receiver_unavailable',
            'receipt_id':row['id'] if success else None,'receipt_sha256':row['payload_sha256'] if success else None,**changes})

    def test_transactional_alert_transition_dedup_and_resolution(self):
        item=self.observation()
        self.assertEqual(self.signed({'event_id':'initial','expected_version':self.version(),'release':item.model_dump(mode='json')}).status_code,200)
        for i in range(2):
            self.assertEqual(self.signed({'event_id':'outage'+str(i),'expected_version':self.version(),
                'unavailable':'sources_unavailable'}).status_code,200)
        view=self.view(); self.assertEqual(len(view['notifications']),1)
        self.assertEqual(view['alerts'][0]['kind'],'observation_unavailable')
        self.assertEqual(view['notifications'][0]['payload']['desired']['build'],20)
        self.assertEqual(self.signed({'event_id':'fresh','expected_version':self.version(),'release':item.model_dump(mode='json')}).status_code,200)
        self.assertEqual(len(self.view()['notifications']),2)
        self.assertEqual(self.view()['alerts'][0]['state'],'resolved')

    def test_signal_pending_firing_resolution_and_missing_are_distinct(self):
        item={'name':'DemoRequestErrors','revision':'abc123','state':'pending'}
        self.assertEqual(self.tick(alerts=[item]).status_code,200); self.assertEqual(self.view()['alerts'],[])
        self.tick(alerts=[{**item,'state':'firing'}]); self.tick(alerts=[{**item,'state':'firing'}])
        self.assertEqual(len(self.view()['notifications']),1)
        self.tick(); self.tick(False)
        kinds={x['kind']:x['state'] for x in self.view()['alerts']}
        self.assertEqual(kinds,{'workload_signal':'resolved','telemetry_unavailable':'firing'})

    def test_candidate_and_post_promotion_failure_have_different_kinds(self):
        self.seed(); self.windows()
        self.assertIn('post_promotion_incident',{x['kind'] for x in self.view()['alerts'] if x['state']=='firing'})
        self.assertEqual(self.move('failed',outcome='git_unavailable').status_code,200)
        active={x['kind'] for x in self.view()['alerts'] if x['state']=='firing'}
        self.assertEqual(active,{'recovery_failed'})
        newer=self.observation(build=21,seq=400)
        self.assertEqual(self.signed({'event_id':'newer','expected_version':self.version(),'release':newer.model_dump(mode='json')}).status_code,200)
        self.assertFalse(any(x['state']=='firing' for x in self.view()['alerts']))
        rejected=self.observation(build=22,seq=500).model_copy(update={'status':'rejected','stable_revision':newer.stable_revision})
        self.assertEqual(self.signed({'event_id':'candidate','expected_version':self.version(),'release':rejected.model_dump(mode='json')}).status_code,200)
        self.assertIn('candidate_rejected',{x['kind'] for x in self.view()['alerts'] if x['state']=='firing'})

    def test_missing_telemetry_cannot_resolve_a_firing_workload_signal(self):
        self.tick(alerts=[{'name':'DemoRequestErrors','revision':'abc','state':'firing'}])
        self.tick(False)
        self.assertEqual({x['kind'] for x in self.view()['alerts'] if x['state']=='firing'},
                         {'workload_signal','telemetry_unavailable'})
        self.tick(True)
        self.assertFalse(any(x['state']=='firing' for x in self.view()['alerts']))

    def test_missing_demo_scrapes_preserve_error_until_current_evidence_returns(self):
        self.tick(alerts=[{'name':'DemoRequestErrors','revision':'abc','state':'firing'}])
        self.tick(alerts=[{'name':'DemoPodsUnavailable','revision':'','state':'pending'}])
        self.assertEqual({x['subject'] for x in self.view()['alerts'] if x['state']=='firing'},{'DemoRequestErrors:abc'})
        self.tick(alerts=[{'name':'DemoPodsUnavailable','revision':'','state':'firing'}])
        self.assertEqual(len([x for x in self.view()['alerts'] if x['state']=='firing']),2)
        self.tick(True)
        self.assertFalse(any(x['state']=='firing' for x in self.view()['alerts']))

    def test_retry_backoff_is_bounded_and_wrong_ack_cannot_succeed(self):
        self.tick(False); row=self.claim()
        self.assertEqual(self.finish(row,receipt_sha256='0'*64).status_code,422)
        for attempt in range(1,6):
            if attempt>1: row=self.claim()
            self.assertEqual(row['attempts'],attempt)
            self.assertEqual(self.finish(row,False).status_code,200)
            self.assertIsNone(self.claim())
            # Only isolated fixture time is advanced; live acceptance waits normally.
            with self.clean_engine.begin() as conn:
                conn.execute(text("UPDATE notification_outbox SET next_attempt_at=now()-interval '1 second'"))
        self.assertEqual(self.view()['notifications'][0]['state'],'dead')
        self.assertEqual(len([x for x in self.view()['delivery_events'] if x['phase']=='claimed']),5)
        self.assertEqual(self.finish(row).status_code,409)

    def test_resolution_cannot_overtake_a_retrying_firing_notification(self):
        self.tick(False); self.tick(True)
        firing=self.claim(); self.assertEqual(firing['payload']['state'],'firing')
        self.finish(firing,False)
        self.assertIsNone(self.claim())
        with self.clean_engine.begin() as conn:
            conn.execute(text("UPDATE notification_outbox SET next_attempt_at=now()-interval '1 second'"))
        retry=self.claim(); self.assertEqual(retry['id'],firing['id'])
        self.finish(retry)
        resolved=self.claim(); self.assertEqual(resolved['payload']['state'],'resolved')

    def test_crash_after_receiver_ack_replays_one_durable_inbox_entry(self):
        self.tick(False); original=self.claim()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'inbox.sqlite3'; token='local-test-receiver-token-'*2
            for i in range(2):
                server=create_receiver(path,token,0); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
                try:
                    with httpx.Client(base_url='http://127.0.0.1:'+str(server.server_port),trust_env=False) as client:
                        response=client.post('/notifications',content=canonical(original['payload']),headers={
                            'Authorization':'Bearer '+token,'Idempotency-Key':original['id']})
                        self.assertEqual(response.status_code,200)
                finally: server.shutdown(); server.server_close(); thread.join()
                if not i:
                    with self.clean_engine.begin() as conn:
                        conn.execute(text("UPDATE notification_outbox SET lease_until=now()-interval '1 second'"))
                    replay=self.claim(); self.assertEqual(replay['id'],original['id']); self.assertNotEqual(replay['lease_id'],original['lease_id'])
            self.assertEqual(self.finish(original).status_code,409)
            self.assertEqual(self.finish(replay).status_code,200)
            import sqlite3
            with sqlite3.connect(path) as conn: self.assertEqual(conn.execute('SELECT count(*) FROM receipts').fetchone()[0],1)
        self.assertIsNone(self.claim())

    def test_roles_immutable_sql_and_probe_age(self):
        for role in ('read','developer'):
            self.client.headers['X-API-Key']=self.tokens[role]
            self.assertEqual(self.tick().status_code,403)
            self.assertEqual(self.client.post('/notifications/claim').status_code,403)
        token='notifier-test-key-01234567890123456789'
        self.settings.api_keys[hashlib.sha256(token.encode()).hexdigest()]='notifier'
        self.client.headers['X-API-Key']=token
        self.assertEqual(self.tick().status_code,200)
        self.assertEqual(self.client.post('/imports',json={}).status_code,403)
        self.assertEqual(self.client.get('/audit').status_code,403)
        self.assertEqual(self.client.post('/recovery/health',json={}).status_code,403)
        self.assertEqual(self.client.post('/auth/session',json={'key':token},headers={'Origin':'http://127.0.0.1'}).status_code,403)
        for seconds in (-60,60):
            response=self.client.post('/monitoring/tick',json={'observed_at':(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat(),'telemetry_available':True})
            self.assertEqual(response.status_code,422)
        for statement in ('DELETE FROM notification_outbox',"UPDATE notification_outbox SET payload='{}'",
                          "UPDATE monitoring_events SET actor='forged'",'DELETE FROM notification_events'):
            self.denied(statement)


class ReceiverTests(unittest.TestCase):
    def test_concurrent_duplicate_conflict_auth_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'receiver.db'; token='receiver-test-token-'*3
            server=create_receiver(path,token,0); thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            payload={'id':'b'*36,'kind':'test'}
            def send(changes=None,authorized=True):
                with httpx.Client(trust_env=False,timeout=5) as client:
                    return client.post('http://127.0.0.1:'+str(server.server_port)+'/notifications',json={**payload,**(changes or {})},
                        headers={'Authorization':'Bearer '+token if authorized else 'bad','Idempotency-Key':payload['id']})
            try:
                with ThreadPoolExecutor(max_workers=6) as pool: self.assertEqual([r.status_code for r in pool.map(lambda _:send(),range(6))],[200]*6)
                self.assertEqual(send({'kind':'changed'}).status_code,409)
                self.assertEqual(send(authorized=False).status_code,401)
            finally: server.shutdown(); server.server_close(); thread.join()

    def test_remote_and_credential_urls_are_rejected(self):
        for value in ('https://127.0.0.1','http://example.com','http://key@localhost','http://localhost/a','http://localhost?key=secret'):
            with self.assertRaises(ValueError): local_url(value)
