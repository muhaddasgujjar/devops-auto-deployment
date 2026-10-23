"""Fixed read-only lab adapters. Never expose Jenkins credentials or raw logs."""
import json
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from scripts.gitops_trial import Jenkins
from scripts.live_trial import kube
from scripts.render_release import ROOT

EVIDENCE = Path('/var/lib/release-lab/evidence')


def evidence():
    if not (EVIDENCE / 'catalog.sqlite3').exists():
        raise RuntimeError('Evidence catalogue unavailable')
    with sqlite3.connect((EVIDENCE / 'catalog.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute('SELECT id,verdict,summary_json,archived_at FROM runs ORDER BY archived_at DESC LIMIT 200').fetchall()
        counts = db.execute('SELECT COUNT(*),COUNT(DISTINCT sha256) FROM files').fetchone()
        total = db.execute('SELECT COUNT(*) FROM runs').fetchone()[0]
    return {'runs': [{'id': r[0], 'verdict': r[1], 'summary': json.loads(r[2]), 'archived_at': r[3]} for r in rows],
            'count': total, 'file_count': counts[0], 'object_count': counts[1]}


def builds():
    tree = 'builds[number,result,building,timestamp,duration,url,actions[parameters[name,value]]]{0,30},inQueue,nextBuildNumber'
    job = Jenkins().json('job/release-main/api/json?' + urlencode({'tree': tree}))
    return {'in_queue': job.get('inQueue', False), 'next_build': job.get('nextBuildNumber'), 'items': [
        {'id': 'release-main-' + str(b['number']), 'number': b['number'],
         'state': 'RUNNING' if b.get('building') else b.get('result', 'UNKNOWN'),
         'started_at': datetime.fromtimestamp(b['timestamp'] / 1000, timezone.utc).isoformat(),
         'duration_ms': b.get('duration', 0), 'url': 'http://localhost:8082/job/release-main/' + str(b['number']) + '/',
         'mode': next((p['value'] for a in b.get('actions', []) for p in a.get('parameters', [])
                       if p.get('name') == 'DEMO_MODE'), 'healthy')}
        for b in job.get('builds', [])]}


def monitoring():
    root = '/api/v1/namespaces/monitoring/services/prometheus:9090/proxy/api/v1/query?'
    query = 'up{job="demo-pods",namespace="demo-dev"}'
    result = json.loads(kube('get', '--raw', root + urlencode({'query': query})))
    age = json.loads(kube('get', '--raw', root + urlencode({'query': 'time() - timestamp(' + query + ')'})))
    samples = result.get('data', {}).get('result', [])
    ages = {r['metric'].get('pod'): float(r['value'][1]) for r in age.get('data', {}).get('result', [])}
    return {'targets': [{'pod': r['metric'].get('pod'), 'revision': r['metric'].get('revision'),
                         'up': float(r['value'][1]) == 1,
                         'age_seconds': round(ages.get(r['metric'].get('pod'), 9999), 1)} for r in samples]}


def collect():
    os.environ['KUBECONFIG'] = str(ROOT / 'output/lab.kubeconfig')
    if kube('config', 'current-context').strip() != 'k3d-release-lab':
        raise RuntimeError('Portal observer only supports the dedicated lab context')
    operations = {
        'rollout': lambda: json.loads(kube('get', 'rollout', 'release-demo', '-n', 'demo-dev', '-o', 'json')),
        'application': lambda: json.loads(kube('get', 'application', 'release-demo-dev', '-n', 'argocd', '-o', 'json')),
        'services': lambda: json.loads(kube('get', 'service', 'demo-stable', '-n', 'demo-dev', '-o', 'json')),
        'analyses': lambda: json.loads(kube('get', 'analysisrun', '-n', 'demo-dev', '-o', 'json')),
        'monitoring': monitoring, 'builds': builds, 'evidence': evidence,
        'recovery': lambda: json.loads(Path('/var/lib/release-lab/recovery/status.json').read_text()),
    }
    snapshot = {'collected_at': datetime.now(timezone.utc).isoformat(), 'components': {}, 'errors': {}}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {name: pool.submit(fn) for name, fn in operations.items()}
        for name, future in futures.items():
            try:
                snapshot['components'][name] = future.result()
            except Exception:
                # Raw exceptions can contain internal paths or credential-bearing URLs.
                snapshot['errors'][name] = 'Source unavailable; inspect the local service.'
    return snapshot
