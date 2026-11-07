"""Real schema and CAN encoding checks; no vehicle connection or transmission."""
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'opendbc_repo')]
try:
  import openpilot.common.params
except ImportError:
  # The DBC loader imports a Hyundai-only Params user; MEB encoding never uses it.
  shim = types.ModuleType('openpilot.common.params')
  shim.Params = type('UnusedParams', (), {})
  sys.modules[shim.__name__] = shim

from openpilot.cereal import car, custom
from opendbc.can.packer import CANPacker
from opendbc.can.parser import get_raw_value
from opendbc.car.volkswagen.acc_display_probe import AccDisplayProbe, PROFILES, write_json
import test_id4_navigation_hud as base


class TestEncoding(unittest.TestCase):
  def test_schema_roundtrip(self):
    source = custom.CarrotMan.new_message(clusterRoadLimitKph=60, clusterEnforcementKph=50)
    with custom.CarrotMan.from_bytes(source.to_bytes()) as restored:
      self.assertEqual((restored.clusterRoadLimitKph, restored.clusterEnforcementKph), (60, 50))
    control = car.CarControl.new_message()
    control.hudControl.roadSpeedLimit = 60
    with car.CarControl.from_bytes(control.to_bytes()) as restored:
      self.assertEqual(restored.hudControl.roadSpeedLimit, 60)

  def test_all_states_real_dbc_encoding(self):
    for dbc in ('vw_meb', 'vw_meb_2024'):
      packer = CANPacker(dbc)
      for state in (0, 2, 3, 4, 6):
        for event in (4, 5):
          with self.subTest(dbc=dbc, state=state, event=event):
            address, payload, bus = base.CAN.create_acc_hud_control(
              packer, 0, state, 80, False, 2, True, False, 0, 30, False, event, 60 / 3.6)
            self.assertEqual((address, len(payload), bus), (0x300, 48, 0))
            signals = packer.dbc.addr_to_msg[address].sigs
            self.assertEqual(get_raw_value(payload, signals['ACC_Events']), event)
            self.assertEqual(get_raw_value(payload, signals['ACC_Tempolimit']), 13)
            self.assertEqual(get_raw_value(payload, signals['ACC_Status_ACC']), state)
            self.assertEqual(get_raw_value(payload, signals['ACC_Enabled']), int(state in (3, 4)))

  def test_probe_only_changes_primary_text_bits_and_restores(self):
    for dbc in ('vw_meb', 'vw_meb_2024'):
      for profile, value in PROFILES.items():
        with self.subTest(dbc=dbc, profile=profile), tempfile.TemporaryDirectory() as directory:
          root = Path(directory)
          boot = root / 'boot'
          boot.write_text('boot')
          now = [100]
          probe = AccDisplayProbe(root, boot, lambda: now[0])
          packer = CANPacker(dbc)

          def frame(display=None):
            return base.CAN.create_acc_hud_control(packer, 0, 0, 80, False, 2, True, False,
                                                   0, 30, False, 0, 0, display_probe=display, probe_parked=True)[1]

          normal = frame()
          write_json(root / 'request.json', {'id': 'a', 'boot_id': 'boot', 'issued_ns': 100,
                                           'expires_ns': 2_000_000_100, 'profile': profile})
          candidate = frame(probe)
          mask = ((1 << 6) - 1) << 114
          delta = int.from_bytes(normal, 'little') ^ int.from_bytes(candidate, 'little')
          self.assertEqual(delta & ~mask, 0)
          self.assertNotEqual(delta, 0)
          self.assertEqual((int.from_bytes(candidate, 'little') >> 114) & 63, value)
          now[0] = 2_000_000_100
          self.assertEqual(frame(probe), normal)
          self.assertEqual(probe.status['phase'], 'expired_normal_packed')


if __name__ == '__main__':
  unittest.main()
