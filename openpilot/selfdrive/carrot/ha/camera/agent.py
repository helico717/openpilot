"""Outbound-only camera agent. No HTTP listener and no vehicle control commands."""
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import signal
import struct
import sys
from urllib.parse import quote, urlsplit, urlunsplit
import uuid

BASE = Path('/data/carrot_ha/camera')

from .protocol import HEADER, MAX_PAYLOAD


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError('Invalid configuration')
    address = config.get('ha_url', '')
    if not isinstance(address, str) or any(ord(c) <= 32 for c in address):
        raise ValueError('Invalid HTTPS address')
    url = urlsplit(address)
    if (url.scheme != 'https' or not url.hostname or url.path not in ('', '/')
            or url.query or url.fragment or url.username or url.password or url.port == 0):
        raise ValueError('An HTTPS base URL is required')
    token = config.get('camera_token', '')
    if not isinstance(token, str) or not 32 <= len(token) <= 256 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError('Invalid camera token')
    device_id = config.get('device_id', '')
    if not isinstance(device_id, str) or not device_id or len(device_id) > 128 or '/' in device_id:
        raise ValueError('Invalid device ID')
    return urlunsplit(('wss', url.netloc, '/api/carrot_ha/v1/camera/' + quote(device_id, safe=''), '', ''))


class DeviceAgent:
    def __init__(self, base=BASE, status=None):
        self.base = base
        self.status = status or self.offroad
        self.process = None
        self.pump_task = None
        self.session_id = None
        self.stop_lock = asyncio.Lock()

    def offroad(self):
        from openpilot.common.params import Params
        from .probe import param_bool, active_camera_processes
        params = Params()
        active = active_camera_processes()
        if self.process is None and not active and params.get_bool('IsTakingSnapshot'):
            with suppress(Exception):
                params.remove('IsTakingSnapshot')
        return (param_bool(params.get('IsOffroad')) is True
                and param_bool(params.get('IsOnroad')) is False
                and not params.get_bool('IsDriverViewEnabled')
                and (self.process is not None or (
                    not params.get_bool('IsTakingSnapshot') and not active)))

    async def stop_capture(self):
        async with self.stop_lock:
            process = self.process
            self.session_id = None
            if process is not None:
                if process.stdin:
                    process.stdin.close()  # Capture treats EOF as stop.
                try:
                    await asyncio.wait_for(process.wait(), 8)
                except TimeoutError:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), 8)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
                self.process = None
            if self.pump_task and self.pump_task is not asyncio.current_task():
                self.pump_task.cancel()
                with suppress(asyncio.CancelledError, ConnectionError, RuntimeError):
                    await self.pump_task
                self.pump_task = None

    async def pump(self, ws, process, session_id):
        try:
            while True:
                length = struct.unpack('!I', await process.stdout.readexactly(4))[0]
                if length < HEADER.size or length > HEADER.size + MAX_PAYLOAD:
                    raise ValueError('Invalid local capture frame')
                packet = await process.stdout.readexactly(length)
                async with asyncio.timeout(5):
                    await ws.send_bytes(packet)
        except (asyncio.IncompleteReadError, ConnectionError, RuntimeError, ValueError, TimeoutError):
            if process.stdin:
                process.stdin.close()
            with suppress(ConnectionError, RuntimeError, TimeoutError):
                async with asyncio.timeout(3):
                    await ws.send_json({'type': 'ended', 'session_id': session_id})

    async def command(self, ws, data):
        if not isinstance(data, dict):
            raise ValueError('Invalid control')
        kind = data.get('type')
        if kind == 'hello':
            if data.get('protocol') not in (1, 2):
                raise ValueError('Unsupported protocol')
            return
        session_id = data.get('session_id')
        if not isinstance(session_id, str):
            raise ValueError('Missing session')
        uuid.UUID(session_id)
        if kind == 'start':
            if self.process is not None or not self.status():
                await ws.send_json({'type': 'ended', 'session_id': session_id})
                return
            requested_cameras = data.get('cameras')
            if (not isinstance(requested_cameras, list) or not requested_cameras
                    or any(c not in ('wide', 'road', 'driver') for c in requested_cameras)):
                raise ValueError('Unsupported camera request')
            # Remote input cannot choose a program, path, duration or command.
            self.process = await asyncio.create_subprocess_exec(
                sys.executable, '-m', 'openpilot.selfdrive.carrot.ha.camera.capture', '--session', session_id,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=None, cwd=Path(__file__).resolve().parents[5],
                env=dict(os.environ, PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1'))
            self.session_id = session_id
            self.pump_task = asyncio.create_task(self.pump(ws, self.process, session_id))
        elif kind == 'renew':
            if session_id == self.session_id and self.process and self.process.returncode is None:
                self.process.stdin.write(b'renew\n')
                async with asyncio.timeout(2):
                    await self.process.stdin.drain()
        elif kind == 'stop':
            if session_id == self.session_id:
                await self.stop_capture()
        else:
            raise ValueError('Unsupported control')

    async def status_loop(self, ws):
        while True:
            if not (self.base / 'enabled').exists():
                await ws.close()
                return
            ready = self.status()
            if not ready and self.process is not None:
                await self.stop_capture()
            async with asyncio.timeout(5):
                await ws.send_json({'type': 'status', 'protocol': 1, 'offroad': ready})
            await asyncio.sleep(3)

    async def connection(self, ws):
        import aiohttp
        status_task = asyncio.create_task(self.status_loop(ws))
        # Close the socket if heartbeat/status fails, including background errors.
        def status_done(task):
            if not task.cancelled():
                task.exception()
                asyncio.create_task(ws.close())
        status_task.add_done_callback(status_done)
        try:
            async for message in ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    await self.command(ws, message.json())
                elif message.type in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.ERROR):
                    raise ValueError('Invalid server message')
        finally:
            status_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await status_task
            await self.stop_capture()


async def main(base=BASE):
    sys.path.insert(0, str(Path(__file__).resolve().parents[5] / 'pydeps'))
    import aiohttp
    config_path = base / 'camera.json'
    if config_path.stat().st_mode & 0o077:
        raise RuntimeError('camera.json must have mode 600')
    config = json.loads(config_path.read_text())
    url = validate_config(config)
    agent = DeviceAgent(base=base)
    running = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, running.cancel)
    delay = 2
    try:
        while (base / 'enabled').exists():
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as client:
                    async with client.ws_connect(url, headers={'Authorization': 'Bearer ' + config['camera_token']},
                                                 heartbeat=10, max_msg_size=4096, compress=0) as ws:
                        print('Camera control connected; idle until requested', flush=True)
                        delay = 2
                        await agent.connection(ws)
            except (aiohttp.ClientError, OSError, ValueError, RuntimeError, TimeoutError) as exc:
                print(f'Camera connection unavailable: {type(exc).__name__}: {exc}', flush=True)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)
    finally:
        await agent.stop_capture()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except asyncio.CancelledError:
        pass
