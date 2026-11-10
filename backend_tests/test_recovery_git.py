import json
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import yaml

from backend.recovery_git import ConcurrentGitChange, GitUnavailable, publish_recovery


class RecoveryGitTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.root=Path(self.temporary.name)
        self.remote=self.root/'environment.git'; self.work=self.root/'work'
        self.git(self.root,'init','--bare','--initial-branch=main',str(self.remote))
        self.git(self.root,'clone',str(self.remote),str(self.work))
        self.git(self.work,'config','user.name','test'); self.git(self.work,'config','user.email','test@localhost')
        target={'apiVersion':'argoproj.io/v1alpha1','kind':'Rollout','metadata':{'name':'release-demo','namespace':'demo-dev'},
                'spec':{'replicas':2,'strategy':{'blueGreen':{'scaleDownDelaySeconds':120}},
                        'template':{'metadata':{'labels':{'app':'release-demo'}},'spec':{'containers':[
                            {'name':'app','image':'localhost:5001/release-demo@sha256:'+'a'*64,
                             'env':[{'name':'APP_REVISION','value':'b'*40+'-jenkins-1'}]}]}}}}
        self.path=self.work/'environments/dev/rollout.yaml'; self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps(target)); (self.work/'README.md').write_text('retained')
        self.target_commit=self.commit('accepted target')
        self.target_template=target['spec']['template']
        current=json.loads(json.dumps(target)); current['spec']['replicas']=3
        current['metadata']['annotations']={'keep':'current-policy'}
        current['spec']['strategy']['blueGreen']['scaleDownDelaySeconds']=180
        container=current['spec']['template']['spec']['containers'][0]
        container['image']='localhost:5001/release-demo@sha256:'+'d'*64
        container['env'][0]['value']='c'*40+'-jenkins-2'
        self.path.write_text(json.dumps(current)); self.base=self.commit('bad promoted release')
        self.recovery={'id':str(uuid.uuid4()),'base_commit':self.base,'policy':'post-promotion-v1',
            'target':{'id':str(uuid.uuid4()),'environment_commit':self.target_commit,
                      'artifact':{'image':'localhost:5001/release-demo@sha256:'+'a'*64},
                      'build':{'source_commit':'b'*40,'number':1}},
            'origin':{'artifact':{'image':'localhost:5001/release-demo@sha256:'+'d'*64},
                      'build':{'source_commit':'c'*40,'number':2}}}

    def tearDown(self): self.temporary.cleanup()

    def git(self, directory, *args):
        return subprocess.check_output(['git','-C',str(directory),*args],stderr=subprocess.DEVNULL,text=True).strip()

    def commit(self, message):
        self.git(self.work,'add','.'); self.git(self.work,'commit','-m',message)
        self.git(self.work,'push','origin','main')
        return self.git(self.work,'rev-parse','HEAD')

    def head(self): return self.git(self.root,'--git-dir',str(self.remote),'rev-parse','main')

    def test_forward_commit_restores_only_template_and_restart_deduplicates(self):
        first=publish_recovery(str(self.remote),self.recovery)
        self.assertTrue(first['changed'])
        self.assertEqual(self.git(self.root,'--git-dir',str(self.remote),'rev-parse','main^'),self.base)
        result=yaml.safe_load(self.git(self.root,'--git-dir',str(self.remote),'show','main:environments/dev/rollout.yaml'))
        self.assertEqual(result['spec']['template'],self.target_template)
        self.assertEqual(result['spec']['replicas'],3)
        self.assertEqual(result['spec']['strategy']['blueGreen']['scaleDownDelaySeconds'],180)
        self.assertEqual(result['metadata']['annotations']['keep'],'current-policy')
        self.assertEqual(result['metadata']['annotations']['release-lab/recovery-id'],self.recovery['id'])
        second=publish_recovery(str(self.remote),self.recovery)
        self.assertFalse(second['changed']); self.assertEqual(first['environment_commit'],second['environment_commit'])
        changed=self.git(self.root,'--git-dir',str(self.remote),'diff','--name-only',self.base,'main').splitlines()
        self.assertEqual(len(changed),2)
        self.assertEqual(self.git(self.root,'--git-dir',str(self.remote),'show','main:README.md'),'retained')

    def test_competing_publisher_wins_without_force_or_rebase(self):
        winner=[]
        def concurrent(directory):
            (self.work/'README.md').write_text('newer publisher')
            winner.append(self.commit('newer wins'))
        with self.assertRaises(ConcurrentGitChange):
            publish_recovery(str(self.remote),self.recovery,before_push=concurrent)
        self.assertEqual(self.head(),winner[0])

    def test_newer_head_before_write_is_superseded(self):
        (self.work/'README.md').write_text('newer'); winner=self.commit('newer')
        with self.assertRaises(ConcurrentGitChange): publish_recovery(str(self.remote),self.recovery)
        self.assertEqual(self.head(),winner)

    def test_mismatched_accepted_digest_never_publishes(self):
        self.recovery['target']['artifact']['image']='localhost:5001/release-demo@sha256:'+'e'*64
        with self.assertRaises(GitUnavailable): publish_recovery(str(self.remote),self.recovery)
        self.assertEqual(self.head(),self.base)

    def test_old_recovery_marker_cannot_undo_later_publisher(self):
        publish_recovery(str(self.remote),self.recovery)
        self.git(self.work,'pull','--ff-only')
        (self.work/'README.md').write_text('later'); winner=self.commit('later')
        with self.assertRaises(ConcurrentGitChange): publish_recovery(str(self.remote),self.recovery)
        self.assertEqual(self.head(),winner)

    def test_guard_rejects_superseded_database_ownership_before_push(self):
        def guard(): raise ConcurrentGitChange('newer desired state')
        with self.assertRaises(ConcurrentGitChange): publish_recovery(str(self.remote),self.recovery,guard=guard)
        self.assertEqual(self.head(),self.base)
