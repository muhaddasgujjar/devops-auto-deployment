"""Bounded, read-only collection with durable callback retries and safe status output."""
import json
import os
import signal
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from backend.cli import post_callback
from backend.collector import SourcesUnavailable, collect


@dataclass(frozen=True)
class WorkerSettings:
    api_url: str
    read_key: str
    callback_secret: str
    kubeconfig: str
    environment_git: str
    status_file: str = '/var/lib/release-observer/status.json'
    interval_seconds: int = 30
    attempts: int = 3

    def __post_init__(self):
        origin = urlparse(self.api_url)
        if origin.scheme != 'http' or origin.hostname != '127.0.0.1' or origin.username or origin.path:
            raise ValueError('Collector credentials may only be sent to the loopback API')
        if not 5 <= self.interval_seconds <= 300 or not 1 <= self.attempts <= 3:
            raise ValueError('Collector interval or retry bound is invalid')
        if len(self.read_key) < 32 or len(self.callback_secret) < 32:
            raise ValueError('Collector credentials are missing')


class AuthenticationFailure(RuntimeError):
    pass


def cycle(client, settings, *, observe=collect, sleep=time.sleep):
    payload = None
    event_id = 'collector:' + uuid.uuid4().hex
    for attempt in range(settings.attempts):
        try:
            if payload is None:
                response = client.get('/environment')
                if response.status_code in (401, 403):
                    raise AuthenticationFailure('API authentication failed')
                response.raise_for_status()
                payload = {'event_id': event_id, 'expected_version': response.json()['version']}
                try:
                    payload['release'] = observe(Path(settings.kubeconfig), Path(settings.environment_git)).model_dump(mode='json')
                except (SourcesUnavailable, KeyError, ValueError, StopIteration):
                    payload['unavailable'] = 'sources_unavailable'
            response = post_callback(client, settings, payload)
            if response.status_code in (401, 403):
                raise AuthenticationFailure('Collector signature rejected')
            if response.status_code == 409:
                detail = response.json().get('detail', '')
                if 'version changed' in detail:
                    payload = None  # Read and collect again; do not relabel an old snapshot as new.
                else:
                    current = client.get('/environment')
                    current.raise_for_status()
                    payload = {'event_id': event_id, 'expected_version': current.json()['version'],
                               'unavailable': 'identity_mismatch'}
            else:
                response.raise_for_status()
                return {'outcome': 'unavailable' if payload.get('unavailable') else 'observed',
                        'backend_version': response.json()['version'], 'attempts': attempt + 1}
        except httpx.HTTPStatusError as error:
            if error.response.status_code < 500:
                raise AuthenticationFailure('Collector request contract rejected') from None
        except httpx.TransportError:
            # Keep the exact event body after an uncertain POST result. The database
            # can then return its prior result without duplicate effects.
            pass
        if attempt + 1 < settings.attempts:
            sleep(min(2**attempt, 4))
    return {'outcome': 'api_unavailable', 'attempts': settings.attempts}


def run(settings, stop, *, max_cycles=None):
    status_path = Path(settings.status_file)
    previous = {}
    if status_path.exists():
        try:
            previous = json.loads(status_path.read_text())
        except (ValueError, OSError):
            pass
    completed = 0
    with httpx.Client(base_url=settings.api_url, headers={'X-API-Key': settings.read_key}, timeout=10,
                      follow_redirects=False, trust_env=False) as client:
        while not stop.is_set():
            result = cycle(client, settings, sleep=lambda delay: stop.wait(delay))
            completed += 1
            previous = {'pid': os.getpid(), 'uid': os.getuid(), 'cycles': previous.get('cycles', 0) + 1,
                        'checked_at_utc': datetime.now(timezone.utc).isoformat(), **result}
            status_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = status_path.with_suffix('.pending')
            temporary.write_text(json.dumps(previous) + '\n')
            os.replace(temporary, status_path)
            print(json.dumps(previous), flush=True)
            if max_cycles is not None and completed >= max_cycles:
                break
            stop.wait(settings.interval_seconds)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-cycles', type=int)
    args = parser.parse_args()
    path = os.environ['RELEASE_WORKER_CONFIG_FILE']
    data = json.loads(Path(path).read_text())
    if 'RELEASE_OBSERVER_KUBECONFIG' in os.environ:
        data['kubeconfig'] = os.environ['RELEASE_OBSERVER_KUBECONFIG']
    settings = WorkerSettings(**data)
    stop = threading.Event()
    for kind in (signal.SIGINT, signal.SIGTERM):
        signal.signal(kind, lambda signum, frame: stop.set())
    run(settings, stop, max_cycles=args.max_cycles)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'fatal': type(error).__name__}), flush=True)
        raise SystemExit(1)
