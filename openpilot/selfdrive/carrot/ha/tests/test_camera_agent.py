import asyncio
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

from openpilot.selfdrive.carrot.ha.camera import agent


class ConfigTests(unittest.TestCase):
    def test_no_credentials_in_url_and_separate_device_path(self):
        config = {'ha_url': 'https://example.org:8123', 'device_id': 'test vehicle', 'camera_token': 'a' * 64}
        self.assertEqual(agent.validate_config(config), 'wss://example.org:8123/api/carrot_ha/v1/camera/test%20vehicle')
        for url in ('http://example.org', 'https://user:password@example.org', 'https://example.org/path', 'https://example.org?token=x'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                agent.validate_config(dict(config, ha_url=url))


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_onroad_start_never_spawns(self):
        device = agent.DeviceAgent(status=lambda: False)
        ws = Mock(send_json=AsyncMock())
        session_id = str(uuid.uuid4())
        with patch.object(asyncio, 'create_subprocess_exec', new_callable=AsyncMock) as spawn:
            await device.command(ws, {'type': 'start', 'session_id': session_id, 'cameras': ['wide', 'driver']})
            spawn.assert_not_called()
        self.assertEqual(ws.send_json.await_args.args[0]['type'], 'ended')

    async def test_unknown_command_cannot_execute(self):
        device = agent.DeviceAgent(status=lambda: True)
        with patch.object(asyncio, 'create_subprocess_exec', new_callable=AsyncMock) as spawn:
            with self.assertRaises(ValueError):
                await device.command(Mock(), {'type': 'shell', 'session_id': str(uuid.uuid4()), 'command': 'anything'})
            spawn.assert_not_called()

    async def test_stale_stop_and_renew_do_not_touch_active_capture(self):
        device = agent.DeviceAgent(status=lambda: True)
        device.session_id = str(uuid.uuid4())
        device.process = Mock()
        for kind in ('stop', 'renew'):
            await device.command(Mock(), {'type': kind, 'session_id': str(uuid.uuid4())})
        device.process.stdin.close.assert_not_called()
        device.process.stdin.write.assert_not_called()

    async def test_stop_closes_lease_pipe_and_waits_for_owned_process(self):
        device = agent.DeviceAgent(status=lambda: True)
        process = Mock(wait=AsyncMock())
        device.process = process
        await device.stop_capture()
        process.stdin.close.assert_called_once()
        process.wait.assert_awaited_once()
        self.assertIsNone(device.process)

    def test_offroad_clears_stale_snapshot_flag(self):
        fake_params = {'IsOffroad': True, 'IsOnroad': False, 'IsDriverViewEnabled': False, 'IsTakingSnapshot': True}
        mock_params = Mock(
            get=lambda key: fake_params.get(key),
            get_bool=lambda key: fake_params.get(key) is True,
            remove=lambda key: fake_params.pop(key, None),
        )
        with patch.dict('sys.modules', {
            'openpilot.common.params': Mock(Params=lambda: mock_params),
            'openpilot.selfdrive.carrot.ha.camera.probe': Mock(param_bool=lambda v: v if isinstance(v, bool) else None,
                                      active_camera_processes=lambda: []),
        }):
            device = agent.DeviceAgent()
            self.assertTrue(device.offroad())
            self.assertNotIn('IsTakingSnapshot', fake_params)


if __name__ == '__main__':
    unittest.main()
