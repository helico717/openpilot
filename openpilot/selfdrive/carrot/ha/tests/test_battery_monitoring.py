import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module
fields = load('battery_fields', 'telemetry_fields.py')
engine = load('battery_engine', 'engine.py')

class BatteryMonitoringTests(unittest.TestCase):
    def test_recorded_frame_extrema_and_same_frame_delta(self):
        result = fields.decode_battery_monitoring(0x16A954A6, bytes.fromhex('ec06229590558bb4'))
        self.assertEqual(result['battery_max_temperature_c'], 34.5)
        self.assertEqual(result['battery_min_temperature_c'], 32)
        self.assertEqual(result['battery_cell_max_voltage_v'], 3.901)
        self.assertEqual(result['battery_cell_min_voltage_v'], 3.888)
        self.assertEqual(result['battery_cell_voltage_delta_mv'], 13)
        self.assertEqual(fields.decode_battery_monitoring(0x1A5555B2, bytes.fromhex('0020d1873e000000')), {'battery_charge_temperature_status': 'optimal'})

    def test_unknown_and_init_are_not_numeric_measurements(self):
        self.assertEqual(fields.decode_battery_monitoring(0x16A954A6, b'\0'*7), {})
        self.assertEqual(fields.decode_battery_monitoring(0x14a, b'\0'*8), {})
        b=bytearray.fromhex('ec06229590558bb4');b[3]=b[4]=254
        self.assertTrue(all(v is None for v in fields.decode_battery_monitoring(0x16A954A6,b).values()))
        b=bytearray.fromhex('ec06229590558bb4');b[5]=255;b[6]|=15
        r=fields.decode_battery_monitoring(0x16A954A6,b)
        self.assertIsNone(r['battery_cell_max_voltage_v']);self.assertIsNone(r['battery_cell_voltage_delta_mv'])
        for code in (0,4,5,6,7):
            self.assertIsNone(fields.decode_battery_monitoring(0x1A5555B2,(code<<15).to_bytes(8,'little'))['battery_charge_temperature_status'])

    def test_timestamps_invalid_clearing_and_old_response_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            store=engine.Store(Path(d)/'state.db');e=engine.Engine(store,'test');k='battery_max_temperature_c';now=1800000000
            def sample(v,t):return {k:v,'_battery_can_measured_at':{k:t}}
            e.tick(now,False,sampled=sample(35,now-4))
            self.assertEqual(e.s['field_measured_at'][k],engine.stamp(now-4))
            self.assertNotIn('_battery_can_measured_at',e.s['vehicle'])
            e.tick(now+1,False,sampled=sample(30,now-5));self.assertEqual(e.s['vehicle'][k],35)
            e.tick(now+2,False,sampled=sample(None,now+1));self.assertIsNone(e.s['vehicle'][k])
            measured=e.s['field_measured_at'][k]
            e.tick(now+3,False,sampled={});self.assertEqual(e.s['field_measured_at'][k],measured)
            e.tick(now+4,False,sampled=sample(90,now+5));self.assertIsNone(e.s['vehicle'][k])
            e.tick(now+5,False)  # state is saved on the existing five-second cadence
            self.assertEqual(engine.Engine(store,'test').s['field_measured_at'][k],measured)
