"""Check the camera API contract, never the changing repository commit ID."""
import os
from pathlib import Path
import subprocess

STREAMS = ('livestreamWideRoadEncodeData', 'livestreamRoadEncodeData', 'livestreamDriverEncodeData')
BINARIES = ('openpilot/system/camerad/camerad', 'openpilot/system/loggerd/encoderd')


def require_runtime(root: Path):
    # Validate before setting ownership flags or launching any camera process.
    for relative in BINARIES:
        binary = root / relative
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise RuntimeError('Camera executable unavailable: ' + relative)
    try:
        version = subprocess.check_output(['/usr/bin/timeout', '--version'], text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError('GNU timeout unavailable') from exc
    if 'GNU coreutils' not in version:
        raise RuntimeError('GNU timeout required')
    import av
    if not hasattr(av.container.OutputContainer, 'add_stream_from_template'):
        raise RuntimeError('PyAV template remux API unavailable')
    from openpilot.cereal import messaging
    from openpilot.cereal.services import SERVICE_LIST
    for name in STREAMS:
        if name not in SERVICE_LIST:
            raise RuntimeError('Camera stream service unavailable: ' + name)
        try:
            event = messaging.new_message(name)
            packet = getattr(event, name)
            bytes(packet.header)
            bytes(packet.data)
            int(packet.idx.timestampSof)
        except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
            raise RuntimeError('Incompatible camera stream schema: ' + name) from exc
