"""Run against the assembled candidate's real validators and persistent-state CLI."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).parents[1]


@unittest.skipUnless((ROOT / 'iqpilot/selfdrive/carrot/ha/iq_restore.py').exists(), 'assembled candidate required')
class RestoreTests(unittest.TestCase):
    def setUp(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from iqpilot.selfdrive.carrot.ha.iq_restore import restore
        self.restore = restore
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / 'ha'
        self.payload = {'receiver': {'transport':'direct', 'url':'https://ha.example/carrot-receiver', 'device':'existing', 'token':'x'*32},
                        'camera': {'ha_url':'https://ha.example','device_id':'existing','camera_token':'y'*32}}
        self.params = type('Params', (), {'get':lambda s,k:{'IsOffroad':b'1','IsOnroad':b'0'}.get(k),
            'get_bool':lambda s,k:False, 'iq_camera_busy':lambda s:False})()

    def tearDown(self):
        self.temp.cleanup()

    def test_restore_idempotent_and_private_without_camera_start(self):
        for _ in range(2):
            self.assertEqual(self.restore(self.payload,self.base,self.params),'HA_CONNECTION_RESTORED_CAMERA_DISABLED')
        self.assertEqual((self.base/'camera/camera.json').stat().st_mode & 0o777,0o600)
        self.assertFalse((self.base/'camera/enabled').exists())
        self.assertEqual(sorted(str(p.relative_to(self.base)) for p in self.base.rglob('*') if p.is_file()),
                         ['camera/camera.json','direct-connection.json'])

    def test_unknown_or_onroad_state_never_writes(self):
        for off,on in [(None,None),(b'1',b'1'),(b'0',b'0')]:
            self.params.get=lambda k:{'IsOffroad':off,'IsOnroad':on}.get(k)
            with self.assertRaises(RuntimeError): self.restore(self.payload,self.base,self.params)
            self.assertFalse(self.base.exists())

    def test_identity_and_url_validation_precede_all_writes(self):
        for path,value in [('device_id','other'),('ha_url','http://ha.example'),('camera_token','short')]:
            payload=copy.deepcopy(self.payload);payload['camera'][path]=value
            with self.assertRaises(ValueError):self.restore(payload,self.base,self.params)
            self.assertFalse(self.base.exists())
        payload=copy.deepcopy(self.payload);payload['params']={}
        with self.assertRaises(ValueError):self.restore(payload,self.base,self.params)
        self.assertFalse(self.base.exists())

    def test_existing_different_configuration_is_preserved(self):
        self.restore(self.payload,self.base,self.params)
        original=(self.base/'camera/camera.json').read_bytes()
        changed=copy.deepcopy(self.payload);changed['camera']['camera_token']='z'*32
        with self.assertRaises(ValueError):self.restore(changed,self.base,self.params)
        self.assertEqual((self.base/'camera/camera.json').read_bytes(),original)
