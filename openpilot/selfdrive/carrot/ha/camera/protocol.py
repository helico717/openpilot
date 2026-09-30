"""Carrot HA camera wire protocol v2 (WLV1 frame specification).

Compatible with MyID4 low-latency WebCodecs decoding pipeline.
Binary Header: 24 bytes
  [0..3]   4s  Magic: b"WLV1"
  [4]      B   FrameType: 0=Metadata, 1=Wide, 2=Driver, 3=Status, 4=Road
  [5]      B   Flags: 0x01=Keyframe (SPS/PPS + IDR)
  [6..11]  6s  Reserved (zeros)
  [12..19] Q   Timestamp (microseconds)
  [20..23] I   PayloadSize (bytes)
  [24..]   bytes H.264 Annex-B NAL unit / JSON control payload
"""
import struct

MAGIC = b"WLV1"
HEADER_SIZE = 24
HEADER = struct.Struct("!4sBB6sQI")

FRAME_METADATA = 0
FRAME_WIDE = 1
FRAME_DRIVER = 2
FRAME_STATUS = 3
FRAME_ROAD = 4

CAMERAS = {
    "wide": FRAME_WIDE,
    "driver": FRAME_DRIVER,
    "road": FRAME_ROAD,
}
CAMERAS_BY_ID = {v: k for k, v in CAMERAS.items()}

FLAG_KEY = 0x01
MAX_PAYLOAD = 4 * 1024 * 1024  # 4MB max single frame


def encode_frame(camera_or_type, payload, is_key=False, timestamp_us=0):
    if isinstance(camera_or_type, str):
        if camera_or_type not in CAMERAS:
            raise ValueError(f"Unknown camera: {camera_or_type}")
        frame_type = CAMERAS[camera_or_type]
    elif isinstance(camera_or_type, int):
        frame_type = camera_or_type
    else:
        raise ValueError("Invalid camera or frame type")

    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError("Payload must be bytes or bytearray")

    payload_size = len(payload)
    if payload_size > MAX_PAYLOAD:
        raise ValueError(f"Payload too large: {payload_size} > {MAX_PAYLOAD}")

    flags = FLAG_KEY if is_key else 0
    header = HEADER.pack(MAGIC, frame_type, flags, b"\x00" * 6, int(timestamp_us), payload_size)
    return header + bytes(payload)


def decode_frame(data):
    if not isinstance(data, (bytes, bytearray)) or len(data) < HEADER_SIZE:
        raise ValueError("Frame too short")

    magic, frame_type, flags, _, timestamp_us, payload_size = HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ValueError(f"Invalid frame magic: {magic!r}")

    if len(data) < HEADER_SIZE + payload_size:
        raise ValueError("Incomplete frame payload")

    payload = data[HEADER_SIZE : HEADER_SIZE + payload_size]
    is_key = bool(flags & FLAG_KEY)
    camera = CAMERAS_BY_ID.get(frame_type)

    return {
        "frame_type": frame_type,
        "camera": camera,
        "is_key": is_key,
        "timestamp_us": timestamp_us,
        "payload": payload,
    }

