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
