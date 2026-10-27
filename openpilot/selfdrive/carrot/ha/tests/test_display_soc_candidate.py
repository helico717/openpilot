import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module
fields = load('display_soc_fields', 'telemetry_fields.py')
engine = load('display_soc_engine', 'engine.py')
KEY = 'display_soc_candidate_percent'

def frame(raw):
    payload = bytearray(32); payload[19] = raw
    return bytes(payload)

class DisplaySocCandidateTests(unittest.TestCase):
    def test_bus1_32byte_byte19_half_percent(self):
        self.assertIn(KEY, fields.BATTERY_MONITOR_KEYS)
        for raw, expected in ((0, 0), (5, 2.5), (61, 30.5), (112, 56), (200, 100)):
            self.assertEqual(fields.decode_display_soc_candidate(frame(raw), 1), {KEY: expected})

    def test_init_and_out_of_range_clear_value(self):
        for raw in (201, 253, 254, 255):
            self.assertEqual(fields.decode_display_soc_candidate(frame(raw), 1), {KEY: None})

    def test_other_bus_or_length_ignored(self):
        self.assertEqual(fields.decode_display_soc_candidate(frame(61), 0), {})
        self.assertEqual(fields.decode_display_soc_candidate(bytes(8), 1), {})
        self.assertEqual(fields.decode_battery_monitoring(0x14A, frame(61)), {})

    def _engine(self, d):
        return engine.Engine(engine.Store(Path(d) / 'state.sqlite3'), 'car')

    def test_telemetry_keeps_wh_soc_and_adds_candidate_with_measured_time(self):
        with tempfile.TemporaryDirectory() as d:
            e = self._engine(d); now = 1800000000
            events = e.tick(now, False, sampled={'battery_wh': 39000, KEY: 60.5, '_battery_can_measured_at': {KEY: now - 3}},
                            motion={'gear': 'park', 'speed_mps': 0})
            vehicle = next(body for path, body in events if path == '/api/telemetry')['vehicle']
            self.assertEqual(vehicle[KEY], 60.5)
            self.assertEqual(vehicle['field_measured_at'][KEY], engine.stamp(now - 3))
            self.assertAlmostEqual(vehicle['soc_percent'], 39000 / 780)  # unchanged Wh/780 meaning
            self.assertEqual(vehicle['battery_wh'], 39000)

    def test_trip_boundaries_carry_candidate_without_affecting_completeness(self):
        with tempfile.TemporaryDirectory() as d:
            e = self._engine(d); base = 1800000000
            def tick(t, wh, onroad, display=None, age=1):
                sampled = {'battery_wh': wh}
                if display is not None:
                    sampled.update({KEY: display, '_battery_can_measured_at': {KEY: base + t - age}})
                return e.tick(base + t, onroad, sampled=sampled,
                              motion={'gear': 'drive' if onroad else 'park', 'speed_mps': 10 if onroad else 0})
            tick(0, 50000, False, 64)
            tick(1, 50000, True, 64)
            for t in range(2, 22):
                tick(t, 50000 - (t - 1) * 10, True, None if t % 2 else 63.5)
            trip = next(body for path, body in tick(22, 49800, False, 63, age=500) if path == '/api/trips')
            m = trip['tripMeasurements']
            self.assertTrue(m['complete'])
            self.assertEqual(m['start'][KEY], 64)
            self.assertEqual(m['start']['display_soc_candidate_measured_at'], engine.stamp(base))
            self.assertEqual(m['start']['soc_percent'], None)
            self.assertEqual(m['start']['battery_wh'], 50000)
            # Stale (>180s) candidate at the end is reported as unknown, not reused.
            self.assertIsNone(m['end'][KEY])
            self.assertIsNone(m['end']['display_soc_candidate_measured_at'])
            self.assertEqual(m['end']['battery_wh'], 49800)

if __name__ == '__main__':
    unittest.main()
