"""Read-only candidate diagnostics. Never sends CAN, starts cameras or reboots."""
import argparse
import json
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def check_runtime(root):
    checks = {}
    checks['arm64'] = platform.machine() in ('aarch64', 'arm64') and sys.platform == 'linux'
    checks['python_312'] = sys.version_info[:2] == (3, 12)
    try:
        expected = json.loads((root / 'HA_CANDIDATE.json').read_text())['iqpilot_sha']
        actual = subprocess.check_output(['git', '-C', str(root / 'vendor/iqpilot'), 'rev-parse', 'HEAD'], text=True).strip()
        checks['vendor_checkout'] = actual == expected and all(
            subprocess.run(['git', '-C', str(root / 'vendor/iqpilot'), 'diff', *flags, '--quiet'], capture_output=True).returncode == 0
            for flags in ([], ['--cached']))
    except Exception:
        checks['vendor_checkout'] = False
    try:
        from iqpilot.common.params import Params
        from .iq_camera import CameraParams
        params = Params()
        required = ('IsOffroad', 'IsOnroad', 'IsDriverViewEnabled', 'IQSentryRecording', 'IsLiveStreaming')
        checks['params_keys'] = all(params.check_key(key) for key in required)
        checks['camera_params_proxy'] = CameraParams(params).get('IsTakingSnapshot') in (b'0', b'1')
    except Exception:
        checks['params_keys'] = False
    try:
        from iqdbc.can.parser import CANParser
        required = [('Motor_16', 2), ('HVEM_02', 10), ('MEB_HVEM_01', 100), ('BMS_04', 2),
                    ('Diagnose_01', 1), ('Klima_Sensor_02', 1), ('Klima_11', 5), ('Klima_12', 5)]
        for bus in (0, 1):
            CANParser('vw_meb', required, bus)
        checks['meb_can_parsers'] = True
    except Exception:
        checks['meb_can_parsers'] = False
    try:
        from .camera.compatibility import require_runtime
        require_runtime(root)
        checks['camera_runtime_and_schema'] = True
    except Exception:
        checks['camera_runtime_and_schema'] = False
    import importlib.util
    checks['video_remux'] = shutil.which('ffmpeg') is not None or importlib.util.find_spec('av') is not None
    checks['os_expected'] = Path('/VERSION').is_file() and Path('/VERSION').read_text().strip().startswith('IQ.OS 4.9.9.4')
    checks['ha_configuration_present'] = any(Path(path).is_file() for path in (
        '/data/id4-collector/connection.json', '/data/carrot_ha/connection.json', '/data/carrot_ha/direct-connection.json'))
    return checks


def check_source(root):
    manifest = json.loads((root / 'HA_CANDIDATE.json').read_text())
    expected = manifest['iqpilot_sha']
    entry = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--stage', 'vendor/iqpilot'], text=True).strip()
    checks = {'vendor_pin': entry.startswith('160000 ' + expected + ' '),
              'launch_without_vendor': (root / 'launch_openpilot.sh').is_file() and not (root / 'launch_openpilot.sh').is_symlink(),
              'private_runtime_outside_git': (root / '.iqpilot').is_symlink() and os.readlink(root / '.iqpilot') == '/data/iqpilot-ha-runtime'}
    checks['candidate_sources_intact'] = all(
        (root / name).is_file() and hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
        for name, digest in manifest.get('candidate_source_sha256', {}).items()) and bool(manifest.get('candidate_source_sha256'))
    for relative in ('launch_openpilot.sh', 'launch_chffrplus.sh', 'bootstrap/ensure_vendor.sh'):
        checks['shell_' + relative] = subprocess.run(['bash', '-n', str(root / relative)], capture_output=True).returncode == 0
    for directory in ('artifacts', 'iqpilot/selfdrive/assets', 'iqpilot/third_party'):
        path = root / directory
        resolved = Path(os.path.abspath(path.parent / os.readlink(path)))
        checks['vendor_link_' + directory] = resolved == root / 'vendor/iqpilot' / directory
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    checks = check_source(root)
    if not args.source_only:
        checks.update(check_runtime(root))
    passed = all(checks.values())
    print(json.dumps({'stage': 'SOURCE_ONLY' if args.source_only else 'LOCAL_RUNTIME',
                      'passed': passed, 'checks': checks, 'field_test_required': True}, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
