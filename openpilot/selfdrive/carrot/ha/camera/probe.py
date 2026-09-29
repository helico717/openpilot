"""Bounded, local camera/encoder probe for a comma disconnected from the vehicle.

Unlike camera_preflight.py, this starts cameras temporarily. It stores no images
and opens no network listener. Use only with --vehicle-disconnected.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


SOURCES = ("wideRoadCameraState", "driverCameraState",
           "livestreamWideRoadEncodeData", "livestreamDriverEncodeData")


def param_bool(value):
    """Accept typed Params booleans and legacy bytes without treating missing as false."""
    if type(value) is bool:
        return value
    if isinstance(value, (bytes, str)):
        if value in (b"1", "1"):
            return True
        if value in (b"0", "0"):
            return False
    return None


def require_offroad(params):
    offroad, onroad = params.get("IsOffroad"), params.get("IsOnroad")
    if param_bool(offroad) is not True or param_bool(onroad) is not False:
        raise RuntimeError(
            f"Explicit offroad state required; stopping test (IsOffroad={offroad!r}, IsOnroad={onroad!r})")
    if params.get_bool("IsDriverViewEnabled"):
        raise RuntimeError("Driver view is active; stopping test")


def active_camera_processes():
    found = []
    for path in Path("/proc").glob("[0-9]*/comm"):
        try:
            if path.read_text().strip() in {"camerad", "encoderd"}:
                found.append(int(path.parent.name))
        except OSError:
            pass
    return found


def stop_owned(process):
    """Signal only the process group created by this test, never by name."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGINT)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=3)


def interrupted(signum, _frame):
    raise RuntimeError(f"Test interrupted by signal {signum}")


def run(root, timeout_binary, verify_decode=False):
    sys.path[:0] = [str(root), str(root / "pydeps")]
    from openpilot.common.params import Params
    from openpilot.cereal import messaging

    params = Params()
    require_offroad(params)
    if params.get_bool("IsTakingSnapshot") or active_camera_processes():
        raise RuntimeError("Camera/snapshot already in use; nothing started")
    original = params.get("IsTakingSnapshot")
    if original is not None and param_bool(original) is None:
        raise RuntimeError("Unrecognized snapshot flag; nothing started")
    counts = {name: 0 for name in SOURCES}
    encoded_bytes = {name: 0 for name in SOURCES if "Encode" in name}
    codec_headers = {name: 0 for name in encoded_bytes}
    decoders = {}
    decoded_frames = {name: 0 for name in encoded_bytes}
    frame_sizes = {}
    if verify_decode:
        # PyAV is already used by this branch's WebRTC implementation.
        # Import/create decoders before changing parameters or starting cameras.
        import av
        decoders = {name: av.CodecContext.create("h264", "r") for name in encoded_bytes}
    report = {"schema": "carrot-camera-smoke-v1", "passed": False,
              "messages": counts, "encoded_bytes": encoded_bytes,
              "codec_headers": codec_headers,
              "note": "Message arrival only; image quality and browser decoding are not verified."}
    if verify_decode:
        report.update(decoded_frames=decoded_frames, frame_sizes=frame_sizes,
                      note="Local H.264 decoding only; visual quality and browser playback are not verified.")
    children, sockets = [], []
    flag_owned = False
    with tempfile.TemporaryDirectory(prefix="carrot-camera-probe-") as tmp:
        with open(Path(tmp) / "process.log", "wb") as output:
            try:
                poller = messaging.Poller()
                sockets = [messaging.sub_sock(name, poller=poller, conflate=False) for name in SOURCES]
                require_offroad(params)
                if active_camera_processes() or params.get_bool("IsTakingSnapshot"):
                    raise RuntimeError("Camera became busy; nothing started")
                params.put_bool("IsTakingSnapshot", True)
                flag_owned = True
                signal.alarm(30)
                time.sleep(2)  # Follow snapshot.py's hardware power preparation.
                require_offroad(params)
                if active_camera_processes():
                    raise RuntimeError("Another camera owner started; refusing to start duplicates")
                environment = dict(os.environ, STREAM_BITRATE="600000")
                for relative, arguments in (
                    ("system/camerad/camerad", []),
                    ("system/loggerd/encoderd", ["--stream"]),
                ):
                    require_offroad(params)
                    binary = root / "openpilot" / relative
                    # An independent timeout also bounds child lifetime if this
                    # Python process disappears before its finally block runs.
                    children.append(subprocess.Popen(
                        [timeout_binary, "--signal=INT", "--kill-after=3s", "35s",
                         str(binary), *arguments], cwd=binary.parent,
                        env=environment, stdin=subprocess.DEVNULL,
                        stdout=output, stderr=output, start_new_session=True,
                    ))
                started = time.monotonic()
                while time.monotonic() - started < 20:
                    require_offroad(params)
                    if any(child.poll() is not None for child in children):
                        raise RuntimeError("Camera or encoder exited early")
                    for sock in poller.poll(100):
                        event = messaging.recv_one_or_none(sock)
                        if event is None or event.which() not in counts:
                            continue
                        name = event.which()
                        counts[name] += 1
                        if name in encoded_bytes:
                            packet = getattr(event, name)
                            encoded_bytes[name] += len(packet.data)
                            codec_headers[name] += bool(packet.header)
                            if verify_decode:
                                decoder = decoders[name]
                                for compressed in decoder.parse(bytes(packet.header) + bytes(packet.data)):
                                    for frame in decoder.decode(compressed):
                                        decoded_frames[name] += 1
                                        frame_sizes[name] = [frame.width, frame.height]
                    if (all(value >= 10 for value in counts.values())
                            and all(encoded_bytes.values()) and all(codec_headers.values())
                            and (not verify_decode or all(decoded_frames.values()))):
                        report["passed"] = True
                        break
                report["observation_seconds"] = round(time.monotonic() - started, 2)
                if not report["passed"]:
                    report["error"] = "Timed out waiting for both cameras and H.264 data/headers or requested decoding"
            except Exception as exc:
                report["error"] = str(exc)
            finally:
                signal.alarm(0)
                # Avoid a second Ctrl-C interrupting resource cleanup.
                for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                    signal.signal(sig, signal.SIG_IGN)
                cleanup_errors = []
                for child in reversed(children):
                    try:
                        stop_owned(child)
                    except Exception as exc:
                        cleanup_errors.append(type(exc).__name__)
                for sock in sockets:
                    try:
                        sock.close()
                    except Exception:
                        pass
                if flag_owned:
                    try:
                        if param_bool(params.get("IsTakingSnapshot")) is True:
                            if original is None:
                                params.remove("IsTakingSnapshot")
                            else:
                                params.put_bool("IsTakingSnapshot", param_bool(original))
                    except Exception as exc:
                        cleanup_errors.append(type(exc).__name__)
                report["cleanup_errors"] = cleanup_errors
                report["remaining_camera_pids"] = active_camera_processes()
                report["snapshot_flag_restored"] = params.get("IsTakingSnapshot") == original
                if cleanup_errors or report["remaining_camera_pids"] or not report["snapshot_flag_restored"]:
                    report["passed"] = False
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vehicle-disconnected", action="store_true")
    parser.add_argument("--verify-decode", action="store_true",
                        help="Also decode both H.264 streams locally in memory; no images are saved")
    args = parser.parse_args()
    if not args.vehicle_disconnected:
        parser.error("Run only disconnected from the vehicle, with --vehicle-disconnected")
    root = Path("/data/openpilot")
    from .compatibility import require_runtime
    require_runtime(root)
    timeout_binary = shutil.which("timeout")
    if not timeout_binary:
        raise SystemExit("GNU timeout is required; nothing started")
    version = subprocess.check_output([timeout_binary, "--version"], text=True)
    if "GNU coreutils" not in version:
        raise SystemExit("GNU timeout is required; nothing started")
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGALRM):
        signal.signal(sig, interrupted)
    with open("/tmp/carrot-camera-smoke.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another probe is running")
        result = run(root, timeout_binary, verify_decode=args.verify_decode)
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
