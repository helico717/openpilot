"""IQpilot PTY adapter for the existing administrator-only HA reverse relay.

No listener, Carrot web server, SSH port, or history replay. The relay still
enforces its administrator lease. Local explicit offroad is checked separately.
"""
import asyncio
import base64
from contextlib import suppress
import errno
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios
import uuid

from .terminal import TerminalAgent, PROTOCOL


class IQTerminalAgent(TerminalAgent):
    def __init__(self, status=None, *, shell=('/bin/bash', '-il'), cwd='/data/openpilot'):
        if status is None:
            super().__init__()
        else:
            super().__init__(status)
        self.shell, self.cwd = shell, cwd
        self.master = -1
        self.process = None

    async def local_ready(self):
        return self.status()

    async def start_local(self, remote, session_id):
        uuid.UUID(session_id)
        if self.session_id is not None or not self.status():
            await self.send(remote, {'type': 'ended', 'session_id': session_id, 'reason': 'not_ready'})
            return
        master, slave = pty.openpty()
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 30, 100, 0, 0))
            environment = dict(os.environ, TERM='xterm-256color')
            environment.pop('TMUX', None)
            process = subprocess.Popen(self.shell, cwd=self.cwd, env=environment,
                                       stdin=slave, stdout=slave, stderr=slave,
                                       start_new_session=True, close_fds=True)
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        os.set_blocking(master, False)
        self.master, self.process, self.session_id = master, process, session_id
        self.local_task = asyncio.create_task(self._pump(remote, session_id))
        await self.send(remote, {'type': 'started', 'session_id': session_id})

    async def _pump(self, remote, session_id):
        reason = 'local_ended'
        loop = asyncio.get_running_loop()
        fd = self.master
        try:
            while self.session_id == session_id:
                if not self.status():
                    reason = 'device_not_offroad'
                    break
                ready = loop.create_future()
                def readable():
                    if not ready.done():
                        ready.set_result(None)
                loop.add_reader(fd, readable)
                try:
                    await ready
                finally:
                    loop.remove_reader(fd)
                if not self.status():
                    reason = 'device_not_offroad'
                    break
                try:
                    data = os.read(fd, 4096)
                except BlockingIOError:
                    continue
                except OSError as error:
                    if error.errno == errno.EIO:
                        break
                    raise
                if not data:
                    break
                await self.send(remote, {'type': 'terminal', 'session_id': session_id,
                                        'message': {'type': 'pty_output',
                                                    'b64': base64.b64encode(data).decode()}})
        finally:
            if self.session_id == session_id:
                await self.stop_local()
                with suppress(ConnectionError, RuntimeError, TimeoutError):
                    await self.send(remote, {'type': 'ended', 'session_id': session_id, 'reason': reason})

    async def stop_local(self):
        task, process, fd = self.local_task, self.process, self.master
        self.session_id = None
        self.local_task, self.process, self.master = None, None, -1
        if fd >= 0:
            asyncio.get_running_loop().remove_reader(fd)
        if process is not None and process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.to_thread(process.wait, timeout=3)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await asyncio.to_thread(process.wait, timeout=3)
        if fd >= 0:
            with suppress(OSError):
                os.close(fd)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def command(self, remote, data):
        if not isinstance(data, dict):
            raise ValueError('Invalid terminal command')
        kind = data.get('type')
        if kind == 'hello':
            if data.get('protocol') != PROTOCOL:
                raise ValueError('Unsupported protocol')
            return
        session_id = data.get('session_id')
        uuid.UUID(session_id)
        if kind == 'start':
            await self.start_local(remote, session_id)
            return
        if kind == 'stop':
            if self.session_id == session_id:
                await self.stop_local()
            return
        if kind != 'input':
            raise ValueError('Unsupported command')
        if session_id != self.session_id or self.master < 0:
            return
        if not self.status():
            await self.stop_local()
            await self.send(remote, {'type': 'ended', 'session_id': session_id, 'reason': 'device_not_offroad'})
            return
        message = data.get('message')
        if not isinstance(message, dict):
            raise ValueError('Invalid input')
        if message.get('type') == 'raw':
            text = message.get('data')
            if not isinstance(text, str) or not text or len(text.encode()) > 4096:
                raise ValueError('Invalid input size')
            value = text.encode()
        elif message.get('type') == 'control' and message.get('action') in ('ctrl_c', 'clear', 'refresh'):
            value = {'ctrl_c': b'\x03', 'clear': b'\x0c', 'refresh': b'\r'}[message['action']]
        else:
            raise ValueError('Unsupported input')
        while value:
            if self.session_id != session_id or self.master < 0 or not self.status():
                await self.stop_local()
                return
            try:
                written = os.write(self.master, value)
                if written <= 0:
                    raise RuntimeError('PTY input failed')
                value = value[written:]
            except BlockingIOError:
                await asyncio.sleep(0.01)
