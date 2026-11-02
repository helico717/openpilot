"""Real pinned IQ CAN parser and schemas, synthetic receive-only frames; no hardware.

IQ_HA_CAN_PACKAGE_ROOT points to the public iqdbc export. Params is replaced only
for unrelated brand checksum imports; the real VW DBC/parser/packer are exercised.
Transport and clocks are synthetic, not real vehicle lifecycle validation.
"""
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]


@unittest.skipUnless(os.environ.get('IQ_HA_CAN_PACKAGE_ROOT'), 'public IQ CAN runtime not supplied')
class IQCANContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path[:0] = [os.environ['IQ_HA_CAN_PACKAGE_ROOT'], str(ROOT)]
        params = types.ModuleType('iqpilot.common.params')
        class ReadOnlyParams:
            def get_bool(self, key):
                return False
        params.Params = ReadOnlyParams
        cls.patch = patch.dict(sys.modules, {params.__name__: params})
        cls.patch.start()
        from iqdbc.can.parser import CANParser
        from iqdbc.can.packer import CANPacker
        cls.parser, cls.packer = staticmethod(CANParser), staticmethod(CANPacker)
        cls.dbc = str(ROOT / 'iqpilot/selfdrive/carrot/ha/dbc/vw_meb.dbc')
        from iqpilot import cereal
        cls.cereal = cereal
        cls.messaging = types.ModuleType('iqpilot.cereal.messaging')
        spec = importlib.util.spec_from_file_location('isolated_ha_telemetry',
            ROOT / 'iqpilot/selfdrive/carrot/ha/wayon_vehicle_telemetry.py')
        cls.telemetry = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(ROOT / 'iqpilot/selfdrive/carrot/ha'))
        with patch.dict(sys.modules, {'iqpilot.cereal.messaging': cls.messaging}), patch.object(cereal, 'messaging', cls.messaging, create=True):
            spec.loader.exec_module(cls.telemetry)

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()

    def test_real_parser_to_ha_values_on_both_buses(self):
        expected = {'battery_wh': 48000., 'odometer_km': 12345., 'outside_temp_c': 21.5,
                    'hv_voltage': 369.1, 'measured_capacity_wh': 66442.}
        for bus in (0, 1):
            with self.subTest(bus=bus):
                packer = self.packer(self.dbc)
                values = [('Motor_16', {'MO_Energieinhalt_BMS': 48000}),
                          ('HVEM_02', {'HVEM_Nutzbare_Energie': 48000}),
                          ('MEB_HVEM_01', {'Battery_Voltage_02': 369.12}),
                          ('BMS_04', {'BMS_Kapazitaet_02': 180}),
                          ('Diagnose_01', {'KBI_Kilometerstand': 12345}),
                          ('Klima_Sensor_02', {'BCM1_Aussen_Temp_ungef': 21.5})]
                frames = [packer.make_can_msg(name, bus, v) for name, v in values]
                packet = types.SimpleNamespace(logMonoTime=1000000000, can=[
                    types.SimpleNamespace(address=a, dat=d, src=b) for a, d, b in frames])
                times = iter([0., .1, 1.])
                clock = types.SimpleNamespace(monotonic=lambda: next(times), time=lambda: 100.,
                                              clock_gettime=lambda _: 1., CLOCK_MONOTONIC=1)
                t = self.telemetry
                t._CAN_SOCK, t._OPTIONAL_PARSERS = object(), []
                self.messaging.drain_sock = lambda _: [packet]
                with patch.object(t, 'time', clock):
                    result = t.sample_vehicle_can(.5)
                for key, value in expected.items():
                    self.assertAlmostEqual(result[key], value, places=1, msg=key)

    def test_wrong_bus_is_ignored_and_energy_init_is_rejected(self):
        from telemetry_fields import decode_battery_energy
        packer = self.packer(self.dbc)
        cp = self.parser(self.dbc, [('Motor_16', 2), ('HVEM_02', 10)], 0)
        self.assertIsNone(decode_battery_energy(cp.vl_all))
        frame = packer.make_can_msg('Motor_16', 1, {'MO_Energieinhalt_BMS': 48000})
        cp.update([(1000000000, [frame])])
        self.assertIsNone(decode_battery_energy(cp.vl_all))
        bad = packer.make_can_msg('Motor_16', 0, {'MO_Energieinhalt_BMS': 102350})
        alternate = packer.make_can_msg('HVEM_02', 0, {'HVEM_Nutzbare_Energie': 48000})
        cp.update([(2000000000, [bad, alternate])])
        self.assertEqual(decode_battery_energy(cp.vl_all), 48000)

    def test_current_camera_schema(self):
        from iqpilot.cereal.services import SERVICE_LIST
        for name in ('livestreamWideRoadEncodeData', 'livestreamRoadEncodeData', 'livestreamDriverEncodeData'):
            self.assertIn(name, SERVICE_LIST)
            packet = self.cereal.log.Event.new_message()
            payload = packet.init(name)
            payload.header, payload.data = b'header', b'frame'
            payload.idx.timestampSof, payload.idx.flags = 123, 8
            with self.cereal.log.Event.from_bytes(packet.to_bytes()) as read:
                value = getattr(read, name)
                self.assertEqual(bytes(value.data), b'frame')
                self.assertEqual(value.idx.timestampSof, 123)
