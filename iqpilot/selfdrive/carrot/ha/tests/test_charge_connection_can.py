import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

fields = load('charge_can_fields', 'telemetry_fields.py')
engine = load('charge_can_engine', 'engine.py')

class ChargeCanTests(unittest.TestCase):
    def test_codes_preserved_per_bus_without_inventing_connection(self):
        for code in range(8):
            result = fields.decode_optional({'WBA_03': {'WBA_GE_Texte_02': [code]}}, bus=1)
            self.assertEqual(result['charge_can_plug_text_bus1'], code)
            self.assertNotIn('charge_plug_connected', result)
            self.assertNotIn('charging', result)
        self.assertEqual(fields.decode_optional({}, bus=0), {})
        self.assertEqual(fields.decode_optional({'WBA_03': {'WBA_GE_Texte_02': [float('nan')]}}, bus=0), {})

    def test_all_candidates_and_bus_isolation(self):
        vl = {message: {} for message, _, _ in fields.CHARGE_CAN_SIGNALS.values()}
        for message, signal, maximum in fields.CHARGE_CAN_SIGNALS.values():
            vl[message][signal] = [maximum]
        a = fields.decode_optional(vl, bus=0)
        b = fields.decode_optional(vl, bus=1)
        self.assertEqual(len(a), 5)
        self.assertFalse(set(a) & set(b))

    def test_engine_persists_without_refreshing_missing_can_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            store = engine.Store(Path(folder) / 'state.db')
            e = engine.Engine(store, 'test')
            key = 'charge_can_plug_text_bus1'
            e.tick(1800000000, False, sampled={key: 2, 'battery_wh': 30000})
            measured = e.s['field_measured_at'][key]
            events = e.tick(1800000061, False, sampled={'battery_wh': 30000})
            vehicle = events[-1][1]['vehicle']
            self.assertEqual(vehicle[key], 2)
            self.assertEqual(vehicle['field_measured_at'][key], measured)
            self.assertFalse(vehicle['charging'])
            restarted = engine.Engine(store, 'test')
            self.assertEqual(restarted.s['vehicle'][key], 2)

if __name__ == '__main__':
    unittest.main()
