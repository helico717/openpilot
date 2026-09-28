from __future__ import annotations

import unittest
from unittest.mock import AsyncMock
import uuid
import time
from unittest.mock import patch

from openpilot.selfdrive.carrot.ha.terminal import LOCAL_WS_URL, TerminalAgent, validate_config
from openpilot.selfdrive.carrot.ha.terminal import discover, watch_discovery


class Response:
  status = 200

  def __init__(self, payload):
    self.payload = payload

  async def __aenter__(self):
    return self

  async def __aexit__(self, *args):
    pass

  def raise_for_status(self):
    pass

  async def json(self):
    return self.payload


class DiscoveryTest(unittest.IsolatedAsyncioTestCase):
  async def test_existing_config_is_sufficient_and_not_modified(self):
    original = {'url': 'https://worker.example', 'token': 'existing-upload', 'device': 'comma'}
    before = dict(original)
    resolved = {'ha_url': 'https://ha.example', 'terminal_token': 't' * 64, 'expires_at': time.time() * 1000 + 120000}
    from unittest.mock import Mock
    client = Mock()
    client.get.return_value = Response({'protocol': 1, 'config': resolved})
    result = await discover(client, original)
    self.assertEqual(result['device'], 'comma')
    self.assertEqual(original, before)
    self.assertEqual(client.get.call_args.kwargs['headers'], {'Authorization': 'Bearer existing-upload'})
    self.assertFalse(client.get.call_args.kwargs['allow_redirects'])
    resolved['expires_at'] = 1
    self.assertIsNone(await discover(client, original))
    client.get.return_value.status = 404
    self.assertIsNone(await discover(client, original))

  async def test_revocation_closes_connection(self):
    remote = AsyncMock()
    module = 'openpilot.selfdrive.carrot.ha.terminal'
    with patch(module + '.asyncio.sleep', new=AsyncMock()), patch(module + '.discover', new=AsyncMock(return_value=None)):
      await watch_discovery(None, {}, remote, {})
    remote.close.assert_awaited_once()


class TerminalConfigTest(unittest.TestCase):
  def test_validate_config_builds_device_websocket_url(self):
    config = {"ha_url": "https://ha.example:8123", "terminal_token": "t" * 64, "device": "comma four"}
    self.assertEqual(validate_config(config), "wss://ha.example:8123/api/carrot_ha/v1/terminal/comma%20four")

  def test_reuses_carrot_web_support_pty_endpoint(self):
    self.assertEqual(LOCAL_WS_URL, "ws://127.0.0.1:7000/ws/terminal_pty?cols=100&rows=30")


class TerminalAgentTest(unittest.IsolatedAsyncioTestCase):
  async def test_onroad_rejects_session_before_local_connection(self):
    remote = AsyncMock()
    agent = TerminalAgent(status=lambda: False)
    agent.local_ready = AsyncMock(return_value=True)
    session_id = str(uuid.uuid4())

    await agent.start_local(remote, session_id)

    agent.local_ready.assert_not_awaited()
    remote.send_json.assert_awaited_once_with({"type": "ended", "session_id": session_id, "reason": "not_ready"})

  async def test_input_is_forwarded_only_for_active_offroad_session(self):
    remote = AsyncMock()
    local_ws = AsyncMock()
    agent = TerminalAgent(status=lambda: True)
    agent.local_ws = local_ws
    agent.session_id = str(uuid.uuid4())
    message = {"type": "raw", "data": "uptime\r"}

    await agent.command(remote, {"type": "input", "session_id": agent.session_id, "message": message})

    local_ws.send_json.assert_awaited_once_with(message)


if __name__ == "__main__":
  unittest.main()
