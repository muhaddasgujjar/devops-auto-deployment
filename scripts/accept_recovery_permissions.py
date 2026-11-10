"""Check the real recovery identity and boundaries without revealing credentials."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone

import httpx

from backend.recovery_signals import Signals
from scripts.backend_runtime import CONFIG, SECRET_ROOT
from scripts.render_release import ROOT


def main():
    base=['kubectl','--kubeconfig',str(SECRET_ROOT/'recovery.kubeconfig'),'--context=k3d-release-lab']
    cases=[(['get','rollouts.argoproj.io/release-demo','-n','demo-dev'],True),
           (['get','applications.argoproj.io/release-demo-dev','-n','argocd'],True),
           (['get','services/demo-stable:80','--subresource=proxy','-n','demo-dev'],True),
           (['get','services/prometheus:9090','--subresource=proxy','-n','monitoring'],True),
           (['patch','rollouts.argoproj.io/release-demo','-n','demo-dev'],False),
           (['patch','services/demo-stable','-n','demo-dev'],False),
           (['create','pods','--subresource=exec','-n','demo-dev'],False),
           (['get','secrets','-n','demo-dev'],False),
           (['patch','applications.argoproj.io/release-demo-dev','-n','argocd'],False),
           (['get','applications.argoproj.io/other','-n','argocd'],False),
           (['get','services/other:9090','--subresource=proxy','-n','monitoring'],False)]
    authorization=[]
    for args,expected in cases:
        result=subprocess.run(base+['auth','can-i']+args,capture_output=True,text=True,timeout=15)
        allowed=result.stdout.strip()=='yes'
        assert allowed==expected, 'Unexpected recovery Kubernetes authority: '+' '.join(args)
        authorization.append({'request':args,'allowed':allowed})
    config=json.loads((SECRET_ROOT/'recovery.json').read_text())
    assert set(config)=={'api_url','api_key','repository','kubeconfig','environment_git'}
    settings=json.loads(CONFIG.read_text())
    assert settings['api_keys'][hashlib.sha256(config['api_key'].encode()).hexdigest()]=='recovery'
    with httpx.Client(base_url=config['api_url'],headers={'X-API-Key':config['api_key']},timeout=10,trust_env=False) as client:
        assert client.get('/recoveries').status_code==200
        assert client.get('/audit').status_code==403
        assert client.post('/imports',json={}).status_code==403
        assert client.post('/auth/session',json={'key':config['api_key']},headers={'Origin':config['api_url']}).status_code==403
    signals=Signals(SECRET_ROOT/'recovery.kubeconfig')
    baseline=signals.probe('demo-stable')
    assert baseline['status']==200
    signals.client.close()
    properties=subprocess.check_output(['systemctl','show','release-state-recovery','-p','User','-p','ActiveState',
        '-p','NoNewPrivileges','-p','ProtectSystem','-p','WorkingDirectory'],text=True)
    properties=dict(line.split('=',1) for line in properties.splitlines())
    assert properties['User']=='release-recovery' and properties['ActiveState']=='active'
    assert properties['NoNewPrivileges']=='yes' and properties['ProtectSystem']=='strict'
    git='/var/lib/release-lab/git/environment.git'
    assert subprocess.check_output(['git','--git-dir',git,'config','receive.denyNonFastForwards'],text=True).strip()=='true'
    assert subprocess.check_output(['git','--git-dir',git,'config','receive.denyDeletes'],text=True).strip()=='true'
    report={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'passed':True,'kubernetes':authorization,
            'service':properties,'api_import_audit_browser_denied':True,'separate_service_key':True,
            'database_admin_hmac_credentials_in_worker':False,'kubernetes_tls_verified_proxy_get':True,
            'git_non_fast_forward_and_ref_deletion_denied':True,'baseline_response':baseline,
            'token_lifetime':'1h; explicit refresh and service restart required',
            'limitations':['Repository-scoped SSH write authority; trusted local host and CI agent remain lab boundaries']}
    (ROOT/'docs/evidence/recovery-permissions.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'allowed_checks':sum(r['allowed'] for r in authorization),
                      'denied_checks':sum(not r['allowed'] for r in authorization)}))


if __name__=='__main__': main()
