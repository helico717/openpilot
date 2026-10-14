"""Git-managed setup of a direct receiver; changes persistent state only."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
import urllib.request
import time
import threading

PATH = Path('/data/carrot_ha/direct-connection.json')
PROFILE = Path(__file__).with_name('direct_receiver.json')
_lock = threading.Lock()
_retry_at = 0.0


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve(config, profile=PROFILE, path=PATH):
    """Only a Git-managed explicit source mapping may bootstrap a new destination."""
    global _retry_at
    profile = Path(profile)
    if Path(path).with_suffix('.disabled').exists():
        return config  # Only an explicit operator rollback can re-enable the previous source.
    if not profile.is_file():
        return config
    mapping = json.loads(profile.read_text(encoding='utf-8'))
    if config.get('url', '').rstrip('/') != mapping.get('previous_url'):
        return config
    destination = mapping['receiver_url']
    validate({'transport': 'direct', 'url': destination, 'device': config['device'], 'token': config['token']})
    pending = {**config, 'transport': 'direct', 'url': destination, '_awaiting_provision': True}
    with _lock:
        path = Path(path)
        if path.is_file():
            return validate(json.loads(path.read_text(encoding='utf-8')))
        if time.monotonic() < _retry_at:
            return pending
        _retry_at = time.monotonic() + 15
        try:
            request = urllib.request.Request(destination + '/api/provision',
                data=json.dumps({'device_id': config['device']}).encode(),
                headers={'Authorization': 'Bearer ' + config['token'], 'Content-Type': 'application/json'})
            with urllib.request.build_opener(NoRedirect).open(request, timeout=8) as response:
                payload = json.loads(response.read(4097))
            direct = validate(payload['config'])
            if direct['device'] != config['device'] or direct['url'] != destination:
                raise ValueError('provision_destination_mismatch')
            configure(direct, path)
            return direct
        except (OSError, ValueError, KeyError, TypeError):
            # Opted-in migration never sends data back to cloud on a temporary failure.
            return pending  # Device identity remains available for local CAN recording.


def validate(config):
    if not isinstance(config, dict) or config.get('transport') != 'direct':
        raise ValueError('invalid_direct_config')
    url = urlsplit(config.get('url', ''))
    if (url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment
            or url.path.rstrip('/') not in ('', '/carrot-receiver')
            or any(ord(c) <= 32 for c in config['url'])):
        raise ValueError('invalid_receiver_url')
    token = config.get('token', '')
    if (not isinstance(token, str) or not 32 <= len(token) <= 256 or not token.isascii()
            or any(c.isspace() for c in token)):
        raise ValueError('invalid_receiver_token')
    device = config.get('device', '')
    if not isinstance(device, str) or not 1 <= len(device) <= 128 or '/' in device:
        raise ValueError('invalid_device')
    return {**config, 'url': config['url'].rstrip('/')}


def configure(config, path=PATH):
    config = validate(config)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        json.dump(config, handle, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    path.with_suffix('.disabled').unlink(missing_ok=True)


def queue_store_path(state, namespace):
    if not isinstance(namespace, str) or not 1 <= len(namespace) <= 128:
        raise ValueError('invalid_queue_namespace')
    return Path(state) / ('param-sync-' + hashlib.sha256(namespace.encode()).hexdigest()[:32] + '.sqlite3')


if __name__ == '__main__':
    # stdin keeps credentials out of shell history. Existing cloud config is retained for rollback.
    if sys.argv[1:] == ['--rollback']:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        PATH.with_suffix('.disabled').write_text('explicit rollback\n', encoding='utf-8')
        PATH.unlink(missing_ok=True)
        print('Direct receiver disabled. Restart collector to use previous configuration.')
    elif not sys.argv[1:]:
        configure(json.load(sys.stdin))
        print('Direct receiver saved. Reboot to switch telemetry, trips, parameters and discovery together.')
    else:
        raise SystemExit('Use JSON on stdin, or --rollback.')
