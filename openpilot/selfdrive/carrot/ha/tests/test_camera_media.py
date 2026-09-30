"""Tests for pure-Python WLV1 wire protocol and NalFrameAssembler."""
import unittest

from openpilot.selfdrive.carrot.ha.camera import media, protocol


class Wlv1ProtocolTests(unittest.TestCase):
    def test_wlv1_header_serialization_and_unpacking(self):
        payload = b"\x00\x00\x00\x01\x67\x42\x00\x1f\x00\x00\x00\x01\x65\x88\x84"
        timestamp_us = 1_700_000_123_456
        wire = protocol.encode_frame("wide", payload, is_key=True, timestamp_us=timestamp_us)

        self.assertEqual(len(wire), protocol.HEADER_SIZE + len(payload))
        self.assertEqual(wire[:4], b"WLV1")

        decoded = protocol.decode_frame(wire)
        self.assertEqual(decoded["frame_type"], protocol.FRAME_WIDE)
        self.assertEqual(decoded["camera"], "wide")
        self.assertTrue(decoded["is_key"])
        self.assertEqual(decoded["timestamp_us"], timestamp_us)
        self.assertEqual(decoded["payload"], payload)

    def test_frame_types_match_myid4_specification(self):
        # MyID4 spec: 0=Metadata, 1=Wide, 2=Driver, 3=Status, 4=Road
        self.assertEqual(protocol.FRAME_METADATA, 0)
        self.assertEqual(protocol.FRAME_WIDE, 1)
        self.assertEqual(protocol.FRAME_DRIVER, 2)
        self.assertEqual(protocol.FRAME_STATUS, 3)
        self.assertEqual(protocol.FRAME_ROAD, 4)

    def test_delta_frame_flag_is_zero(self):
        wire = protocol.encode_frame("driver", b"\x00\x00\x00\x01\x41\x9a", is_key=False, timestamp_us=5000)
        decoded = protocol.decode_frame(wire)
        self.assertEqual(decoded["camera"], "driver")
        self.assertFalse(decoded["is_key"])
        self.assertEqual(decoded["timestamp_us"], 5000)

    def test_invalid_magic_raises_error(self):
        bad_wire = b"XXXX" + b"\x00" * 20 + b"data"
        with self.assertRaises(ValueError):
            protocol.decode_frame(bad_wire)


class NalFrameAssemblerTests(unittest.TestCase):
    def setUp(self):
        self.assembler = media.NalFrameAssembler("wide")

    def test_keyframe_prepends_sps_pps_header(self):
        header = b"\x00\x00\x00\x01\x67\x42\x00\x1f"
        data = b"\x00\x00\x00\x01\x65\x88\x84"
        timestamp_ns = 2_000_000_000

        wire = self.assembler.process(header, data, timestamp_ns, is_key=True)
        decoded = protocol.decode_frame(wire)

        self.assertTrue(decoded["is_key"])
        self.assertEqual(decoded["timestamp_us"], 2_000_000)  # ns -> us
        self.assertEqual(decoded["payload"], header + data)

    def test_delta_frame_without_header(self):
        data = b"\x00\x00\x00\x01\x41\x9a"
        timestamp_ns = 2_033_333_000

        wire = self.assembler.process(b"", data, timestamp_ns, is_key=False)
        decoded = protocol.decode_frame(wire)

        self.assertFalse(decoded["is_key"])
        self.assertEqual(decoded["timestamp_us"], 2_033_333)
        self.assertEqual(decoded["payload"], data)

    def test_empty_packet_returns_empty_bytes(self):
        wire = self.assembler.process(b"", b"", 1000)
        self.assertEqual(wire, b"")
