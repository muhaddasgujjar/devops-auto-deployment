import json
import unittest
from datetime import datetime, timedelta, timezone

import httpx

from backend.collector import SourcesUnavailable
from backend.recovery_signals import Signals
from backend.recovery_worker import RecoveryWorker


class RecoverySignalTests(unittest.TestCase):
    def signal(self, body, status=200):
        client=httpx.Client(base_url='https://127.0.0.1:6445',transport=httpx.MockTransport(
            lambda request:httpx.Response(status,json=body)))
        self.addCleanup(client.close)
        return Signals(None,client=client)

    def test_empty_nonfinite_and_denied_queries_never_become_zero(self):
        for body,status in [({'status':'success','data':{'resultType':'vector','result':[]}},200),
            ({'status':'success','data':{'resultType':'vector','result':[{'value':[1,'NaN']}]}},200),
            ({'message':'denied'},403),({'status':'error'},200)]:
            with self.assertRaises(SourcesUnavailable): self.signal(body,status).scalar('test',datetime.now(timezone.utc))

    def test_proxy_http_failures_are_not_counted_as_success(self):
        result=self.signal({'revision':'old'},500).probe('demo-stable')
        self.assertFalse(result['ok'])
        with self.assertRaises(ValueError): self.signal({}).probe('unmanaged-service')

    def test_queries_bind_current_serving_pods_and_completed_time(self):
        requests=[]
        def respond(request):
            requests.append(request)
            return httpx.Response(200,json={'status':'success','data':{'resultType':'vector','result':[{'value':[1,'1']}]}})
        client=httpx.Client(base_url='https://127.0.0.1:6445',transport=httpx.MockTransport(respond)); self.addCleanup(client.close)
        class Observation:
            stable_hash='abcde12345'
            observation_details={'stable_pod_names':['release-demo-a-1','release-demo-a-2']}
        end=datetime.fromtimestamp(1800,timezone.utc)
        Signals(None,client=client).measure(Observation(),end)
        self.assertEqual(len(requests),6)
        for request in requests:
            self.assertEqual(request.url.params['time'],'1800')
            self.assertIn('revision="abcde12345"',request.url.params['query'])
            self.assertIn('pod=~"release-demo-a-1|release-demo-a-2"',request.url.params['query'])


class RecoveryWorkerTests(unittest.TestCase):
    def config(self):
        return {'api_url':'http://127.0.0.1:8090','api_key':'unit-recovery-key-'+'a'*32,
                'repository':'ssh://release-git@127.0.0.1:2222/var/lib/release-lab/git/environment.git',
                'kubeconfig':'/unit/kubeconfig','environment_git':'/unit/environment.git'}

    def test_credentials_cannot_be_sent_to_remote_api_or_repository(self):
        for field,value in [('api_url','http://outside.example:8090'),('repository','ssh://outside.example/repository')]:
            with self.assertRaises(ValueError): RecoveryWorker({**self.config(),field:value},signals=object())

    def test_uncertain_post_retries_exact_event_and_body(self):
        captured=[]
        def respond(request):
            captured.append(request.content)
            if len(captured)==1: raise httpx.ReadTimeout('response lost',request=request)
            return httpx.Response(200,json={'duplicate':True})
        client=httpx.Client(base_url='http://127.0.0.1:8090',transport=httpx.MockTransport(respond)); self.addCleanup(client.close)
        worker=RecoveryWorker(self.config(),client=client,signals=object())
        self.assertTrue(worker.post('/unit',{'event_id':'same-event','expected_version':3})['duplicate'])
        self.assertEqual(captured[0],captured[1]); self.assertEqual(len(captured),2)

    def test_source_failure_records_unavailable_window_instead_of_incident(self):
        captured=[]
        def respond(request):
            if request.method=='GET': return httpx.Response(200,json=[])
            captured.append(json.loads(request.content)); return httpx.Response(200,json={'version':2})
        def unavailable(*args): raise SourcesUnavailable('no telemetry')
        client=httpx.Client(base_url='http://127.0.0.1:8090',transport=httpx.MockTransport(respond)); self.addCleanup(client.close)
        worker=RecoveryWorker(self.config(),client=client,signals=object(),observe=unavailable)
        state={'version':1,'freshness':'current','stable_hash':'abcde12345','desired':{
            'id':'deployment','status':'promoted','promoted_at':(datetime.now(timezone.utc)-timedelta(seconds=180)).isoformat()}}
        self.assertEqual(worker.sample(state),'unavailable')
        self.assertEqual(captured[0]['quality'],'unavailable')
        self.assertNotIn('requests',captured[0]['data'])
