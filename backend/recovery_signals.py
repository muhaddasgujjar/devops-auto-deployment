"""Read-only, deployment-specific Prometheus and finite HTTP probes via Kubernetes."""
import json
import base64
import math
import re
import ssl
import time
from urllib.parse import urlencode

import httpx
import yaml

from backend.collector import SourcesUnavailable, execute


class Signals:
    def __init__(self, kubeconfig, client=None):
        if client:
            self.client = client
            return
        from pathlib import Path
        from urllib.parse import urlparse
        config = yaml.safe_load(Path(kubeconfig).read_text())
        context = next(c['context'] for c in config['contexts'] if c['name'] == 'k3d-release-lab')
        cluster = next(c['cluster'] for c in config['clusters'] if c['name'] == context['cluster'])
        user = next(u['user'] for u in config['users'] if u['name'] == context['user'])
        parsed = urlparse(cluster['server'])
        if parsed.scheme != 'https' or parsed.hostname not in ('127.0.0.1', 'localhost', '0.0.0.0') or parsed.username:
            raise ValueError('Signals require the verified local Kubernetes API')
        tls = ssl.create_default_context(cadata=base64.b64decode(cluster['certificate-authority-data']).decode())
        self.client = httpx.Client(base_url=cluster['server'].replace('://0.0.0.0:', '://127.0.0.1:'),
            verify=tls, headers={'Authorization': 'Bearer ' + user['token']}, timeout=5,
            follow_redirects=False, trust_env=False)

    def raw(self, path):
        try:
            response = self.client.get(path)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise SourcesUnavailable('read_only_signal_unavailable') from None

    def scalar(self, query, end):
        path = '/api/v1/namespaces/monitoring/services/prometheus:9090/proxy/api/v1/query?'
        document = self.raw(path + urlencode({'query': query, 'time': int(end.timestamp())}))
        values = document.get('data', {}).get('result', [])
        if (document.get('status') != 'success' or document.get('warnings') or document.get('infos') or
            document.get('data', {}).get('resultType') != 'vector' or len(values) != 1):
            raise SourcesUnavailable('telemetry_inconclusive')
        value = float(values[0]['value'][1])
        if not math.isfinite(value):
            raise SourcesUnavailable('telemetry_nonfinite')
        return value

    def measure(self, observation, end):
        names = observation.observation_details.get('stable_pod_names', [])
        if len(names) != 2 or any(not re.fullmatch('[a-z0-9-]{1,253}', p) for p in names):
            raise SourcesUnavailable('serving_pods_unavailable')
        labels = 'namespace="demo-dev",revision="' + observation.stable_hash + '",pod=~"' + '|'.join(names) + '"'
        requests = 'sum(increase(demo_requests_total{' + labels + '}[30s]))'
        errors = 'sum(increase(demo_requests_total{' + labels + ',status="500"}[30s]))'
        p95 = 'histogram_quantile(0.95,sum by(le)(rate(demo_request_duration_seconds_bucket{' + labels + '}[30s])))'
        up = 'up{job="demo-pods",' + labels + '}'
        queries = {'requests': requests, 'errors': errors, 'p95_seconds': p95,
                   'up_min': 'min(' + up + ')', 'up_count': 'count(' + up + ')',
                   'scrape_age_seconds': 'max(time()-timestamp(' + up + '))'}
        return {**{name: self.scalar(query, end) for name, query in queries.items()},
                'pod_names': names, 'query_window_seconds': 30}

    def probe(self, service):
        if service not in ('demo-stable', 'demo-preview'):
            raise ValueError('Only the two managed services may be probed')
        start = time.monotonic()
        try:
            response = self.client.get('/api/v1/namespaces/demo-dev/services/' + service + ':80/proxy/')
            body = response.json()
            return {'ok': response.status_code == 200, 'status': response.status_code,
                    'revision': body.get('revision'), 'mode': body.get('mode'), 'seconds': time.monotonic() - start}
        except (httpx.HTTPError, ValueError):
            return {'ok': False, 'status': 0, 'revision': None, 'seconds': time.monotonic() - start}
