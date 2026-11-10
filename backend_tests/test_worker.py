import json
import unittest
from pathlib import Path

import httpx

from backend.collector import SourcesUnavailable
from backend.worker import AuthenticationFailure, WorkerSettings, cycle


class Observation:
    def __init__(self, sequence=1):
        self.sequence = sequence

    def model_dump(self, **kwargs):
        return {'observation_sequence': self.sequence}


class WorkerTests(unittest.TestCase):
    def settings(self):
        return WorkerSettings('http://127.0.0.1:8090', 'r' * 32, 's' * 32, '/tmp/kube', '/tmp/git')

    def test_uncertain_post_retries_identical_event_body(self):
        bodies, reads = [], []
        def respond(request):
            if request.method == 'GET':
                reads.append(1)
                return httpx.Response(200, json={'version': 2})
            bodies.append(request.content)
            if len(bodies) == 1:
                raise httpx.ReadTimeout('uncertain response', request=request)
            return httpx.Response(200, json={'version': 3})
        with httpx.Client(base_url=self.settings().api_url, transport=httpx.MockTransport(respond)) as client:
            result = cycle(client, self.settings(), observe=lambda *args: Observation(), sleep=lambda n: None)
        self.assertEqual(result['outcome'], 'observed')
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(len(reads), 1)

    def test_version_conflict_reads_and_collects_again(self):
        bodies, observations = [], []
        def respond(request):
            if request.method == 'GET':
                return httpx.Response(200, json={'version': len(bodies)})
            bodies.append(json.loads(request.content))
            return httpx.Response(409, json={'detail': 'Environment version changed'}) if len(bodies) == 1 else httpx.Response(200, json={'version': 2})
        def observe(*args):
            observations.append(1)
            return Observation(len(observations))
        with httpx.Client(base_url=self.settings().api_url, transport=httpx.MockTransport(respond)) as client:
            cycle(client, self.settings(), observe=observe, sleep=lambda n: None)
        self.assertEqual(len(observations), 2)
        self.assertNotEqual(bodies[0]['release'], bodies[1]['release'])

    def test_missing_sources_are_reported_without_a_healthy_release(self):
        bodies = []
        def respond(request):
            if request.method == 'GET':
                return httpx.Response(200, json={'version': 0})
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={'version': 1})
        def missing(*args):
            raise SourcesUnavailable('sources_unavailable')
        with httpx.Client(base_url=self.settings().api_url, transport=httpx.MockTransport(respond)) as client:
            result = cycle(client, self.settings(), observe=missing)
        self.assertEqual(result['outcome'], 'unavailable')
        self.assertNotIn('release', bodies[0])

    def test_authentication_failure_is_not_retried(self):
        calls = []
        def respond(request):
            calls.append(1)
            return httpx.Response(401)
        with httpx.Client(base_url=self.settings().api_url, transport=httpx.MockTransport(respond)) as client:
            with self.assertRaises(AuthenticationFailure):
                cycle(client, self.settings(), sleep=lambda n: None)
        self.assertEqual(len(calls), 1)

    def test_api_failure_has_three_attempts_and_bounded_backoff(self):
        calls, sleeps = [], []
        def respond(request):
            calls.append(1)
            return httpx.Response(503)
        with httpx.Client(base_url=self.settings().api_url, transport=httpx.MockTransport(respond)) as client:
            result = cycle(client, self.settings(), sleep=sleeps.append)
        self.assertEqual(result['outcome'], 'api_unavailable')
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [1, 2])

    def test_identity_conflict_reports_unavailability(self):
        bodies = []
        def respond(request):
            if request.method == 'GET':
                return httpx.Response(200, json={'version': 1})
            bodies.append(json.loads(request.content))
            if len(bodies) == 1:
                return httpx.Response(409, json={'detail': 'Controller identity changed'})
            return httpx.Response(200, json={'version': 2})
        with httpx.Client(base_url=self.settings().api_url, transport=httpx.MockTransport(respond)) as client:
            result = cycle(client, self.settings(), observe=lambda *args: Observation(), sleep=lambda n: None)
        self.assertEqual(result['outcome'], 'unavailable')
        self.assertEqual(bodies[-1]['unavailable'], 'identity_mismatch')

    def test_remote_api_origin_is_rejected(self):
        with self.assertRaises(ValueError):
            WorkerSettings('http://example.com', 'r' * 32, 's' * 32, '/tmp/kube', '/tmp/git')
