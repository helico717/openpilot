"""Carrot HA camera wire protocol v1; keep compatible with HA camera_session.py."""
import struct
import uuid

CAMERAS = {"wide": 1, "driver": 2, "road": 3}
HEADER = struct.Struct("!4s16sB")
MAGIC = b"CHV1"
MAX_PAYLOAD = 188 * 512


def encode_media(session_id, camera, payload):
    if camera not in CAMERAS:
        raise ValueError("Unknown camera")
    _validate_ts(payload)
    return HEADER.pack(MAGIC, uuid.UUID(session_id).bytes, CAMERAS[camera]) + payload


def _validate_ts(payload):
    if not payload or len(payload) > MAX_PAYLOAD or len(payload) % 188:
        raise ValueError("Invalid MPEG-TS payload size")
    if any(payload[offset] != 0x47 for offset in range(0, len(payload), 188)):
        raise ValueError("Invalid MPEG-TS packet sync")


def decode_media(data):
    if not isinstance(data, bytes) or len(data) < HEADER.size or len(data) > HEADER.size + MAX_PAYLOAD:
        raise ValueError("Invalid media message size")
    magic, session, camera_id = HEADER.unpack_from(data)
    if magic != MAGIC or camera_id not in CAMERAS.values():
        raise ValueError("Invalid media message header")
    payload = data[HEADER.size:]
    _validate_ts(payload)
    camera = next(name for name, value in CAMERAS.items() if value == camera_id)
    return str(uuid.UUID(bytes=session)), camera, payload
