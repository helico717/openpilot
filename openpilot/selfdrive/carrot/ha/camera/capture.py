"""One bounded offroad capture session. Binary stdout belongs to the agent."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[5]
sys.path[:0] = [str(ROOT), str(ROOT / 'pydeps')]

from .protocol import MAX_PAYLOAD, encode_media
from .media import TransportMux
from .probe import active_camera_processes, require_offroad, stop_owned, param_bool
from .compatibility import require_runtime


def run(session_id):
    from openpilot.common.params import Params
    from openpilot.cereal import messaging

    params = Params()
    require_offroad(params)
    if params.get_bool('IsTakingSnapshot') or active_camera_processes():
        raise RuntimeError('Camera already in use')
    original = params.get('IsTakingSnapshot')
    if original is not None and param_bool(original) is None:
        raise RuntimeError('Unknown camera ownership flag')
    lease = {'last': time.monotonic(), 'stopped': False}

    def controls():
        try:
            for line in sys.stdin:
                if line.strip() == 'renew':
                    lease['last'] = time.monotonic()
                else:
                    break
        finally:
            lease['stopped'] = True

    threading.Thread(target=controls, daemon=True).start()
    def interrupted(signum, frame):
        raise RuntimeError('Capture interrupted')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM):
        signal.signal(sig, interrupted)
    children, sockets, muxes = [], [], {}
    flag_owned = False
    started = time.monotonic()
    # Nonblocking writes avoid holding cameras open when HA stops reading.
    os.set_blocking(sys.stdout.fileno(), False)
    pending = bytearray()
    last_progress = time.monotonic()
    try:
        poller = messaging.Poller()
        names = {
            'livestreamWideRoadEncodeData': 'wide',
            'livestreamRoadEncodeData': 'road',
            'livestreamDriverEncodeData': 'driver',
        }
        # H.264 delta frames depend on earlier frames. Conflation can discard
        # both the bootstrap keyframe and reference frames during scheduling
        # delays; only decoded display frames may safely be conflated.
        sockets = [messaging.sub_sock(name, poller=poller, conflate=False) for name in names]
        muxes = {name: TransportMux() for name in names.values()}
        require_offroad(params)
        if active_camera_processes() or params.get_bool('IsTakingSnapshot'):
            raise RuntimeError('Camera became busy')
        params.put_bool('IsTakingSnapshot', True)
        flag_owned = True
        signal.alarm(305)
        time.sleep(2)
        require_offroad(params)
        if active_camera_processes():
            raise RuntimeError('Another camera owner started')
        environment = dict(os.environ, STREAM_BITRATE='600000')
        for relative, arguments in (('system/camerad/camerad', []),
                                    ('system/loggerd/encoderd', ['--stream'])):
            require_offroad(params)
            binary = ROOT / 'openpilot' / relative
            children.append(subprocess.Popen(
                ['/usr/bin/timeout', '--signal=INT', '--kill-after=3s', '310s', str(binary), *arguments],
                cwd=binary.parent, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True))
        seen = {}
        while not lease['stopped'] and time.monotonic() - started < 300:
            require_offroad(params)
            now = time.monotonic()
            if now - lease['last'] >= 12:
                raise RuntimeError('Camera lease expired')
            if any(child.poll() is not None for child in children):
                raise RuntimeError('Camera process exited')
            for sock in poller.poll(50):
                event = messaging.recv_one_or_none(sock)
                if event is None or event.which() not in names:
                    continue
                camera = names[event.which()]
                packet = getattr(event, event.which())
                payload = muxes[camera].push(bytes(packet.header), bytes(packet.data), int(packet.idx.timestampSof))
                if payload:
                    seen[camera] = now
                for offset in range(0, len(payload), MAX_PAYLOAD):
                    wire = encode_media(session_id, camera, payload[offset:offset + MAX_PAYLOAD])
                    pending.extend(struct.pack('!I', len(wire)))
                    pending.extend(wire)
            if len(pending) > 2 * 1024 * 1024:
                raise RuntimeError('Camera consumer too slow')
            if pending:
                try:
                    written = os.write(sys.stdout.fileno(), pending)
                    del pending[:written]
                    last_progress = now
                except BlockingIOError:
                    if now - last_progress > 5:
                        raise RuntimeError('Camera output blocked')
            else:
                last_progress = now
            if now - started > 20 and (len(seen) < 2 or any(now - value > 10 for value in seen.values())):
                raise RuntimeError('Camera frames unavailable')
    finally:
        signal.alarm(0)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        errors = []
        for child in reversed(children):
            try:
                stop_owned(child)
            except Exception:
                errors.append('process_cleanup_failed')
        for sock in sockets:
            with __import__('contextlib').suppress(Exception):
                if hasattr(sock, 'close'):
                    sock.close()
        sockets.clear()
        if flag_owned:
            try:
                if param_bool(params.get('IsTakingSnapshot')) is True:
                    if original is None:
                        params.remove('IsTakingSnapshot')
                    else:
                        params.put_bool('IsTakingSnapshot', param_bool(original))
            except Exception:
                errors.append('flag_cleanup_failed')
        for mux in muxes.values():
            with __import__('contextlib').suppress(Exception):
                mux.close()
        if errors:
            raise RuntimeError('Capture cleanup incomplete')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', required=True)
    args = parser.parse_args()
    import uuid
    uuid.UUID(args.session)
    require_runtime(ROOT)
    with open('/tmp/carrot-camera-smoke.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(args.session)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # No URLs, credentials, images or arbitrary server text in this log.
        print(f'capture stopped: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        sys.exit(1)
