import importlib.util
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('telemetry_fields', ROOT / 'telemetry_fields.py')
fields = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fields)


class HvemObservationTests(unittest.TestCase):
    def test_valid_samples_keep_zero_and_use_latest(self):
        result = fields.decode_optional({'HVEM_02': {'HVEM_IstLeistungNA': [100.0, 450.0],
                                                     'HVEM_Leistung_Klima_Vorgabe': [0.0]}})
        self.assertEqual(result['hv_aux_power_w'], 450.0)
        self.assertEqual(result['climate_power_request_w'], 0.0)

    def test_init_error_and_missing_are_not_values(self):
        result = fields.decode_optional({'HVEM_02': {'HVEM_IstLeistungNA': [25500.0],
                                                     'HVEM_Leistung_Klima_Vorgabe': [12700.0]}})
        self.assertNotIn('hv_aux_power_w', result)
        self.assertNotIn('climate_power_request_w', result)
        self.assertEqual(fields.decode_optional({}), {})
        self.assertEqual(fields.decode_optional({'HVEM_02': {}}), {})

    def test_limits_are_inclusive(self):
        result = fields.decode_optional({'HVEM_02': {'HVEM_IstLeistungNA': [25450.0],
                                                     'HVEM_Leistung_Klima_Vorgabe': [12650.0]}})
        self.assertEqual(result['hv_aux_power_w'], 25450.0)
        self.assertEqual(result['climate_power_request_w'], 12650.0)


if __name__ == '__main__':
    unittest.main()
