"""H.264 Annex-B to MPEG-TS remuxing; no pixel decoding or re-encoding."""
from fractions import Fraction
import io

import av


class Buffer:
    def __init__(self):
        self.data = bytearray()

    def write(self, data):
        self.data.extend(data)
        return len(data)

    def writable(self):
        return True

    def take(self):
        data = bytes(self.data)
        self.data.clear()
        return data


class TransportMux:
    def __init__(self, origin_ns=None):
        self.buffer = Buffer()
        self.container = None
        self.stream = None
        self.origin_ns = origin_ns
        self.last_pts = -1

    def push(self, header, data, timestamp_ns, origin_ns=None):
        if self.container is None:
            if not header:
                return b''  # Wait for SPS/PPS + keyframe.
            with av.open(io.BytesIO(header + data), format='h264') as source:
                self.container = av.open(self.buffer, 'w', format='mpegts', options={
                    'mpegts_flags': 'resend_headers', 'flush_packets': '1'})
                self.stream = self.container.add_stream_from_template(source.streams.video[0])
                self.stream.time_base = Fraction(1, 90000)
            if self.origin_ns is None:
                self.origin_ns = origin_ns if origin_ns is not None else timestamp_ns
        origin = self.origin_ns if origin_ns is None else origin_ns
        pts = (timestamp_ns - origin) * 90000 // 1_000_000_000
        if pts < 0:
            if self.last_pts < 0:
                pts = 0
            else:
                pts = self.last_pts + 1
        elif pts <= self.last_pts:
            raise ValueError('Non-monotonic camera timestamp')
        self.last_pts = pts
        packet = av.Packet(header + data)
        packet.pts = packet.dts = pts
        packet.time_base = Fraction(1, 90000)
        packet.stream = self.stream
        packet.is_keyframe = bool(header)
        self.container.mux(packet)
        return self.buffer.take()

    def close(self):
        if self.container is not None:
            self.container.close()
            self.container = None
