import io
import tempfile
from pathlib import Path
from fractions import Fraction
import unittest
import av
from openpilot.selfdrive.carrot.ha.camera import media

def encoded_frames():
    codec = av.CodecContext.create('libx264', 'w')
    codec.width, codec.height, codec.pix_fmt = 320, 180, 'yuv420p'
    codec.time_base = Fraction(1, 20)
    codec.framerate = Fraction(20, 1)
    codec.options = {'preset': 'ultrafast', 'tune': 'zerolatency',
                     'x264-params': 'keyint=10:scenecut=0:repeat-headers=1'}
    for index in range(30):
        frame = av.VideoFrame(320, 180, 'yuv420p')
        for plane in frame.planes:
            plane.update(bytes([80 + index]) * plane.buffer_size)
        frame.pts = index
        for packet in codec.encode(frame):
            data = bytes(packet)
            # Entire keyframe is a valid Annex-B bootstrap sample.
            yield data if packet.is_keyframe else b'', b'' if packet.is_keyframe else data, index * 50_000_000


class MuxTests(unittest.TestCase):
    def test_transport_stream_remuxes_to_fragmented_mp4_hls(self):
        mux = media.TransportMux()
        payload = b''.join(mux.push(*frame) for frame in encoded_frames())
        mux.close()
        payload += mux.buffer.take()
        with tempfile.TemporaryDirectory() as directory:
            playlist = Path(directory) / 'index.m3u8'
            with av.open(io.BytesIO(payload), format='mpegts') as source:
                with av.open(playlist.as_posix(), 'w', format='hls', options={
                    'hls_segment_type': 'fmp4', 'hls_time': '1', 'hls_list_size': '0',
                }) as output:
                    video = output.add_stream_from_template(source.streams.video[0])
                    for packet in source.demux(video=0):
                        if packet.dts is not None:
                            packet.stream = video
                            output.mux(packet)
            self.assertIn('#EXT-X-MAP', playlist.read_text())
            with av.open(playlist.as_posix()) as hls:
                self.assertEqual(len(list(hls.decode(video=0))), 30)

    def test_remuxed_ts_decodes_and_preserves_timing(self):
        mux = media.TransportMux()
        chunks = [mux.push(*frame) for frame in encoded_frames()]
        mux.close()
        chunks.append(mux.buffer.take())
        payload = b''.join(chunks)
        self.assertEqual(len(payload) % 188, 0)
        with av.open(io.BytesIO(payload), format='mpegts') as source:
            frames = list(source.decode(video=0))
        self.assertEqual(len(frames), 30)
        self.assertEqual((frames[0].width, frames[0].height), (320, 180))
        self.assertAlmostEqual(float(frames[-1].pts * frames[-1].time_base - frames[0].pts * frames[0].time_base), 1.45, places=2)

    def test_waits_for_header_and_rejects_backwards_time(self):
        mux = media.TransportMux()
        self.assertEqual(mux.push(b'', b'not-a-keyframe', 1), b'')
        first = next(encoded_frames())
        mux.push(*first)
        with self.assertRaises(ValueError):
            mux.push(*first)
        mux.close()

    def test_reader_joining_mid_gop_can_decode_at_next_keyframe(self):
        mux = media.TransportMux()
        chunks = [mux.push(*frame) for frame in encoded_frames()]
        mux.close()
        # A second HA camera can join while the shared capture is already
        # running. It does not receive the first stream header/GOP.
        payload = b''.join(chunks[15:]) + mux.buffer.take()
        decoded = []
        started = False
        with av.open(io.BytesIO(payload), format='mpegts') as source:
            for packet in source.demux(video=0):
                started = started or packet.is_keyframe
                if started:
                    decoded.extend(packet.decode())
        self.assertEqual(len(decoded), 10)

    def test_synchronized_multi_camera_origin_preserves_relative_timing(self):
        common_origin = 1_000_000_000
        mux1 = media.TransportMux()
        mux2 = media.TransportMux()
        frames1 = list(encoded_frames())
        frames2 = list(encoded_frames())
        # Stream 1 starts at T0 (1_000_000_000)
        h1, d1, _ = frames1[0]
        mux1.push(h1, d1, common_origin, origin_ns=common_origin)
        # Stream 2 starts 200ms later at T0 + 200ms (1_200_000_000)
        h2, d2, _ = frames2[0]
        mux2.push(h2, d2, common_origin + 200_000_000, origin_ns=common_origin)
        # Mux 1 PTS at T0 should be 0
        self.assertEqual(mux1.last_pts, 0)
        # Mux 2 PTS at T0+200ms should be 200ms * 90000 / 1e9 = 18000 (not reset to 0!)
        self.assertEqual(mux2.last_pts, 18000)
        mux1.close()
        mux2.close()

    def test_camera_timestamp_before_origin_clamps_and_increases_monotonically(self):
        common_origin = 1_000_000_000
        mux = media.TransportMux()
        frames = list(encoded_frames())
        # Frame 0 arrives with timestamp 50ms before common_origin
        h0, d0, _ = frames[0]
        mux.push(h0, d0, common_origin - 50_000_000, origin_ns=common_origin)
        self.assertEqual(mux.last_pts, 0)
        # Frame 1 arrives with timestamp 10ms after common_origin
        h1, d1, _ = frames[1]
        mux.push(h1, d1, common_origin + 10_000_000, origin_ns=common_origin)
        self.assertEqual(mux.last_pts, 900)
        mux.close()

