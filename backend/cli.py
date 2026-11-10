import argparse
import hashlib
import hmac
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

from backend.collector import SourcesUnavailable, collect
from backend.config import load_settings


def post_callback(client, settings, payload):
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    stamp = str(int(time.time()))
    signature = 'v1=' + hmac.new(settings.callback_secret.encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return client.post('/callbacks', content=raw, headers={'X-Release-Timestamp': stamp,
                       'X-Release-Signature': signature, 'Content-Type': 'application/json'})


def main():
    parser = argparse.ArgumentParser(description='Authenticated local release state commands')
    parser.add_argument('--url', default='http://127.0.0.1:8090')
    parser.add_argument('--tokens', type=Path, default=Path('/opt/release-lab/secrets/backend/tokens.json'))
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('state')
    imp = sub.add_parser('import')
    imp.add_argument('report', type=Path)
    imp.add_argument('--kind', choices=['ci_acceptance', 'runtime_acceptance', 'ci_negative_gate'], required=True)
    rec = sub.add_parser('reconcile')
    rec.add_argument('--kubeconfig', type=Path, required=True)
    rec.add_argument('--environment-git', type=Path, default=Path('/var/lib/release-lab/git/environment.git'))
    args = parser.parse_args()
    origin = urlparse(args.url)
    if origin.scheme != 'http' or origin.hostname != '127.0.0.1' or origin.username or origin.path:
        parser.error('This lab client sends credentials only to a loopback HTTP origin')
    settings = load_settings()
    tokens = json.loads(args.tokens.read_text())
    with httpx.Client(base_url=args.url, headers={'X-API-Key': tokens['admin']}, timeout=30) as client:
        state = client.get('/environment')
        state.raise_for_status()
        if args.action == 'state':
            print(json.dumps(state.json(), indent=2))
            return
        payload = {'expected_version': state.json()['version']}
        if args.action == 'import':
            raw = args.report.read_bytes()
            payload.update(event_id='report:' + hashlib.sha256(raw).hexdigest(), kind=args.kind, report=json.loads(raw))
            response = client.post('/imports', json=payload)
        else:
            payload['event_id'] = 'reconcile:' + uuid.uuid4().hex
            try:
                payload['release'] = collect(args.kubeconfig, args.environment_git).model_dump(mode='json')
            except (SourcesUnavailable, KeyError, ValueError, StopIteration):
                payload['unavailable'] = 'sources_unavailable'
            response = post_callback(client, settings, payload)
        response.raise_for_status()
        print(json.dumps(response.json(), indent=2))


if __name__ == '__main__':
    main()
