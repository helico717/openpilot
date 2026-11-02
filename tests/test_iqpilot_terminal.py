"""POSIX adapter checks with a synthetic base relay; no real HA or vehicle."""
import asyncio
import base64
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
import uuid

package = types.ModuleType('iq_adapter_test')
package.__path__ = []
sys.modules[package.__name__] = package
base = types.ModuleType('iq_adapter_test.terminal')
class BaseAgent:
    def __init__(self, status=lambda: False):
        self.status, self.session_id, self.local_task = status, None, None
    async def send(self, remote, data):
        await remote.send_json(data)
base.TerminalAgent, base.PROTOCOL = BaseAgent, 1
sys.modules[base.__name__] = base
spec = importlib.util.spec_from_file_location('iq_adapter_test.iq_terminal',
    Path(__file__).parents[1] / 'iqpilot/selfdrive/carrot/ha/iq_terminal.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class Remote:
    def __init__(self):
        self.events = []
    async def send_json(self, value):
        self.events.append(value)


class TerminalTests(unittest.IsolatedAsyncioTestCase):
    async def test_not_offroad_never_starts_shell(self):
        agent = adapter.IQTerminalAgent(lambda: False)
        remote = Remote()
        await agent.start_local(remote, str(uuid.uuid4()))
        self.assertIsNone(agent.process)
        self.assertEqual(remote.events[-1]['reason'], 'not_ready')

    async def test_real_pty_output_and_offroad_input_block(self):
        parked = [True]
        remote = Remote()
        with tempfile.TemporaryDirectory() as directory:
            agent = adapter.IQTerminalAgent(lambda: parked[0], shell=('/bin/bash', '--noprofile', '--norc', '-i'), cwd=directory)
            session = str(uuid.uuid4())
            try:
                await agent.start_local(remote, session)
                process = agent.process
                await agent.command(remote, {'type': 'input', 'session_id': session,
                    'message': {'type': 'raw', 'data': "printf 'IQ_HA_PTY_OK\\n'\n"}})
                for _ in range(100):
                    output = b''.join(base64.b64decode(item['message']['b64']) for item in remote.events if item['type'] == 'terminal')
                    if b'\r\nIQ_HA_PTY_OK\r\n' in output:
                        break
                    await asyncio.sleep(0.02)
                self.assertIn(b'\r\nIQ_HA_PTY_OK\r\n', output)
                with self.assertRaises(ValueError):
                    await agent.command(remote, {'type': 'input', 'session_id': session,
                        'message': {'type': 'raw', 'data': 'x' * 4097}})
                parked[0] = False
                await agent.command(remote, {'type': 'input', 'session_id': session,
                    'message': {'type': 'raw', 'data': 'touch forbidden\n'}})
                self.assertFalse((Path(directory) / 'forbidden').exists())
                self.assertIsNone(agent.session_id)
                self.assertGreaterEqual(process.returncode, -9)
                self.assertEqual(agent.master, -1)
            finally:
                await agent.stop_local()


if __name__ == '__main__':
    unittest.main()
