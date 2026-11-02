"""Camera ownership outside compiled IQ Params; never alters IQ control keys."""
import json
import os
import fcntl
from contextlib import contextmanager
from pathlib import Path


class CameraParams:
    def __init__(self, native=None, marker=Path('/data/carrot_ha/camera/iq-ownership.json')):
        if native is None:
            from iqpilot.common.params import Params
            native = Params()
        self.native, self.marker = native, Path(marker)

    @contextmanager
    def _lock(self):
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.marker.with_suffix('.lock'), os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, 'a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def _owner(self):
        try:
            owner = json.loads(self.marker.read_text())['pid']
            if type(owner) is not int or owner <= 0:
                raise ValueError('Invalid owner')
            os.kill(owner, 0)
            return owner
        except (FileNotFoundError, ProcessLookupError):
            return None
        except PermissionError:
            raise RuntimeError('Camera owner cannot be verified')

    def get(self, key, *args, **kwargs):
        if key == 'IsTakingSnapshot':
            return b'1' if self._owner() is not None else b'0'
        return self.native.get(key, *args, **kwargs)

    def get_bool(self, key):
        if key == 'IsTakingSnapshot':
            return self.get(key) == b'1'
        return self.native.get_bool(key)

    def put_bool(self, key, value):
        if key != 'IsTakingSnapshot':
            raise ValueError('Camera adapter may only write its own ownership marker')
        if not value:
            self.remove(key)
            return
        with self._lock():
            owner = self._owner()
            if owner is not None:
                if owner != os.getpid():
                    raise RuntimeError('Camera already owned')
                return
            self.marker.unlink(missing_ok=True)
            descriptor = os.open(self.marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w') as stream:
                json.dump({'pid': os.getpid()}, stream)
                stream.flush()
                os.fsync(stream.fileno())

    def remove(self, key):
        if key != 'IsTakingSnapshot':
            raise ValueError('Camera adapter cannot remove IQ Params')
        with self._lock():
            if self._owner() in (None, os.getpid()):
                self.marker.unlink(missing_ok=True)

    def iq_camera_busy(self):
        try:
            return any(self.native.get_bool(key) for key in ('IQSentryRecording', 'IsLiveStreaming'))
        except Exception:
            return True
