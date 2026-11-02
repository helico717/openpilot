"""Test ownership isolation without native IQ Params or camera hardware."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('iq_camera_adapter', Path(__file__).parents[1] / 'iqpilot/selfdrive/carrot/ha/iq_camera.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class Native:
    def __init__(self, busy=False):
        self.busy = busy
    def get(self, key):
        return {'IsOffroad': b'1', 'IsOnroad': b'0'}[key]
    def get_bool(self, key):
        if key == 'IsTakingSnapshot':
            raise AssertionError('Must never query compiled snapshot key')
        return self.busy


class CameraTests(unittest.TestCase):
    def test_marker_does_not_require_or_change_compiled_params(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'owner.json'
            params = adapter.CameraParams(Native(), marker)
            self.assertFalse(params.get_bool('IsTakingSnapshot'))
            params.put_bool('IsTakingSnapshot', True)
            self.assertTrue(params.get_bool('IsTakingSnapshot'))
            self.assertEqual(marker.stat().st_mode & 0o077, 0)
            self.assertEqual(params.get('IsOffroad'), b'1')
            params.remove('IsTakingSnapshot')
            self.assertFalse(marker.exists())

    def test_other_live_owner_cannot_be_cleared_or_claimed(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'owner.json'
            marker.write_text(json.dumps({'pid': os.getpid() + 100}))
            params = adapter.CameraParams(Native(), marker)
            with patch.object(adapter.os, 'kill', return_value=None):
                params.remove('IsTakingSnapshot')
                self.assertTrue(marker.exists())
                with self.assertRaises(RuntimeError):
                    params.put_bool('IsTakingSnapshot', True)

    def test_iq_sentry_or_unknown_status_blocks_ha_camera(self):
        params = adapter.CameraParams(Native(busy=True))
        self.assertTrue(params.iq_camera_busy())
        with patch.object(params.native, 'get_bool', side_effect=ValueError('unknown')):
            self.assertTrue(params.iq_camera_busy())
        self.assertFalse(adapter.CameraParams(Native()).iq_camera_busy())

    def test_no_control_params_can_be_written(self):
        params = adapter.CameraParams(Native())
        for key in ['IsOnroad', 'ExperimentalMode', 'IQSentryRecording']:
            with self.assertRaises(ValueError):
                params.put_bool(key, True)
            with self.assertRaises(ValueError):
                params.remove(key)


if __name__ == '__main__':
    unittest.main()
