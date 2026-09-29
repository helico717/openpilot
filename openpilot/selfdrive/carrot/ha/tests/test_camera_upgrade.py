"""Commit-independent compatibility and legacy-to-manager migration regression tests."""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from openpilot.selfdrive.carrot.ha.camera import compatibility, service, agent


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for relative in compatibility.BINARIES:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#!/bin/sh\nexit 0\n')
            path.chmod(0o755)
        self.packet = SimpleNamespace(header=b'', data=b'', idx=SimpleNamespace(timestampSof=0))
        self.messaging = SimpleNamespace(new_message=lambda name: SimpleNamespace(**{name: self.packet}))
        self.modules = {
            'openpilot.cereal': SimpleNamespace(messaging=self.messaging),
            'openpilot.cereal.services': SimpleNamespace(SERVICE_LIST=dict.fromkeys(compatibility.STREAMS)),
            'av': SimpleNamespace(container=SimpleNamespace(OutputContainer=SimpleNamespace(add_stream_from_template=Mock()))),
        }

    def check(self):
        with patch.dict(sys.modules, self.modules), patch.object(compatibility.subprocess, 'check_output', return_value='GNU coreutils') as command:
            compatibility.require_runtime(self.root)
            self.assertEqual(command.call_args.args[0], ['/usr/bin/timeout', '--version'])
            self.assertEqual(command.call_count, 1)

    def test_new_git_commits_do_not_break_unchanged_camera_contract(self):
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL, text=True).strip()
        git('init')
        heads = []
        for index in range(2):
            (self.root / 'unrelated.txt').write_text(str(index))
            git('add', '.')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'Unrelated update')
            heads.append(git('rev-parse', 'HEAD'))
            self.check()
        self.assertNotEqual(*heads)

    def test_missing_or_nonexecutable_binary_is_rejected(self):
        path = self.root / compatibility.BINARIES[0]
        path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, 'executable unavailable'):
            self.check()
        path.unlink()
        with self.assertRaisesRegex(RuntimeError, 'executable unavailable'):
            self.check()

    def test_missing_service_is_rejected(self):
        self.modules['openpilot.cereal.services'].SERVICE_LIST.pop(compatibility.STREAMS[1])
        with self.assertRaisesRegex(RuntimeError, 'service unavailable'):
            self.check()

    def test_changed_schema_is_rejected(self):
        del self.packet.idx
        with self.assertRaisesRegex(RuntimeError, 'schema'):
            self.check()

    def test_missing_remux_api_is_rejected(self):
        self.modules['av'].container.OutputContainer = object
        with self.assertRaisesRegex(RuntimeError, 'PyAV'):
            self.check()


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / 'native'
        self.legacy = Path(self.temp.name) / 'legacy'
        self.legacy.mkdir()
        self.config = {'ha_url': 'https://example.org', 'device_id': 'test-id4', 'camera_token': 'a' * 64}
        (self.legacy / 'camera.json').write_text(json.dumps(self.config))
        (self.legacy / 'camera.json').chmod(0o600)
        (self.legacy / 'enabled').touch()
        (self.legacy / 'agent.py').write_text('legacy source must remain untouched')
        self.values = {'IsOffroad': True, 'IsOnroad': False}
        self.params = SimpleNamespace(get=self.values.get, get_bool=lambda key: self.values.get(key) is True)

    def test_preserves_settings_and_does_not_modify_legacy_code(self):
        service.migrate_settings(self.base, self.legacy)
        self.assertEqual(json.loads((self.base / 'camera.json').read_text()), self.config)
        self.assertEqual((self.base / 'camera.json').stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.base / 'enabled').exists())
        self.assertFalse((self.legacy / 'enabled').exists())
        self.assertEqual((self.legacy / 'agent.py').read_text(), 'legacy source must remain untouched')
        service.migrate_settings(self.base, self.legacy)
        self.assertTrue(service.configured(self.base, self.legacy))

    def test_native_disabled_configuration_is_never_reenabled(self):
        service.migrate_settings(self.base, self.legacy)
        (self.base / 'enabled').unlink()
        (self.legacy / 'enabled').touch()
        service.migrate_settings(self.base, self.legacy)
        self.assertFalse(service.configured(self.base, self.legacy))

    def test_disabled_legacy_installation_stays_disabled(self):
        (self.legacy / 'enabled').unlink()
        service.migrate_settings(self.base, self.legacy)
        self.assertFalse(self.base.exists())
        self.assertFalse(service.configured(self.base, self.legacy))

    def test_invalid_config_does_not_disable_existing_service(self):
        (self.legacy / 'camera.json').write_text('{}')
        with self.assertRaises(ValueError):
            service.migrate_settings(self.base, self.legacy)
        self.assertTrue((self.legacy / 'enabled').exists())
        self.assertFalse((self.base / 'camera.json').exists())

    def test_interrupted_migration_can_resume(self):
        with patch.object(service.os, 'replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                service.migrate_settings(self.base, self.legacy)
        self.assertTrue((self.legacy / 'enabled').exists())
        service.migrate_settings(self.base, self.legacy)
        self.assertTrue(service.configured(self.base, self.legacy))
        self.assertFalse((self.legacy / 'enabled').exists())

    async def test_waits_for_legacy_supervisor_lock_before_connecting(self):
        with (self.legacy / 'supervisor.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(service, 'run_agent', new_callable=AsyncMock) as run:
                task = asyncio.create_task(service.serve(self.base, self.legacy, self.params))
                try:
                    await asyncio.sleep(0.05)
                    self.assertFalse((self.legacy / 'enabled').exists())
                    run.assert_not_awaited()
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    await asyncio.wait_for(task, 3)
                    run.assert_awaited_once_with(self.base)
                finally:
                    task.cancel()

    async def test_onroad_never_migrates_or_starts_agent(self):
        self.values['IsOnroad'] = True
        with patch.object(service, 'run_agent', new_callable=AsyncMock) as run:
            task = asyncio.create_task(service.serve(self.base, self.legacy, self.params))
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            run.assert_not_awaited()
            self.assertTrue((self.legacy / 'enabled').exists())
            self.assertFalse(self.base.exists())

    async def test_capture_always_launches_git_managed_module(self):
        import uuid
        device = agent.DeviceAgent(base=self.legacy, status=lambda: True)
        proc = Mock(stdout=Mock(readexactly=AsyncMock(side_effect=asyncio.IncompleteReadError(b'', 4))))
        ws = Mock(send_json=AsyncMock())
        with patch.object(asyncio, 'create_subprocess_exec', new_callable=AsyncMock, return_value=proc) as spawn:
            await device.command(ws, {'type': 'start', 'session_id': str(uuid.uuid4()), 'cameras': ['wide']})
            await device.pump_task
            self.assertEqual(spawn.call_args.args[1:3], ('-m', 'openpilot.selfdrive.carrot.ha.camera.capture'))


class ManagerWiringTests(unittest.TestCase):
    def test_manager_uses_configuration_as_should_run_predicate(self):
        import ast
        # Manager's `enabled` is a bool, not a callback. Exercise the registered
        # should_run slot so an unconfigured device never starts the service.
        path = Path(__file__).resolve().parents[4] / 'system/manager/process_config.py'
        tree = ast.parse(path.read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'enable_carrot_camera')
        function.returns = None
        for arg in function.args.args:
            arg.annotation = None
        scope = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), scope)
        call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == 'PythonProcess'
                    and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 'carrot_camera')
        scope['PythonProcess'] = lambda name, module, should_run, **kwargs: should_run
        should_run = eval(compile(ast.Expression(call), str(path), 'eval'), scope)
        for configured in (False, True):
            with patch.object(service, 'configured', return_value=configured):
                self.assertEqual(should_run(False, None, None), configured)


class ConfigureTests(unittest.TestCase):
    def test_enable_and_disable_only_touch_runtime_state(self):
        from openpilot.selfdrive.carrot.ha.camera import configure
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / 'native'
            legacy = Path(directory) / 'legacy'
            base.mkdir()
            legacy.mkdir()
            config = {'ha_url': 'https://example.org', 'device_id': 'test', 'camera_token': 'a' * 64}
            config_path = base / 'camera.json'
            config_path.write_text(json.dumps(config))
            config_path.chmod(0o600)
            params = SimpleNamespace(get=lambda key: {'IsOffroad': True, 'IsOnroad': False}.get(key), get_bool=lambda _: False)
            with patch.object(configure, 'BASE', base), patch.object(configure, 'LEGACY', legacy), \
                    patch.dict(sys.modules, {'openpilot.common.params': SimpleNamespace(Params=lambda: params)}), \
                    patch('builtins.print'):
                with patch.object(sys, 'argv', ['configure', '--enable']):
                    configure.main()
                self.assertTrue(service.configured(base, legacy))
                (legacy / 'enabled').touch()
                with patch.object(sys, 'argv', ['configure', '--disable']):
                    configure.main()
                self.assertFalse(service.configured(base, legacy))
                self.assertEqual(json.loads(config_path.read_text()), config)


class ProtocolTests(unittest.TestCase):
    def test_v1_wire_format_stays_compatible_with_ha(self):
        from openpilot.selfdrive.carrot.ha.camera import protocol
        session = '00112233-4455-6677-8899-aabbccddeeff'
        payload = b'\x47' + bytes(187)
        for name, camera_id in (('wide', 1), ('driver', 2), ('road', 3)):
            expected = bytes.fromhex('4348563100112233445566778899aabbccddeeff') + bytes([camera_id]) + payload
            self.assertEqual(protocol.encode_media(session, name, payload), expected)
            self.assertEqual(protocol.decode_media(expected), (session, name, payload))
