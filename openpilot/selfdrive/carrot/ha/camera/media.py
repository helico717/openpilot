"""H.264 Annex-B NAL unit processing and frame packet assembly.

No external C-extensions (av/ffmpeg) required. Pure Python and zero-copy slicing.
"""
from .protocol import encode_frame, FLAG_KEY


class NalFrameAssembler:
    """Combines encoder SPS/PPS header and slice NAL data into wire frames."""

    def __init__(self, camera_name):
        self.camera_name = camera_name
        self.last_timestamp_us = 0

    def process(self, header, data, timestamp_ns, is_key=False):
        """Processes one encoder packet into a WLV1 wire frame.

        Args:
            header: bytes containing SPS/PPS parameter sets (non-empty on keyframes).
            data: bytes containing video slice NAL units.
            timestamp_ns: sensor start-of-frame timestamp in nanoseconds.
            is_key: boolean indicating keyframe. Header presence also marks keyframe.

        Returns:
            bytes: serialized WLV1 frame ready for transmission, or empty bytes.
        """
        if not data and not header:
            return b""

        is_keyframe = bool(is_key or header)
        payload = (header + data) if header else data
        timestamp_us = timestamp_ns // 1000

        self.last_timestamp_us = timestamp_us
        return encode_frame(self.camera_name, payload, is_key=is_keyframe, timestamp_us=timestamp_us)
