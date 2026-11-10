"""One bounded recovery owner: observe, commit to Git, verify; never patches Kubernetes."""
import fcntl
import hashlib
import json
import os
import shlex
import signal
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from backend.collector import collect, SourcesUnavailable
from backend.recovery_git import publish_recovery, ConcurrentGitChange, GitUnavailable
from backend.recovery_policy import POLICY, as_time, measured, sustained
from backend.recovery_signals import Signals


class ClockDiscontinuity(RuntimeError):
    pass


class RecoveryWorker:
    def __init__(self, config, *, client=None, observe=collect, signals=None, writer=publish_recovery):
        parsed = urlparse(config['api_url'])
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.username or
            parsed.path or parsed.query or parsed.fragment or len(config['api_key']) < 32):
            raise ValueError('Recovery credentials require the loopback API')
        if config['repository'] != 'ssh://release-git@127.0.0.1:2222/var/lib/release-lab/git/environment.git':
            raise ValueError('Recovery writer is restricted to the local environment repository')
        self.config, self.observe, self.writer = config, observe, writer
        self.boot_wall, self.boot_monotonic = time.time(), time.monotonic()
        self.client = client or httpx.Client(base_url=config['api_url'], headers={'X-API-Key': config['api_key']},
                                            timeout=10, follow_redirects=False, trust_env=False)
        self.signals = signals or Signals(config['kubeconfig'])

    def get(self, path):
        response = self.client.get(path)
        response.raise_for_status()
        return response.json()

    def post(self, path, payload):
        # On an uncertain response, retry the identical event once. A later cycle
        # reads the durable phase/sample instead of issuing a new actuation.
        for attempt in range(2):
            try:
                response = self.client.post(path, json=payload)
                if response.status_code == 409:
                    return None
                response.raise_for_status()
                return response.json()
            except httpx.TransportError:
                if attempt:
                    raise

    def event(self, recovery, phase, **fields):
        state = self.get('/environment')
        return self.post('/recoveries/' + recovery['id'] + '/events', {
            'event_id': recovery['id'] + ':' + phase + ':' + str(recovery['version']),
            'expected_version': state['version'], 'expected_recovery_version': recovery['version'],
            'phase': phase, **fields})

    def sample(self, state):
        desired = state.get('desired')
        now = datetime.now(timezone.utc)
        if not desired or desired['status'] != 'promoted' or state['freshness'] != 'current':
            return 'not_armed'
        end = datetime.fromtimestamp(int(now.timestamp()) // 30 * 30, timezone.utc)
        promoted = as_time(desired['promoted_at']) if desired.get('promoted_at') else now
        if end - timedelta(seconds=30) < promoted:
            return 'waiting_for_complete_window'
        if (now - promoted).total_seconds() > POLICY['monitor_seconds']:
            return 'observation_window_closed'
        prior = self.get('/recovery/health?release_id=' + desired['id'])
        if any(as_time(row['window_end']) == end for row in prior):
            return 'window_already_recorded'
        quality, data = 'measured', {}
        try:
            observation = self.observe(Path(self.config['kubeconfig']), Path(self.config['environment_git']))
            if (observation.environment_commit != desired['environment_commit'] or observation.status != 'promoted' or
                observation.stable_hash != state['stable_hash']):
                raise SourcesUnavailable('sources_changing')
            data = self.signals.measure(observation, end)
            after = self.observe(Path(self.config['kubeconfig']), Path(self.config['environment_git']))
            if after.observation_sequence != observation.observation_sequence or after.source_uid != observation.source_uid:
                raise SourcesUnavailable('sources_changing')
            if not measured(data):
                raise SourcesUnavailable('insufficient_telemetry')
        except (SourcesUnavailable, ValueError, KeyError, StopIteration):
            quality, data = 'unavailable', {'reason': 'telemetry_or_sources_unavailable'}
        event = hashlib.sha256((desired['id'] + end.isoformat()).encode()).hexdigest()
        result = self.post('/recovery/health', {'event_id': 'health:' + event, 'expected_version': state['version'],
            'release_id': desired['id'], 'pod_hash': state['stable_hash'], 'window_end': end.isoformat(),
            'quality': quality, 'data': data})
        return quality if result else 'state_changed'

    def guard(self, recovery):
        self.check_clock()
        state = self.get('/environment')
        if not state.get('desired') or state['desired']['id'] != recovery['origin_release_id']:
            raise ConcurrentGitChange('Desired deployment changed before recovery publication')
        latest = next((r for r in self.get('/recoveries') if r['id'] == recovery['id']), None)
        if not latest or latest['phase'] != 'applying':
            raise ConcurrentGitChange('Recovery no longer owns publication')
        if not 0 <= time.time() - as_time(latest['created_at']).timestamp() < POLICY['recovery_timeout_seconds']:
            raise TimeoutError('Recovery publication deadline expired')

    def apply(self, recovery):
        if recovery['phase'] == 'proposed':
            self.event(recovery, 'applying')
            return 'reserved'
        try:
            receipt = self.writer(self.config['repository'], recovery, guard=lambda: self.guard(recovery))
            self.event(recovery, 'verifying', recovery_commit=receipt['environment_commit'], evidence=receipt)
            return 'git_published'
        except ConcurrentGitChange:
            self.event(recovery, 'superseded', outcome='concurrent_git_change')
            return 'superseded'
        except GitUnavailable:
            self.event(recovery, 'failed', outcome='git_unavailable')
            return 'git_unavailable'
        except TimeoutError:
            self.event(recovery, 'failed', outcome='verification_timeout')
            return 'verification_timeout'

    def verify(self, recovery, stop):
        # A bounded finite load probe supplies the existing pre-promotion gate on
        # a cold accepted target and independent serving HTTP proof afterwards.
        state = self.get('/environment')
        deadline = as_time(recovery['created_at']).timestamp() + POLICY['recovery_timeout_seconds']
        target = recovery['target']
        revision = f"{target['build']['source_commit']}-jenkins-{target['build']['number']}"
        proof = {'requests': 0, 'non_200': 0, 'target_requests': 0, 'identity_mismatches': 0, 'maximum_gap_seconds': 0, 'revision': revision,
                 'image': target['artifact']['image'], 'pod_hash': None}
        last = None
        # Each invocation is short; a restart simply gathers new independent proof.
        finish = min(deadline, time.time() + 15)
        while not stop.is_set() and time.time() < finish:
            if proof['requests'] % 20 == 0:
                current = self.get('/environment')
                if current.get('desired') and current['desired']['id'] != recovery['origin_release_id'] and current['desired'].get('recovery_id') != recovery['id']:
                    return 'newer_release'
            self.signals.probe('demo-preview')
            sample = self.signals.probe('demo-stable')
            stamp = time.monotonic()
            proof['requests'] += 1
            if last is not None:
                proof['maximum_gap_seconds'] = max(proof['maximum_gap_seconds'], stamp - last)
            last = stamp
            if sample['ok'] and sample['revision'] == revision:
                proof['target_requests'] += 1
            if not sample['ok']:
                proof['non_200'] += 1
            if sample['revision'] != revision:
                proof['identity_mismatches'] += 1
            stop.wait(.05)
        if time.time() >= deadline:
            self.event(recovery, 'failed', outcome='verification_timeout', evidence=proof)
            return 'verification_timeout'
        state = self.get('/environment')
        desired = state.get('desired')
        if desired and desired.get('recovery_id') == recovery['id']:
            proof['pod_hash'] = state['stable_hash']
            windows = self.get('/recovery/health?release_id=' + desired['id'])
            if proof['target_requests'] >= POLICY['minimum_requests'] and proof['non_200'] == 0 and proof['identity_mismatches'] == 0 and sustained(windows, 'healthy'):
                try:
                    observed = self.observe(Path(self.config['kubeconfig']), Path(self.config['environment_git']))
                except (SourcesUnavailable, ValueError, KeyError, StopIteration):
                    return 'source_unavailable'
                if (observed.environment_commit != recovery['recovery_commit'] or observed.status != 'promoted' or
                    observed.stable_revision != revision or observed.stable_image != target['artifact']['image'] or
                    observed.stable_hash != state['stable_hash']):
                    return 'sources_changing'
                proof.update(environment_commit=observed.environment_commit, controller_uid=observed.source_uid,
                             controller_observation=observed.model_dump(mode='json'))
                self.event(recovery, 'recovered', outcome='healthy_target_verified', evidence=proof)
                return 'recovered'
        return 'verifying'

    def cycle(self, stop):
        self.check_clock()
        state = self.get('/environment')
        outcome = self.sample(state)
        for recovery in self.get('/recoveries'):
            if recovery['phase'] in ('proposed', 'applying', 'verifying'):
                if time.time() < as_time(recovery['created_at']).timestamp():
                    self.event(recovery, 'failed', outcome='source_unavailable', evidence={'reason': 'host_clock_uncertain'})
                    return 'host_clock_uncertain'
                if time.time() - as_time(recovery['created_at']).timestamp() >= POLICY['recovery_timeout_seconds']:
                    self.event(recovery, 'failed', outcome='verification_timeout')
                    return 'verification_timeout'
                return self.verify(recovery, stop) if recovery['phase'] == 'verifying' else self.apply(recovery)
        return outcome

    def check_clock(self):
        if abs((time.time() - self.boot_wall) - (time.monotonic() - self.boot_monotonic)) > 5:
            raise ClockDiscontinuity('Host wall clock changed; stop actuation and re-establish time')


def main():
    config = json.loads(Path(os.environ['RELEASE_RECOVERY_CONFIG_FILE']).read_text())
    for variable, key in (('RELEASE_RECOVERY_KUBECONFIG', 'kubeconfig'),):
        if variable in os.environ:
            config[key] = os.environ[variable]
    os.environ['GIT_SSH_COMMAND'] = shlex.join(['ssh', '-i', os.environ['RELEASE_RECOVERY_GIT_KEY'],
        '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'UserKnownHostsFile=' + os.environ['RELEASE_RECOVERY_KNOWN_HOSTS']])
    state_dir = Path('/var/lib/release-recovery')
    with (state_dir / 'writer.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another recovery owner is active') from None
        worker = RecoveryWorker(config)
        stop = threading.Event()
        for kind in (signal.SIGTERM, signal.SIGINT):
            signal.signal(kind, lambda signum, frame: stop.set())
        while not stop.is_set():
            try:
                result = worker.cycle(stop)
            except httpx.HTTPStatusError as error:
                if error.response.status_code < 500:
                    raise RuntimeError('Recovery service authorization or contract rejected') from None
                result = 'api_unavailable'
            except (httpx.TransportError, SourcesUnavailable):
                result = 'api_or_sources_unavailable'
            record = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid(),
                      'uid': os.getuid(), 'outcome': result}
            pending = state_dir / 'status.pending'
            pending.write_text(json.dumps(record) + '\n')
            os.replace(pending, state_dir / 'status.json')
            print(json.dumps(record), flush=True)
            stop.wait(2)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'fatal': type(error).__name__}), flush=True)
        raise SystemExit(1)
