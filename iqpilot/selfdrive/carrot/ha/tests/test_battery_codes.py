import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('fields',Path(__file__).resolve().parents[1]/'telemetry_fields.py')
fields=importlib.util.module_from_spec(spec);spec.loader.exec_module(fields)
class BatteryCodesTests(unittest.TestCase):
    def test_init_and_error_are_not_battery_energy(self):
        for value in [102350,102375]:
            self.assertIsNone(fields.decode_battery_energy({'Motor_16':{'MO_Energieinhalt_BMS':[value]}}))
        for value in [102250,102300,102350]:
            self.assertIsNone(fields.decode_battery_energy({'HVEM_02':{'HVEM_Nutzbare_Energie':[value]}}))
    def test_valid_fallback_and_real_energy(self):
        self.assertEqual(fields.decode_battery_energy({'Motor_16':{'MO_Energieinhalt_BMS':[102350]},'HVEM_02':{'HVEM_Nutzbare_Energie':[56000]}}),56000)
        self.assertEqual(fields.decode_battery_energy({'Motor_16':{'MO_Energieinhalt_BMS':[63975]}}),63975)
