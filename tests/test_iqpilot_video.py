"""Synthetic finalized H.264 TS -> MP4 stream-copy; no vehicle recordings."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

try:
    import av
except ImportError:
    av = None

spec = importlib.util.spec_from_file_location('iq_video_adapter', Path(__file__).parents[1] / 'iqpilot/selfdrive/carrot/ha/iq_video.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


@unittest.skipIf(av is None, 'Optional IQpilot PyAV runtime is not installed')
class VideoTests(unittest.TestCase):
    def test_h264_ts_remux_preserves_source_and_decodable_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'qcamera.ts', Path(directory) / 'qcamera.mp4'
            with av.open(str(source), 'w', format='mpegts') as container:
                stream = container.add_stream('libx264', rate=20)
                stream.width = stream.height = 16
                stream.pix_fmt = 'yuv420p'
                for index in range(4):
                    frame = av.VideoFrame(16, 16, 'yuv420p')
                    for plane in frame.planes:
                        plane.update(bytes(plane.buffer_size))
                    frame.pts = index
                    for packet in stream.encode(frame):
                        container.mux(packet)
                for packet in stream.encode():
                    container.mux(packet)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            adapter.remux(source, output)
            with av.open(str(output)) as result:
                self.assertEqual(result.streams.video[0].codec_context.name, 'h264')
                self.assertEqual(len(list(result.decode(video=0))), 4)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)

    def test_existing_output_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'source.ts', Path(directory) / 'output.mp4'
            source.write_bytes(b'not a video')
            output.write_bytes(b'keep')
            with self.assertRaises(ValueError):
                adapter.remux(source, output)
            self.assertEqual(output.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
