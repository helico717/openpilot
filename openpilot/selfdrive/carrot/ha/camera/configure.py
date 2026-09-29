"""Configure locally; credentials never need to be sent to a developer."""
import argparse
import getpass
import json
import os
from pathlib import Path
import secrets

from .agent import validate_config, BASE
from .service import LEGACY
from .probe import require_offroad


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--enable', action='store_true')
    actions.add_argument('--disable', action='store_true')
    args = parser.parse_args()
    from openpilot.common.params import Params
    require_offroad(Params())
    base = BASE
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = base / 'camera.json'
    if args.disable:
        (base / 'enabled').unlink(missing_ok=True)
        (LEGACY / 'enabled').unlink(missing_ok=True)
        print('Camera service disabled; manager will stop it.')
        return
    if args.enable:
        validate_config(json.loads(path.read_text()))
        if path.stat().st_mode & 0o077:
            raise SystemExit('camera.json must have mode 600')
        (base / 'enabled').touch(mode=0o600)
        print('Camera service enabled; manager will start it.')
        return
    if (base / 'enabled').exists() or (LEGACY / 'enabled').exists():
        raise SystemExit('Disable the camera service before changing credentials.')
    url = input('HA external HTTPS base URL: ').strip().rstrip('/')
    device = input('Existing Carrot HA device ID (not DongleId): ').strip()
    token = getpass.getpass('Dedicated camera token (Enter to generate): ').strip()
    generated = not token
    token = token or secrets.token_hex(32)
    config = {'ha_url': url, 'device_id': device, 'camera_token': token}
    validate_config(config)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(config, handle)
        handle.write('\n')
    temporary.replace(path)
    if generated:
        print('Paste this camera-only token into Carrot HA options; do not share it:')
        print(token)
    print('Saved camera.json (600). Service has not been started.')


if __name__ == '__main__':
    main()
