"""Standalone MyID4 CAN reader -> existing Cloudflare API, with durable outbox."""
from __future__ import annotations
import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

try:
    from .engine import Store, Engine
    from .telemetry_fields import device_health
except (ImportError, ValueError):
    from engine import Store, Engine
    from telemetry_fields import device_health

BASE = Path(__file__).resolve().parent

def _resolve_data_dir() -> Path:
    if os.getenv("CARROT_HA_DATA_DIR"):
        return Path(os.getenv("CARROT_HA_DATA_DIR"))
    if Path("/data/id4-collector").exists():
        return Path("/data/id4-collector")
    d = Path("/data/carrot_ha")
    d.mkdir(parents=True, exist_ok=True)
    return d

DATA_DIR = _resolve_data_dir()
STATE = DATA_DIR / 'state'
LOCK_FILE = DATA_DIR / 'collector.lock'


def load_config() -> dict | None:
    candidates = [
        os.getenv("CARROT_HA_CONFIG"),
        "/data/id4-collector/connection.json",
        "/data/carrot_ha/connection.json",
        str(BASE / "connection.json"),
    ]
    for p in candidates:
        if p and Path(p).is_file():
            try:
                return json.loads(Path(p).read_text(encoding='utf-8'))
            except Exception:
                pass
    try:
        from openpilot.common.params import Params
        raw = Params().get("CarrotHaConfig")
        if raw:
            return json.loads(raw.decode('utf-8'))
    except Exception:
        pass
    return None


def atomic(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    config = load_config()
    while not config:
        print("[Carrot HA] No connection.json found. Waiting for configuration...", flush=True)
        time.sleep(30)
        config = load_config()

    from urllib.parse import urlsplit
    url = urlsplit(config['url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
        raise ValueError('Invalid Worker URL')

    from openpilot.cereal import messaging
    from openpilot.common.params import Params
    try:
        from . import wayon_vehicle_telemetry as reference
    except (ImportError, ValueError):
        import wayon_vehicle_telemetry as reference

    store = Store(STATE / 'collector.sqlite3')
    engine = Engine(store, config['device'])

    # On restart, publish a newly observed snapshot before draining old records.
    engine.s.pop('last_upload', None)
    first_snapshot = threading.Event()
    sample_lock = threading.Lock()
    latest_sample = {}
    sample_version = 0

    def sample():
        nonlocal latest_sample, sample_version
        while True:
            try:
                values = reference.sample_vehicle_can(timeout_s=4)
                with sample_lock:
                    latest_sample = values
                    sample_version += 1
            except Exception as error:
                print('CAN sample:', type(error).__name__, flush=True)
            time.sleep(26)

    def upload():
        first_snapshot.wait()
        delay = 2
        prefer_latest = True

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        while True:
            row = (store.latest_telemetry() if prefer_latest else None) or store.first()
            if not row:
                time.sleep(2)
                continue
            key, path, body = row
            try:
                request = urllib.request.Request(
                    config['url'].rstrip('/') + path,
                    data=body.encode(),
                    headers={
                        'Authorization': 'Bearer ' + config['token'],
                        'User-Agent': 'CarrotHA/0.3.0',
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    }
                )
                with opener.open(request, timeout=30) as response:
                    ack = json.load(response)
                if ack.get('ok') is not True or (path == '/api/trips' and ack.get('id') != json.loads(body)['id']):
                    raise ValueError('Invalid acknowledgement')
                store.acknowledge(key)
                delay = 2
                prefer_latest = not prefer_latest
                atomic(STATE / 'delivery.json', {'status': 'ok', 'at': time.time(), 'path': path, 'pending': store.count()})
            except Exception as error:
                prefer_latest = True
                reason = type(error).__name__ + (' HTTP ' + str(error.code) if isinstance(error, urllib.error.HTTPError) else '')
                atomic(STATE / 'delivery.json', {'status': 'retrying', 'reason': reason, 'pending': store.count(), 'at': time.time()})
                print('Upload retry:', reason, flush=True)
                time.sleep(delay)
                delay = min(120, delay * 2)

    # Temporary raw CAN analysis uses HA files, not the normal telemetry outbox.
    try:
        from .can_capture import start_capture_thread
    except (ImportError, ValueError):
        from can_capture import start_capture_thread
    def capture_context():
        values = dict(engine.s.get('vehicle', {}))
        keys = {'battery_wh', 'charging', 'charge_power_w', 'driving', 'comma_onroad', 'gear', 'wheel_speed_mps'}
        return {'observed_at': time.time(), 'onroad': engine.s.get('onroad'),
                'values': {key: value for key, value in values.items() if key in keys or key.startswith('charge_can_')},
                'field_measured_at': {key: value for key, value in dict(engine.s.get('field_measured_at', {})).items()
                                     if key in keys or key.startswith('charge_can_')}}
    try:
        start_capture_thread(config, DATA_DIR, capture_context)
    except Exception as error:
        print("CAN capture start error:", type(error).__name__, flush=True)

    threading.Thread(target=sample, daemon=True).start()
    threading.Thread(target=upload, daemon=True).start()

    try:
        try:
            from .param_sync import start_param_sync_thread
        except (ImportError, ValueError):
            from param_sync import start_param_sync_thread
        start_param_sync_thread(config)
    except Exception as err:
        print('Param sync start error:', err, flush=True)

    sm = messaging.SubMaster(['carState', 'gpsLocationExternal', 'gpsLocation', 'peripheralState', 'selfdriveState', 'deviceState'])
    params = Params()
    consumed = -1
    last_health = 0
    print('Carrot HA collector started: receive-only CAN, Cloudflare outbox.', flush=True)

    while True:
        time.sleep(1)
        sm.update(0)
        now = time.time()
        mono = time.monotonic()
        if now < 1735689600:
            continue

        gps = None
        for service in ['gpsLocationExternal', 'gpsLocation']:
            if sm.valid.get(service) and sm.seen.get(service) and mono - sm.recv_time[service] < 10:
                g = sm[service]
                if g.hasFix:
                    gps = {
                        'latitude': float(g.latitude),
                        'longitude': float(g.longitude),
                        'speedMps': float(g.speed),
                        'bearingDeg': float(g.bearingDeg),
                        'accuracyM': float(g.horizontalAccuracy),
                        'fresh': True,
                    }
                    import math
                    if not all(math.isfinite(v) for v in gps.values()) or abs(gps['latitude']) > 90 or abs(gps['longitude']) > 180:
                        gps = None
                    else:
                        break

        with sample_lock:
            sampled = dict(latest_sample) if consumed != sample_version else None
            consumed = sample_version

        if sampled is not None and sm.valid.get('peripheralState') and mono - sm.recv_time['peripheralState'] < 10:
            mv = sm['peripheralState'].voltage
            if 9000 <= mv <= 18000:
                sampled['aux_voltage'] = round(mv / 1000, 2)

        enabled = None
        if sm.valid.get('selfdriveState') and mono - sm.recv_time['selfdriveState'] < 10:
            enabled = bool(sm['selfdriveState'].enabled)

        motion = None
        if sm.valid.get('carState') and sm.seen.get('carState') and mono - sm.recv_time['carState'] < 2:
            car = sm['carState']
            if car.canValid:
                motion = {'gear': str(car.gearShifter), 'speed_mps': float(car.vEgo)}

        diagnostics = None
        if mono - last_health >= 10 and sm.seen.get('deviceState') and sm.valid.get('deviceState') and mono - sm.recv_time['deviceState'] < 10:
            try:
                diagnostics = device_health(sm['deviceState'])
            except Exception:
                diagnostics = None
            last_health = mono

        events = engine.tick(now, params.get_bool('IsOnroad'), gps, sampled, enabled, motion=motion, diagnostics=diagnostics, monotonic_now=mono)
        if any(path == '/api/telemetry' for path, _ in events):
            first_snapshot.set()

        atomic(STATE / 'status.json', {
            'status': 'running',
            'at': now,
            'onroad': engine.s['vehicle'].get('comma_onroad'),
            'driving': engine.s.get('onroad'),
            'gear': engine.s['vehicle'].get('gear'),
            'pending': store.count(),
            'can_fields': sorted((latest_sample or {}).keys()),
            'active_trip': bool(engine.s.get('trip'))
        })


if __name__ == '__main__':
    try:
        import fcntl
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOCK_FILE.open('w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                sys.exit(0)
            main()
    except Exception:
        main()
