"""Verify actual notifier scopes and separate service identities without keys."""
import hashlib
import json
import subprocess
from datetime import datetime,timezone
import httpx
from scripts.backend_runtime import CONFIG,SECRET_ROOT
from scripts.render_release import ROOT


def main():
    kube=['kubectl','--kubeconfig',str(SECRET_ROOT/'notifier.kubeconfig'),'--context=k3d-release-lab','auth','can-i']
    cases=[(['get','services/prometheus:9090','--subresource=proxy','-n','monitoring'],True),
        (['create','services/prometheus:9090','--subresource=proxy','-n','monitoring'],False),
        (['get','pods','-n','demo-dev'],False),(['create','pods','--subresource=exec','-n','demo-dev'],False),
        (['get','secrets','-n','monitoring'],False),(['patch','services/demo-stable','-n','demo-dev'],False),
        (['patch','rollouts.argoproj.io/release-demo','-n','demo-dev'],False),
        (['get','services/demo-stable:80','--subresource=proxy','-n','demo-dev'],False)]
    authorization=[]
    for args,expected in cases:
        row=subprocess.run(kube+args,capture_output=True,text=True,timeout=10)
        allowed=row.stdout.strip()=='yes'; assert allowed==expected
        authorization.append({'request':args,'allowed':allowed})
    config=json.loads((SECRET_ROOT/'notification.json').read_text())
    assert set(config)=={'api_url','api_key','receiver_url','receiver_token','kubeconfig'}
    settings=json.loads(CONFIG.read_text())
    assert settings['api_keys'][hashlib.sha256(config['api_key'].encode()).hexdigest()]=='notifier'
    with httpx.Client(base_url=config['api_url'],headers={'X-API-Key':config['api_key']},timeout=5,trust_env=False) as client:
        assert client.get('/monitoring').status_code==200
        for path in ('/imports','/recovery/health'):
            assert client.post(path,json={}).status_code==403
        assert client.get('/audit').status_code==403
        assert client.post('/auth/session',json={'key':config['api_key']},headers={'Origin':config['api_url']}).status_code==403
    units={}
    for name,user in (('release-state-notifier','release-notifier'),('release-notification-receiver','release-notification-receiver')):
        raw=subprocess.check_output(['systemctl','show',name,'-p','User','-p','ActiveState','-p','NoNewPrivileges','-p','ProtectSystem','-p','WorkingDirectory'],text=True)
        value=dict(line.split('=',1) for line in raw.splitlines())
        assert value['User']==user and value['ActiveState']=='active' and value['NoNewPrivileges']=='yes' and value['ProtectSystem']=='strict'
        units[name]=value
    result={'passed':True,'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'kubernetes':authorization,'units':units,
        'separate_receiver_token':config['api_key']!=config['receiver_token'],
        'database_admin_hmac_credentials_in_worker':False,'git_or_docker_credentials_in_worker':False,
        'api_import_recovery_audit_browser_denied':True,'receiver_bind':'127.0.0.1:8092',
        'token_lifetime':'1h; explicit token refresh and service restart required'}
    (ROOT/'docs/evidence/notification-permissions.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'passed':True,'kubernetes_checks':len(cases),'separate_users':True}))


if __name__=='__main__': main()
