"""Restore only existing HA connection identity from JSON stdin while offroad.

No Params, driving calibration, databases, queue history or program files are restored.
Existing different configuration is never overwritten. Camera remains disabled until
explicitly enabled by the owner with the normal camera.configure command.
"""
import json
import os
from pathlib import Path
import sys


def restore(payload, base=Path('/data/carrot_ha'), params=None):
    from .direct_connection import validate
    from .camera.agent import validate_config
    from .camera.probe import require_offroad
    if params is None:
        from .iq_camera import CameraParams
        params = CameraParams()
    require_offroad(params)
    if not isinstance(payload, dict) or set(payload) != {'receiver', 'camera'}:
        raise ValueError('Expected receiver and camera connection settings only')
    receiver, camera = payload['receiver'], payload['camera']
    if not isinstance(receiver, dict) or set(receiver) != {'transport', 'url', 'device', 'token'}:
        raise ValueError('Unexpected receiver configuration keys')
    if not isinstance(camera, dict) or set(camera) != {'ha_url', 'device_id', 'camera_token'}:
        raise ValueError('Unexpected camera configuration keys')
    receiver = validate(receiver)
    validate_config(camera)
    if receiver['device'] != camera['device_id']:
        raise ValueError('Receiver and camera device identity mismatch')
    base = Path(base)
    if base.is_symlink() or (base / 'camera').is_symlink():
        raise ValueError('Unexpected configuration directory symlink')
    if (base / 'direct-connection.disabled').exists() or (base / 'camera/enabled').exists():
        raise ValueError('Existing disabled receiver or active camera; review before restoring')
    targets = [(base / 'direct-connection.json', receiver), (base / 'camera/camera.json', camera)]
    for target, value in targets:
        if target.is_symlink() or (target.exists() and json.loads(target.read_text()) != value):
            raise ValueError('Different existing configuration; refusing overwrite')
    # All validations finish before the first write. A partial I/O failure can be
    # retried idempotently, but different configuration always requires review.
    for target, value in targets:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if target.exists():
            target.chmod(0o600)
            continue
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
    return 'HA_CONNECTION_RESTORED_CAMERA_DISABLED'


if __name__ == '__main__':
    try:
        raw = sys.stdin.buffer.read(32769)
        if len(raw) > 32768:
            raise ValueError('Configuration payload too large')
        print(restore(json.loads(raw)))
    except Exception:
        # Never include request data, URLs or credentials in a traceback/log.
        raise SystemExit('HA restore refused or failed; inspect state without displaying credentials')
