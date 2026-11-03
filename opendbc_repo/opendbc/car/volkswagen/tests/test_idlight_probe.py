"""Real vw_meb packer tests; Windows-only Params import shim is unused by VW."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

try:
  import openpilot.common.params
except ImportError:
  params = types.ModuleType("openpilot.common.params")
  params.Params = type("UnusedParams", (), {})
  sys.modules[params.__name__] = params

from opendbc.can.packer import CANPacker
from opendbc.car.volkswagen import mebcan
from opendbc.car.volkswagen.idlight_probe import DisplayProbe, PROFILES, atomic_json

MASKS = {"LDW_Texte": (16, 4), "LDW_Lernmodus_links": (38, 2), "LDW_Lernmodus_rechts": (36, 2),
         "LDW_SW_Warnung_links": (14, 1), "LDW_SW_Warnung_rechts": (15, 1),
         "LDW_Warnung_links": (56, 1), "LDW_Warnung_rechts": (57, 1)}


class DisplayProbeTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.root = Path(self.tmp.name)
    self.boot = self.root / "boot"
    self.boot.write_text("boot-a")
    self.now = 100_000_000
    self.probe = DisplayProbe(self.root, self.boot, lambda: self.now)
    self.packer = CANPacker("vw_meb")
    self.hud = types.SimpleNamespace(leftLaneDepart=False, rightLaneDepart=False,
                                    leftLaneVisible=True, rightLaneVisible=True)
    self.stock = {"LDW_SW_Warnung_links": 0, "LDW_SW_Warnung_rechts": 0,
                  "LDW_Seite_DLCTLC": 1, "LDW_DLC": .3, "LDW_TLC": 1.5}

  def request(self, profile="text8", **extra):
    data = {"id": "one", "profile": profile, "boot_id": "boot-a",
            "issued_ns": self.now, "expires_ns": self.now + 1_000_000_000}
    data.update(extra)
    atomic_json(self.root / "request.json", data)

  def frame(self, probe=True, alert=0):
    return mebcan.create_lka_hud_control(self.packer, 0, self.stock, False, False, alert,
                                        self.hud, 0, self.probe if probe else None)

  def status(self):
    return json.loads((self.root / "status.json").read_text())

  def test_default_no_request_matches_original_and_writes_nothing(self):
    self.assertEqual(self.frame(), self.frame(False))
    self.assertFalse((self.root / "status.json").exists())

  def test_all_profiles_modify_only_one_field_and_restore_real_packed_frame(self):
    baseline = self.frame(False)
    for index, (profile, change) in enumerate(PROFILES.items()):
      with self.subTest(profile=profile):
        self.request(profile, id=str(index))
        message = self.frame()
        self.assertEqual((message[0], message[2], len(message[1])), (0x397, 0, 8))
        field, value = next(iter(change.items()))
        start, width = MASKS[field]
        mask = ((1 << width) - 1) << start
        before, after = (int.from_bytes(m[1], "little") for m in (baseline, message))
        self.assertEqual((before ^ after) & ~mask, 0)
        self.assertEqual((after & mask) >> start, value)
        self.assertEqual(self.status()["phase"], "candidate_packed")
        self.assertFalse(self.status()["hardware_transmission_confirmed"])
        self.now += 1_000_000_000
        self.assertEqual(self.frame(), baseline)
        self.assertEqual(self.status()["phase"], "expired_normal_packed")
        self.assertEqual(self.frame(), baseline)  # no replay of consumed request

  def test_check_acknowledges_original_frame_without_modification(self):
    self.request(observe=True, profile=None)
    self.assertEqual(self.frame(), self.frame(False))
    self.assertEqual(self.status()["phase"], "observed_normal_packed")
    self.assertEqual(self.status()["packed_frames"], 0)

  def test_cancel_restores_normal_on_next_frame(self):
    self.request(); self.frame()
    self.request(id="cancel", cancel=True)
    self.assertEqual(self.frame(), self.frame(False))
    self.assertEqual(self.status()["phase"], "cancelled_normal_packed")

  def test_real_warning_aborts_probe_without_masking_warning(self):
    self.request("left3"); self.frame()
    self.assertEqual(self.frame(alert=4), self.frame(False, alert=4))
    self.assertEqual(self.status()["phase"], "aborted_existing_warning_normal_packed")

  def test_stale_future_reboot_and_excess_duration_are_rejected(self):
    for index, extra in enumerate(({"expires_ns": self.now}, {"issued_ns": self.now + 1},
                                 {"boot_id": "old-boot"}, {"expires_ns": self.now + 3_000_000_000})):
      self.request(id=str(index), **extra)
      self.assertEqual(self.frame(), self.frame(False))
      self.assertEqual(self.status()["phase"], "rejected")

  def test_unknown_or_wrong_type_profile_is_rejected(self):
    for index, profile in enumerate(("random", {}, None)):
      self.request(profile, id=str(index))
      self.assertEqual(self.frame(), self.frame(False))
      self.assertEqual(self.status()["phase"], "rejected")

  def test_invalid_file_does_not_crash_or_modify_frame(self):
    (self.root / "request.json").write_text("broken")
    self.assertEqual(self.frame(), self.frame(False))

  def test_status_write_failure_does_not_stop_controller(self):
    from unittest.mock import patch
    self.request()
    with patch("opendbc.car.volkswagen.idlight_probe.atomic_json", side_effect=OSError("full")):
      self.assertEqual(self.frame()[0], 0x397)


if __name__ == "__main__":
  unittest.main()
