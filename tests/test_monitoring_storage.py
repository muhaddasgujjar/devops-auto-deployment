import copy
import unittest
from scripts.install_monitoring import validate_storage


class MonitoringStorageTests(unittest.TestCase):
    def fixtures(self):
        claim={'metadata':{'uid':'retained-id'},'spec':{'storageClassName':'release-retain',
            'resources':{'requests':{'storage':'2Gi'}},'accessModes':['ReadWriteOnce'],'volumeName':'existing-pv'}}
        storage_class={'provisioner':'rancher.io/local-path','reclaimPolicy':'Retain','volumeBindingMode':'WaitForFirstConsumer'}
        volume={'spec':{'persistentVolumeReclaimPolicy':'Retain','claimRef':{
            'namespace':'monitoring','name':'prometheus-data','uid':'retained-id'}}}
        return claim,storage_class,volume

    def test_existing_retained_claim_is_adopted_without_mutation(self):
        values=self.fixtures(); before=copy.deepcopy(values)
        validate_storage(*values); self.assertEqual(values,before)

    def test_fresh_install_has_no_existing_binding_to_replace(self):
        validate_storage(None,None,None)

    def test_different_size_or_class_is_not_overwritten(self):
        for field,value in (('storageClassName','another-class'),('storage','4Gi')):
            claim,storage_class,volume=self.fixtures()
            if field=='storage': claim['spec']['resources']['requests']['storage']=value
            else: claim['spec'][field]=value
            with self.assertRaises(RuntimeError): validate_storage(claim,storage_class,volume)

    def test_delete_policy_or_foreign_claim_cannot_be_adopted(self):
        claim,storage_class,volume=self.fixtures()
        volume['spec']['persistentVolumeReclaimPolicy']='Delete'
        with self.assertRaises(RuntimeError): validate_storage(claim,storage_class,volume)
        volume['spec']['persistentVolumeReclaimPolicy']='Retain'; volume['spec']['claimRef']['uid']='foreign'
        with self.assertRaises(RuntimeError): validate_storage(claim,storage_class,volume)
