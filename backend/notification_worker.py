"""Least-privilege local signal check and bounded outbox delivery process."""
import json
import os
import signal
import threading
import time
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from backend.collector import SourcesUnavailable
from backend.monitoring import POLICY,canonical
from backend.recovery_signals import Signals


def local_url(value):
    parsed=urlparse(value)
    if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Notification endpoints must be plain local origins')
    if parsed.path not in ('','/'): raise ValueError('Configure an origin without a path')
    return value.rstrip('/')


class NotificationWorker:
    def __init__(self,config,signals=None):
        self.api=httpx.Client(base_url=local_url(config['api_url']),headers={'X-API-Key':config['api_key']},
                              timeout=10,trust_env=False,follow_redirects=False)
        self.receiver=httpx.Client(base_url=local_url(config['receiver_url']),
            headers={'Authorization':'Bearer '+config['receiver_token']},timeout=5,trust_env=False,follow_redirects=False)
        self.signals=signals or Signals(config['kubeconfig'])
        self.boot_wall,self.boot_mono=time.time(),time.monotonic()

    def post(self,path,payload=None):
        response=self.api.post(path,json=payload); response.raise_for_status(); return response.json()

    def tick(self):
        available=True; alerts=[]
        try:
            document=self.signals.raw('/api/v1/namespaces/monitoring/services/prometheus:9090/proxy/api/v1/alerts')
            if document.get('status')!='success' or document.get('warnings') or document.get('infos') or not isinstance(document.get('data',{}).get('alerts'),list):
                raise SourcesUnavailable('invalid_telemetry')
            for row in document['data']['alerts']:
                labels=row.get('labels',{}); name=labels.get('alertname')
                if name in POLICY['native_rules']:
                    alerts.append({'name':name,'revision':labels.get('revision',''),'state':row['state']})
            if len(alerts)>20: raise SourcesUnavailable('telemetry_cardinality_limit')
        except (SourcesUnavailable,KeyError,TypeError): available=False; alerts=[]
        self.post('/monitoring/tick',{'observed_at':datetime.now(timezone.utc).isoformat(),
                                      'telemetry_available':available,'alerts':alerts})

    def deliver(self):
        item=self.post('/notifications/claim')
        if not item: return 'idle'
        payload={'lease_id':item['lease_id'],'delivered':False,'result':'receiver_unavailable'}
        try:
            response=self.receiver.post('/notifications',content=canonical(item['payload']),headers={
                'Content-Type':'application/json','Idempotency-Key':item['id']})
            if response.status_code==200:
                receipt=response.json()
                if receipt.get('id')==item['id'] and receipt.get('sha256')==item['payload_sha256']:
                    payload.update(delivered=True,result='receiver_acknowledged',receipt_id=receipt['id'],receipt_sha256=receipt['sha256'])
                else: payload['result']='invalid_receipt'
        except ValueError: payload['result']='invalid_receipt'
        except httpx.HTTPError: pass
        # If this response is uncertain, the lease expires and the same immutable
        # notification is retried. Receiver deduplication prevents duplicate inbox entries.
        return self.post('/notifications/'+item['id']+'/result',payload)['state']

    def cycle(self):
        if abs((time.time()-self.boot_wall)-(time.monotonic()-self.boot_mono))>5:
            raise RuntimeError('Host clock changed; re-establish time before delivery')
        self.tick()
        return self.deliver()

    def close(self): self.api.close(); self.receiver.close(); self.signals.client.close()


def main():
    config=json.loads(Path(os.environ['RELEASE_NOTIFICATION_CONFIG_FILE']).read_text())
    config['kubeconfig']=os.environ['RELEASE_NOTIFICATION_KUBECONFIG']
    worker=NotificationWorker(config); stop=threading.Event()
    for kind in (signal.SIGTERM,signal.SIGINT): signal.signal(kind,lambda *_:stop.set())
    try:
        while not stop.is_set():
            try: outcome=worker.cycle()
            except httpx.HTTPStatusError as error:
                if error.response.status_code<500: raise RuntimeError('Notifier authorization or contract rejected') from None
                outcome='api_unavailable'
            except httpx.HTTPError: outcome='api_unavailable'
            record={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'outcome':outcome,'pid':os.getpid()}
            target=Path('/var/lib/release-notifier/status.json'); pending=target.with_suffix('.pending')
            pending.write_text(json.dumps(record)+'\n'); os.replace(pending,target)
            print(json.dumps(record),flush=True); stop.wait(2)
    finally: worker.close()


if __name__=='__main__':
    try: main()
    except Exception as error:
        print(json.dumps({'fatal':type(error).__name__}),flush=True); raise SystemExit(1)
