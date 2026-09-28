"""Outbound HA relay for the PTY shared by Carrot Web and support_terminal."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import json
from urllib.parse import quote, urlsplit, urlunsplit
import uuid


PROTOCOL = 1
MAX_REMOTE_BYTES = 131072
LOCAL_STATUS_URL = "http://127.0.0.1:7000/api/terminal_pty/status"
LOCAL_WS_URL = "ws://127.0.0.1:7000/ws/terminal_pty?cols=100&rows=30"


def validate_config(config: dict) -> str:
  if not isinstance(config, dict):
    raise ValueError("invalid configuration")
  address = config.get("ha_url", "")
  if not isinstance(address, str) or any(ord(char) <= 32 for char in address):
    raise ValueError("invalid HA URL")
  url = urlsplit(address)
  if (url.scheme != "https" or not url.hostname or url.path not in ("", "/")
      or url.query or url.fragment or url.username or url.password or url.port == 0):
    raise ValueError("ha_url must be an HTTPS base URL")
  token = config.get("terminal_token", "")
  if (not isinstance(token, str) or not 32 <= len(token) <= 256 or not token.isascii()
      or any(char.isspace() for char in token)):
    raise ValueError("invalid terminal token")
  device_id = config.get("device", "")
  if not isinstance(device_id, str) or not device_id or len(device_id) > 128 or "/" in device_id:
    raise ValueError("invalid device ID")
  return urlunsplit(("wss", url.netloc, "/api/carrot_ha/v1/terminal/" + quote(device_id, safe=""), "", ""))


def _param_bool(value) -> bool | None:
  if isinstance(value, bool):
    return value
  if isinstance(value, bytes):
    value = value.decode(errors="ignore")
  if isinstance(value, str):
    text = value.strip().lower()
    if text in ("1", "true"):
      return True
    if text in ("0", "false"):
      return False
  return None


def is_offroad() -> bool:
  try:
    from openpilot.common.params import Params
    params = Params()
    return _param_bool(params.get("IsOffroad")) is True and _param_bool(params.get("IsOnroad")) is False
  except Exception:
    return False


class TerminalAgent:
  def __init__(self, status=is_offroad):
    self.status = status
    self.local_ws = None
    self.local_client = None
    self.local_task = None
    self.session_id = None
    self.send_lock = asyncio.Lock()
    self.stop_lock = asyncio.Lock()

  async def local_ready(self) -> bool:
    import aiohttp
    if not self.status():
      return False
    try:
      timeout = aiohttp.ClientTimeout(total=2)
      async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.get(LOCAL_STATUS_URL) as response:
          if response.status != 200:
            return False
          data = await response.json()
          # Opening /ws/terminal_pty starts the shared PTY when it is not alive yet.
          return data.get("ok") is True
    except (aiohttp.ClientError, OSError, ValueError, TimeoutError):
      return False

  async def send(self, remote, payload: dict) -> None:
    async with self.send_lock, asyncio.timeout(5):
      await remote.send_json(payload)

  async def start_local(self, remote, session_id: str) -> None:
    if self.session_id is not None:
      await self.send(remote, {"type": "ended", "session_id": session_id, "reason": "busy"})
      return
    if not self.status() or not await self.local_ready():
      await self.send(remote, {"type": "ended", "session_id": session_id, "reason": "not_ready"})
      return
    import aiohttp
    client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
    try:
      # The endpoint is backed by the same PTY_SESSION used by support_terminal.
      local_ws = await client.ws_connect(LOCAL_WS_URL, heartbeat=10, max_msg_size=1048576, compress=0)
    except Exception:
      await client.close()
      await self.send(remote, {"type": "ended", "session_id": session_id, "reason": "local_unavailable"})
      return
    self.local_client = client
    self.local_ws = local_ws
    self.session_id = session_id
    self.local_task = asyncio.create_task(self.pump_local(remote, local_ws, session_id))
    await self.send(remote, {"type": "started", "session_id": session_id})

  async def pump_local(self, remote, local_ws, session_id: str) -> None:
    import aiohttp
    reason = "local_ended"
    try:
      async for message in local_ws:
        if message.type == aiohttp.WSMsgType.TEXT:
          if len(message.data.encode()) > 1048576:
            raise ValueError("local terminal message is too large")
          payload = message.json()
          if not isinstance(payload, dict) or payload.get("type") not in (
              "meta", "pty_output", "pty_resize", "pty_exit", "error"):
            raise ValueError("invalid local terminal message")
          # Never disclose terminal contents that predate this HA session.
          if payload.get("type") == "pty_output" and payload.get("replay") is True:
            continue
          await self.send(remote, {"type": "terminal", "session_id": session_id, "message": payload})
        elif message.type == aiohttp.WSMsgType.ERROR:
          reason = "local_error"
          break
    except (aiohttp.ClientError, ConnectionError, RuntimeError, ValueError, TimeoutError):
      reason = "local_error"
    finally:
      if self.session_id == session_id:
        await self.stop_local()
        with suppress(ConnectionError, RuntimeError, TimeoutError):
          await self.send(remote, {"type": "ended", "session_id": session_id, "reason": reason})

  async def stop_local(self) -> None:
    async with self.stop_lock:
      local_ws, client, task = self.local_ws, self.local_client, self.local_task
      self.local_ws = None
      self.local_client = None
      self.local_task = None
      self.session_id = None
    if local_ws is not None:
      await local_ws.close()
    if client is not None:
      await client.close()
    if task is not None and task is not asyncio.current_task():
      task.cancel()
      with suppress(asyncio.CancelledError):
        await task

  async def command(self, remote, data: dict) -> None:
    if not isinstance(data, dict):
      raise ValueError("invalid terminal command")
    kind = data.get("type")
    if kind == "hello":
      if data.get("protocol") != PROTOCOL:
        raise ValueError("unsupported terminal protocol")
      return
    session_id = data.get("session_id")
    if not isinstance(session_id, str):
      raise ValueError("missing terminal session")
    uuid.UUID(session_id)
    if kind == "start":
      await self.start_local(remote, session_id)
      return
    if kind == "stop":
      if session_id == self.session_id:
        await self.stop_local()
      return
    if kind != "input":
      raise ValueError("unsupported terminal command")
    if session_id != self.session_id or self.local_ws is None:
      return
    if not self.status():
      await self.stop_local()
      await self.send(remote, {"type": "ended", "session_id": session_id, "reason": "device_not_offroad"})
      return
    message = data.get("message")
    if not isinstance(message, dict):
      raise ValueError("invalid terminal input")
    input_type = message.get("type")
    if input_type == "raw":
      value = message.get("data")
      if not isinstance(value, str) or not value or len(value.encode()) > 4096:
        raise ValueError("invalid raw terminal input")
    elif input_type == "control":
      if message.get("action") not in ("ctrl_c", "clear", "refresh"):
        raise ValueError("unsupported terminal control")
    else:
      raise ValueError("unsupported terminal input")
    await self.local_ws.send_json(message)

  async def status_loop(self, remote) -> None:
    while True:
      offroad = self.status()
      ready = offroad and await self.local_ready()
      if not offroad and self.session_id is not None:
        old_session = self.session_id
        await self.stop_local()
        await self.send(remote, {"type": "ended", "session_id": old_session, "reason": "device_not_offroad"})
      await self.send(remote, {
        "type": "status",
        "protocol": PROTOCOL,
        "offroad": offroad,
        "local_ready": ready,
      })
      await asyncio.sleep(3)

  async def connection(self, remote) -> None:
    import aiohttp
    status_task = asyncio.create_task(self.status_loop(remote))
    try:
      async for message in remote:
        if message.type == aiohttp.WSMsgType.TEXT:
          if len(message.data.encode()) > MAX_REMOTE_BYTES:
            raise ValueError("terminal message is too large")
          await self.command(remote, message.json())
        elif message.type in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.ERROR):
          raise ValueError("invalid terminal server message")
    finally:
      status_task.cancel()
      with suppress(asyncio.CancelledError):
        await status_task
      await self.stop_local()


async def run() -> None:
  import aiohttp
  from openpilot.selfdrive.carrot.ha.collector import load_config

  agent = TerminalAgent()
  delay = 2
  while True:
    config = load_config()
    if not config or config.get("terminal_enabled") is not True:
      await asyncio.sleep(30)
      continue
    try:
      url = validate_config(config)
    except ValueError as exc:
      print(f"[Carrot HA terminal] configuration disabled: {exc}", flush=True)
      await asyncio.sleep(30)
      continue
    try:
      timeout = aiohttp.ClientTimeout(total=20)
      async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.ws_connect(
          url,
          headers={"Authorization": "Bearer " + config["terminal_token"]},
          heartbeat=10,
          max_msg_size=MAX_REMOTE_BYTES,
          compress=0,
        ) as remote:
          print("[Carrot HA terminal] connected; waiting for an HA administrator", flush=True)
          delay = 2
          await agent.connection(remote)
    except (aiohttp.ClientError, OSError, ValueError, RuntimeError, TimeoutError) as exc:
      print(f"[Carrot HA terminal] connection unavailable: {type(exc).__name__}: {exc}", flush=True)
    await asyncio.sleep(delay)
    delay = min(delay * 2, 60)


def run_in_thread() -> None:
  try:
    asyncio.run(run())
  except Exception as exc:
    print(f"[Carrot HA terminal] stopped: {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
  asyncio.run(run())
