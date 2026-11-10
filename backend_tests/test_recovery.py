import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

import backend_tests.test_state as fixtures
from backend.contracts import ReleaseObservation, Analysis
from backend.recovery_policy import POLICY, measured, sustained, verdict


class RecoveryPolicyTests(unittest.TestCase):
    def data(self, **changes):
        return dict(requests=200, errors=0, p95_seconds=.1, up_min=1, up_count=2, scrape_age_seconds=5, **changes)

    def test_missing_empty_nan_and_low_traffic_are_inconclusive(self):
        base = self.data()
        for patch in ({'requests': 0}, {'requests': 99}, {'p95_seconds': float('nan')},
                      {'errors': None}, {'up_count': 1}, {'up_min': 0}, {'scrape_age_seconds': 16}):
            self.assertEqual(verdict({**base, **patch}), 'inconclusive')

    def test_error_and_latency_breaches_are_distinct_from_healthy(self):
        self.assertEqual(verdict(self.data()), 'healthy')
        self.assertEqual(verdict({**self.data(), 'errors': 11}), 'breach')
        self.assertEqual(verdict({**self.data(), 'p95_seconds': .51}), 'breach')

    def test_three_completed_consecutive_windows_and_freshness_are_required(self):
        now = datetime.now(timezone.utc)
        rows = [dict(window_end=now-timedelta(seconds=i*30), quality='measured', data={**self.data(), 'errors': 100}) for i in (2,1,0)]
        self.assertTrue(sustained(rows, 'breach', now=now))
        self.assertFalse(sustained(rows[:2], 'breach', now=now))
        self.assertFalse(sustained([rows[0], rows[0], rows[2]], 'breach', now=now))
        self.assertFalse(sustained(rows, 'breach', now=now+timedelta(seconds=91)))
        rows[1]['quality'] = 'unavailable'
        self.assertFalse(sustained(rows, 'breach', now=now))


class RecoveryPostgreSQLTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.PostgreSQLStateTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.PostgreSQLStateTests.tearDownClass.__func__)
    setUp = fixtures.PostgreSQLStateTests.setUp
    tearDown = fixtures.PostgreSQLStateTests.tearDown
    version = fixtures.PostgreSQLStateTests.version
    report = fixtures.PostgreSQLStateTests.report
    import_report = fixtures.PostgreSQLStateTests.import_report
    signed = fixtures.PostgreSQLStateTests.signed
    observation = fixtures.PostgreSQLStateTests.observation
    denied = fixtures.PostgreSQLStateTests.denied

    def seed(self, target=True):
        if target:
            self.import_report()
            self.target = self.client.get('/releases').json()[0]
            # Synthetic controller analysis supplements this isolated fixture's
            # curated HTTP/scan import; it is not used as live target evidence.
            item=ReleaseObservation(build_number=self.target['build']['number'],source_commit=self.target['build']['source_commit'],
                image=self.target['artifact']['image'],environment_commit=self.target['environment_commit'],
                candidate_hash=self.target['candidate_hash'],stable_hash=self.target['candidate_hash'],
                stable_revision=f"{self.target['build']['source_commit']}-jenkins-{self.target['build']['number']}",
                status='promoted',source_uid='test-rollout-uid',observation_sequence=50,
                observed_at=datetime.now(timezone.utc)-timedelta(seconds=600),
                analyses=[Analysis(name='unit-pre-analysis',phase='Successful')])
            self.assertEqual(self.signed({'event_id':'unit-target-analysis','expected_version':self.version(),
                                         'release':item.model_dump(mode='json')}).status_code,200)
            with self.clean_engine.begin() as conn:
                conn.execute(text("UPDATE releases SET promoted_at=now()-interval '600 seconds' WHERE id=:id"),
                             {'id': self.target['id']})
        item = self.observation().model_copy(update={'observed_at': datetime.now(timezone.utc)-timedelta(seconds=180)})
        self.assertEqual(self.signed({'event_id':'origin','expected_version':self.version(),'release':item.model_dump(mode='json')}).status_code,200)
        self.origin = self.client.get('/environment').json()['desired']

    def windows(self, *, errors=200, quality='measured', start=2):
        now = datetime.now(timezone.utc)
        end = datetime.fromtimestamp(int(now.timestamp())//30*30,timezone.utc)
        for i in range(start,-1,-1):
            state = self.client.get('/environment').json()
            payload = {'event_id':str(end.timestamp())+str(i)+state['desired']['id'], 'expected_version':self.version(),
                'release_id':state['desired']['id'],'pod_hash':state['stable_hash'],
                'window_end':(end-timedelta(seconds=i*30)).isoformat(),'quality':quality,
                'data':dict(requests=200,errors=errors,p95_seconds=.1,up_min=1,up_count=2,scrape_age_seconds=5)}
            response = self.client.post('/recovery/health',json=payload)
            self.assertEqual(response.status_code,200,response.text)

    def incident(self):
        return self.client.get('/recoveries').json()[0]

    def move(self, phase, **fields):
        row = self.incident()
        response = self.client.post('/recoveries/'+row['id']+'/events',json={
            'event_id':row['id']+phase,'expected_version':self.version(),
            'expected_recovery_version':row['version'],'phase':phase,**fields})
        return response

    def prepare_verification(self):
        self.seed(); self.windows()
        self.assertEqual(self.move('applying').status_code,200)
        self.assertEqual(self.move('verifying',recovery_commit='d'*40).status_code,200)
        # Advance the isolated ledger's clock to simulate elapsed verification;
        # live acceptance never edits timestamps or fabricates healthy samples.
        with self.clean_engine.begin() as conn:
            conn.execute(text("UPDATE recoveries SET created_at=now()-interval '200 seconds', updated_at=now()-interval '150 seconds'"))
        row = self.incident()
        target = ReleaseObservation(build_number=self.target['build']['number'],source_commit=self.target['build']['source_commit'],
            image=self.target['artifact']['image'],environment_commit='d'*40,candidate_hash=self.target['candidate_hash'],
            stable_hash=self.target['candidate_hash'],stable_revision=f"{self.target['build']['source_commit']}-jenkins-{self.target['build']['number']}",
            stable_image=self.target['artifact']['image'],status='promoted',source_uid='test-rollout-uid',observation_sequence=300,
            observed_at=datetime.now(timezone.utc)-timedelta(seconds=120),recovery_id=row['id'])
        response = self.signed({'event_id':'recovered-observer','expected_version':self.version(),'release':target.model_dump(mode='json')})
        self.assertEqual(response.status_code,200,response.text)
        return target

    def test_incident_requires_three_bad_windows_and_selects_accepted_target(self):
        self.seed(); self.windows(start=1)
        self.assertEqual(self.client.get('/recoveries').json(),[])
        # Add the missing oldest window in a new order; detection still requires
        # contiguous event time, not three arbitrary bad readings.
        now=datetime.now(timezone.utc); end=datetime.fromtimestamp(int(now.timestamp())//30*30,timezone.utc)
        data={'event_id':'oldest','expected_version':self.version(),'release_id':self.origin['id'],
              'pod_hash':self.origin['candidate_hash'],'window_end':(end-timedelta(seconds=60)).isoformat(),
              'quality':'measured','data':dict(requests=200,errors=200,p95_seconds=.1,up_min=1,up_count=2,scrape_age_seconds=5)}
        self.assertEqual(self.client.post('/recovery/health',json=data).status_code,200)
        self.assertEqual(self.incident()['target_release_id'],self.target['id'])
        self.assertEqual(self.incident()['phase'],'proposed')
        again=self.client.post('/recovery/health',json=data)
        self.assertTrue(again.json()['duplicate'])
        self.assertEqual(len(self.client.get('/recoveries').json()),1)

    def test_missing_telemetry_does_not_open_an_incident(self):
        self.seed(); self.windows(quality='unavailable')
        self.assertEqual(self.client.get('/recoveries').json(),[])

    def test_no_accepted_target_records_failure_without_actuation(self):
        self.seed(target=False); self.windows()
        self.assertEqual(self.incident()['phase'],'failed')
        self.assertEqual(self.incident()['outcome'],'no_accepted_target')
        self.assertEqual(self.move('applying').status_code,409)

    def test_completed_recovery_preserves_original_release_and_rejects_old_observation(self):
        target=self.prepare_verification(); self.windows(errors=0)
        original=self.client.get('/releases/'+self.target['id']).json()
        current=self.client.get('/environment').json()
        self.assertNotEqual(current['desired']['id'],self.target['id'])
        self.assertEqual(original['environment_commit'],self.target['environment_commit'])
        # Refresh the signed serving observation without changing promotion time.
        self.assertEqual(self.signed({'event_id':'fresh-target','expected_version':self.version(),
            'release':target.model_copy(update={'observed_at':datetime.now(timezone.utc)}).model_dump(mode='json')}).status_code,200)
        proof={'requests':120,'target_requests':120,'identity_mismatches':0,'non_200':0,'maximum_gap_seconds':.1,'revision':target.stable_revision,
               'environment_commit':'d'*40,'controller_uid':'test-rollout-uid',
               'image':target.image,'pod_hash':target.candidate_hash}
        result=self.move('recovered',outcome='healthy_target_verified',evidence=proof)
        self.assertEqual(result.status_code,200,result.text+' '+json.dumps({
            'environment':self.client.get('/environment').json(),
            'windows':self.client.get('/recovery/health',params={'release_id':current['desired']['id']}).json(),
            'incident':self.incident()},default=str))
        stale=self.observation(seq=200)
        self.assertEqual(self.signed({'event_id':'late-old-origin','expected_version':self.version(),'release':stale.model_dump(mode='json')}).status_code,200)
        self.assertEqual(self.client.get('/environment').json()['desired']['environment_commit'],'d'*40)

    def test_no_false_success_without_http_and_fresh_metrics(self):
        target=self.prepare_verification()
        self.assertEqual(self.move('recovered').status_code,409)
        self.windows(errors=0)
        self.assertEqual(self.signed({'event_id':'fresh-target','expected_version':self.version(),
            'release':target.model_copy(update={'observed_at':datetime.now(timezone.utc)}).model_dump(mode='json')}).status_code,200)
        self.assertEqual(self.move('recovered',evidence={'requests':120}).status_code,422)

    def test_newer_release_supersedes_pending_recovery(self):
        self.seed(); self.windows()
        newer=self.observation(build=21,seq=400)
        response=self.signed({'event_id':'newer','expected_version':self.version(),'release':newer.model_dump(mode='json')})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.incident()['phase'],'superseded')
        self.assertEqual(self.move('applying').status_code,409)

    def test_role_and_database_boundaries(self):
        self.seed()
        for role in ('read','developer'):
            self.client.headers['X-API-Key']=self.tokens[role]
            self.assertEqual(self.client.post('/recovery/health',json={}).status_code,403)
        self.denied('DELETE FROM recovery_events')
        self.denied("UPDATE recoveries SET policy='forged'")
        self.denied("UPDATE health_windows SET quality='measured'")

    def test_service_key_cannot_sign_in_or_import(self):
        key='recovery-test-key-01234567890123456789'
        self.settings.api_keys[hashlib.sha256(key.encode()).hexdigest()]='recovery'
        self.client.headers['X-API-Key']=key
        self.assertEqual(self.client.get('/recoveries').status_code,200)
        self.assertEqual(self.client.post('/imports',json={}).status_code,403)
        self.assertEqual(self.client.post('/auth/session',json={'key':key},headers={'Origin':'http://127.0.0.1'}).status_code,403)

    def test_timed_out_verification_cannot_report_success(self):
        self.prepare_verification(); self.windows(errors=0)
        with self.clean_engine.begin() as conn:
            conn.execute(text("UPDATE recoveries SET created_at=now()-interval '601 seconds'"))
        self.assertEqual(self.move('recovered').status_code,409)
        self.assertEqual(self.move('failed',outcome='verification_timeout').status_code,200)
        self.assertEqual(self.incident()['phase'],'failed')

    def test_git_failure_is_terminal_and_audited(self):
        self.seed(); self.windows()
        self.assertEqual(self.move('applying').status_code,200)
        self.assertEqual(self.move('failed',outcome='git_unavailable').status_code,200)
        self.assertEqual(self.incident()['outcome'],'git_unavailable')
        self.assertEqual([e['phase'] for e in self.incident()['events']],['proposed','applying','failed'])
        self.assertEqual(self.move('applying').status_code,409)

    def test_failed_verification_still_records_actual_serving_target(self):
        target=self.prepare_verification()
        self.assertEqual(self.move('failed',outcome='verification_timeout').status_code,200)
        response=self.signed({'event_id':'late-serving-truth','expected_version':self.version(),
            'release':target.model_copy(update={'observed_at':datetime.now(timezone.utc),'observation_sequence':400}).model_dump(mode='json')})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/environment').json()['desired']['status'],'promoted')
        self.assertEqual(self.incident()['phase'],'failed')
        self.assertEqual(self.move('recovered').status_code,409)
