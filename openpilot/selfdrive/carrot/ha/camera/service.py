"""Manager entrypoint and one-time migration from the legacy camera bundle.

Only settings/enable markers/locks under /data are touched. Program files and
continue.sh are never rewritten. The legacy supervisor exits when disabled;
its flock is held for the lifetime of this service to prevent duplicate agents.
"""
import asyncio
import fcntl
import json
import os
from pathlib import Path
import signal
import tempfile

from .agent import BASE, main as run_agent, validate_config
from .probe import require_offroad

LEGACY = Path('/data/carrot-camera')


def configured(base=BASE, legacy=LEGACY):
    return any((path / 'enabled').is_file() and (path / 'camera.json').is_file()
               for path in (base, legacy))


def migrate_settings(base=BASE, legacy=LEGACY):
    """Idempotent; existing native configuration/disabled state takes precedence."""
    if not (base / 'camera.json').exists() and (legacy / 'enabled').is_file():
        source = legacy / 'camera.json'
        if source.stat().st_mode & 0o077:
            raise RuntimeError('Legacy camera.json must have mode 600')
        data = source.read_text()
        validate_config(json.loads(data))
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix='.camera-', dir=base)
        try:
            with os.fdopen(fd, 'w') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            # Enable before the atomic config rename: a restart can finish the
            # migration and never strands an enabled legacy installation.
            (base / 'enabled').touch(mode=0o600)
            os.replace(temporary, base / 'camera.json')
        finally:
            Path(temporary).unlink(missing_ok=True)
    if (base / 'camera.json').is_file():
        validate_config(json.loads((base / 'camera.json').read_text()))
        if (base / 'camera.json').stat().st_mode & 0o077:
            raise RuntimeError('camera.json must have mode 600')
        # Runtime marker only. The old startup hook becomes inert without edits.
        (legacy / 'enabled').unlink(missing_ok=True)


async def serve(base=BASE, legacy=LEGACY, params=None):
    if params is None:
        from openpilot.common.params import Params
        params = Params()
    # Do not change service ownership during driving or unknown vehicle state.
    while True:
        try:
            require_offroad(params)
            break
        except RuntimeError:
            await asyncio.sleep(2)
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (base / 'service.lock').open('a') as service_lock:
        try:
            fcntl.flock(service_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        migrate_settings(base, legacy)
        # Do not spawn a replacement until the old supervisor AND its agent
        # release their inherited lock. Timeout/retry waits are deliberately
        # allowed to finish; never kill an unrelated process based on its name.
        legacy_lock = None
        try:
            if legacy.is_dir():
                legacy_lock = (legacy / 'supervisor.lock').open('a')
                while True:
                    try:
                        fcntl.flock(legacy_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        await asyncio.sleep(2)
            if (base / 'enabled').is_file():
                await run_agent(base)
        finally:
            if legacy_lock is not None:
                legacy_lock.close()


async def async_main():
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)
    await serve()


def main():
    try:
        asyncio.run(async_main())
    except asyncio.CancelledError:
        pass


if __name__ == '__main__':
    main()
