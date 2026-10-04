"""Receive-only CAN capture -> HA analysis files. Never sends vehicle CAN."""
import asyncio
import gzip
import json
import os
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote

MAX_FRAMES = 30000
MAX_PLAIN = 4 * 1024 * 1024
MAX_WIRE = 512 * 1024
MAX_SPOOL = 128 * 1024 * 1024


def boot_ns():
    if hasattr(time, 'CLOCK_BOOTTIME'):
        return time.clock_gettime_ns(time.CLOCK_BOOTTIME)
    return time.monotonic_ns()


def encode_batch(device, key, frames, context, dropped=0):
    payload = dict(schema=1, device=device, batch_id=key, unix_ns=time.time_ns(),
                   boot_ns=boot_ns(), clock='CLOCK_BOOTTIME' if hasattr(time, 'CLOCK_BOOTTIME') else 'CLOCK_MONOTONIC', frames=frames,
                   context=context, dropped_frames=dropped)
    raw = json.dumps(payload, separators=(',', ':'), allow_nan=False).encode()
    if len(frames) > MAX_FRAMES or len(raw) > MAX_PLAIN:
        raise ValueError('CAN batch exceeds bounds')
    wire = gzip.compress(raw, compresslevel=1, mtime=0)
    if len(wire) > MAX_WIRE:
        raise ValueError('Compressed CAN batch exceeds bounds')
    return wire


class CaptureClient:
    def __init__(self, config, directory, context):
        self.config = config
        self.root = Path(directory) / 'can-capture-spool'
        self.root.mkdir(parents=True, exist_ok=True)
        self.context = context
        self.lock = threading.RLock()
        self.session = uuid.uuid4().hex
        self.sequence = 0
        self.enabled = False
        self.until = 0
        self.continuous = False
        self.destination = None
        self.dropped = 0
        self.last_error = None
        self.delivered = 0
        self.pending = sorted(self.root.glob('*.json.gz'))
        self.spool_bytes = sum(p.stat().st_size for p in self.pending)

    def status(self):
        value = dict(enabled=self.enabled, continuous=self.continuous, until=self.until, pending=len(self.pending),
                     pending_bytes=self.spool_bytes, delivered_batches=self.delivered,
                     dropped_frames=self.dropped, last_error=self.last_error, updated_at=time.time())
        temp = self.root / 'status.tmp'
        temp.write_text(json.dumps(value))
        temp.replace(self.root / 'status.json')

    def save(self, frames):
        if not frames:
            return
        key = f'{self.session}-{self.sequence:010}'
        self.sequence += 1
        try:
            wire = encode_batch(self.config['device'], key, frames, self.context(), self.dropped)
        except ValueError:
            if len(frames) < 2:
                raise
            midpoint = len(frames)//2
            self.save(frames[:midpoint])
            self.save(frames[midpoint:])
            return
        with self.lock:
            if self.spool_bytes + len(wire) > MAX_SPOOL:
                self.dropped += len(frames)
                self.last_error = 'temporary upload queue full'
                return
            path = self.root / (key + '.json.gz')
            temp = path.with_suffix('.tmp')
            temp.write_bytes(wire)
            temp.replace(path)
            self.pending.append(path)
            self.spool_bytes += len(wire)

    async def poll(self, client):
        from .terminal import discover
        while True:
            try:
                destination = self.destination
                if not destination or time.time()*1000 >= destination.get('expires_at', 0)-30000:
                    destination = await discover(client, self.config)
                if not destination:
                    raise ValueError('HA discovery not available')
                self.destination = destination
                url = destination['ha_url'].rstrip('/') + '/api/carrot_ha/v1/can-capture/' + quote(self.config['device'], safe='')
                async with client.get(url, headers={'Authorization': 'Bearer ' + destination['terminal_token']}, allow_redirects=False) as response:
                    response.raise_for_status()
                    status = await response.json()
                self.enabled = status.get('enabled') is True
                self.until = status.get('until') or 0
                self.continuous = status.get('continuous') is True
                self.last_error = None
            except Exception as error:
                # Preserve an already authorized capture during transient network outages.
                self.enabled = (self.continuous or time.time() < self.until) and getattr(error, 'status', None) not in (401, 403)
                self.last_error = 'discovery/status ' + type(error).__name__
            await asyncio.sleep(15 if self.enabled else 30)

    async def upload(self, client):
        while True:
            if not self.pending or not self.destination:
                await asyncio.sleep(1)
                continue
            with self.lock:
                path = self.pending[0]
            try:
                wire = await asyncio.to_thread(path.read_bytes)
                destination = self.destination
                url = destination['ha_url'].rstrip('/') + '/api/carrot_ha/v1/can-capture/' + quote(self.config['device'], safe='')
                async with client.post(url, data=wire, headers={
                    'Authorization': 'Bearer ' + destination['terminal_token'],
                    'Content-Type': 'application/gzip', 'X-Can-Batch': path.name.removesuffix('.json.gz')},
                    allow_redirects=False) as response:
                    response.raise_for_status()
                    ack = await response.json()
                if ack.get('ok') is not True or ack.get('batch_id') != path.name.removesuffix('.json.gz'):
                    raise ValueError('Invalid capture acknowledgement')
                with self.lock:
                    path.unlink()
                    self.pending.pop(0)
                    self.spool_bytes -= len(wire)
                    self.delivered += 1
            except Exception as error:
                self.last_error = 'upload ' + type(error).__name__
                await asyncio.sleep(10)

    async def run(self):
        import aiohttp
        from openpilot.cereal import messaging
        sock = None
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as client:
            tasks = [asyncio.create_task(self.poll(client)), asyncio.create_task(self.upload(client))]
            frames = []
            last_flush = last_status = time.monotonic()
            try:
                while True:
                    # A separate subscriber does not consume the telemetry reader's messages.
                    active = self.enabled and (self.continuous or time.time() < self.until)
                    if active and sock is None:
                        sock = messaging.sub_sock('can', timeout=0)
                    elif not active and sock is not None:
                        sock.close()
                        sock = None
                    if active:
                        # Bound work per iteration, including a continuously busy bus.
                        for _ in range(200):
                            packet = messaging.recv_one_or_none(sock)
                            if packet is None:
                                break
                            for frame in packet.can:
                                if len(frames) >= MAX_FRAMES:
                                    await asyncio.to_thread(self.save, frames)
                                    frames = []
                                frames.append([packet.logMonoTime, frame.address, frame.src, bytes(frame.dat).hex()])
                    now = time.monotonic()
                    if frames and now - last_flush >= 3:
                        await asyncio.to_thread(self.save, frames)
                        frames = []
                        last_flush = now
                    if now - last_status >= 10:
                        await asyncio.to_thread(self.status)
                        last_status = now
                    await asyncio.sleep(0.02)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if sock is not None:
                    sock.close()


def start_capture_thread(config, directory, context):
    def run():
        # Linux per-thread priority; existing telemetry/control threads stay unchanged.
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)
        except (AttributeError, OSError):
            pass
        while True:
            try:
                asyncio.run(CaptureClient(config, directory, context).run())
            except Exception as error:
                print('[Carrot CAN capture] restarting: ' + type(error).__name__, flush=True)
                time.sleep(30)
    thread = threading.Thread(target=run, name='ha-can-capture', daemon=True)
    thread.start()
    return thread
