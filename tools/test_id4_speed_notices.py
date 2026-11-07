"""Production-code regressions for information-only road/enforcement display."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest

import test_id4_navigation_hud as base

ROOT = Path(__file__).resolve().parents[1]


def module(name, relative):
  spec = importlib.util.spec_from_file_location(name, ROOT / relative)
  result = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(result)
  return result


signs = module('navigation_hud', 'openpilot/selfdrive/carrot/navigation_hud.py')
probe = module('acc_display_probe', 'opendbc_repo/opendbc/car/volkswagen/acc_display_probe.py')


class TestNotices(unittest.TestCase):
  def controller(self):
    c = base.CONTROLLER.__new__(base.CONTROLLER)
    c.navi_event_last = c.navi_banner_frames = c.road_limit_last = c.road_banner_frames = 0
    return c

  def frame(self, c, **kwargs):
    return base.controller_frame(camera=0, controller=c, **kwargs)[0]

  def test_forwarding_clears_stale_road_and_enforcement(self):
    for alive, valid in ((True, True), (False, True), (True, False)):
      hud = base.forwarded_camera(alive=alive, valid=valid, return_hud=True)
      self.assertEqual((hud.roadSpeedLimit, hud.naviSpeedLimit), (60, 60) if alive and valid else (0, 0))

  def test_road_in_all_normal_acc_states(self):
    for enabled, available, override, status in ((False, False, False, 0), (False, True, False, 2),
                                                (True, True, False, 3), (True, True, True, 4)):
      v = self.frame(self.controller(), road=60, enabled=enabled, available=available, override=override)
      self.assertEqual((v['ACC_Events'], v['ACC_Tempolimit'], v['ACC_Status_ACC']), (5, 13, status))
      self.assertEqual(v['ACC_Enabled'], int(enabled))

  def test_road_lifetime_repeat_change_and_invalid_recovery(self):
    c = self.controller()
    self.assertEqual(sum(self.frame(c, road=60)['ACC_Events'] == 5 for _ in range(60)), 40)
    self.assertEqual(self.frame(c, road=60)['Lead_Brightness'], 0)
    for road in (80, 60):
      self.assertEqual(self.frame(c, road=road)['ACC_Events'], 5)
    self.frame(c, road=0)
    self.assertEqual(self.frame(c, road=60)['ACC_Events'], 5)

  def test_camera_priority_and_no_old_road_replay(self):
    c = self.controller()
    for _ in range(45):
      v = base.controller_frame(controller=c, camera=50, road=60)[0]
      self.assertEqual((v['ACC_Events'], v['ACC_Tempolimit']), (4, 11))
    self.assertEqual(self.frame(c, road=60)['ACC_Events'], 0)

  def test_fault_does_not_create_road_notice(self):
    self.assertEqual(self.frame(self.controller(), road=60, fault=True)['ACC_Events'], 0)

  def test_default_and_expired_legacy_values_do_not_announce(self):
    s = NS(carrot_navi_active=False, active_count=80, active_kisa_count=0,
           cluster_legacy_road=0, cluster_legacy_road_at=0, nSdiType=-1)
    self.assertEqual(signs.cluster_limits(s, 1), (0, 0))
    s.cluster_legacy_road = 60
    self.assertEqual(signs.cluster_limits(s, 21), (0, 0))
    self.assertEqual(signs.cluster_limits(s, 1), (60, 0))

  def test_legacy_enforcement_raw_and_section(self):
    s = NS(carrot_navi_active=False, active_count=80, active_kisa_count=0,
           cluster_legacy_road=60, cluster_legacy_road_at=0, nSdiType=1,
           nSdiDist=100, nSdiSpeedLimit=50, nSdiBlockType=-1)
    self.assertEqual(signs.cluster_limits(s, 1), (60, 50))
    s.nSdiType = 22
    self.assertEqual(signs.cluster_limits(s, 1), (60, 0))
    s.nSdiType, s.nSdiBlockType, s.nSdiBlockDist, s.nSdiBlockSpeed = 4, 2, 1000, 80
    self.assertEqual(signs.cluster_limits(s, 1), (60, 80))
    s.nSdiType = 50
    self.assertEqual(signs.cluster_limits(s, 1), (60, 0))

  def test_new_navi_road_independent_of_control_and_offroute(self):
    speed = NS(road_limit_kph=60, section_active=False, sdi_present=False)
    navi = NS(off_route=False, speed=speed)
    s = NS(carrot_navi_active=True, carrot_navi_control=navi)
    self.assertEqual(signs.cluster_limits(s, 1), (60, 0))
    speed.section_active, speed.section_speed_limit_kph = True, 50
    self.assertEqual(signs.cluster_limits(s, 1), (60, 50))
    navi.off_route = True
    self.assertEqual(signs.cluster_limits(s, 1), (0, 0))

  def test_probe_changes_text_only_and_restores_on_expiry(self):
    for profile, text in probe.PROFILES.items():
      with self.subTest(profile=profile), TemporaryDirectory() as directory:
        root = Path(directory)
        boot = root / 'boot'
        boot.write_text('boot')
        now = [1_000_000_000]
        p = probe.AccDisplayProbe(root, boot, lambda: now[0])
        probe.write_json(root / 'request.json', {'id': 'a', 'boot_id': 'boot', 'issued_ns': now[0],
                                               'expires_ns': now[0] + 2_000_000_000, 'profile': profile})
        values = {'ACC_Status_ACC': 0, 'ACC_Events': 0, 'ACC_Enabled': 0, 'ACC_Tempolimit': 0}
        self.assertEqual(p.apply(values, True), {**values, 'ACC_Texte_Primaeranz_02': text})
        p.packed((0x300, bytes(48), 0))
        self.assertEqual(p.status['phase'], 'candidate_packed')
        now[0] += 2_000_000_000
        self.assertEqual(p.apply(values, True), values)
        p.packed((0x300, bytes(48), 0))
        self.assertEqual(p.status['phase'], 'expired_normal_packed')

  def test_probe_cancel_and_malformed_profile(self):
    with TemporaryDirectory() as directory:
      root = Path(directory)
      boot = root / 'boot'
      boot.write_text('boot')
      p = probe.AccDisplayProbe(root, boot, lambda: 10)
      values = {'ACC_Status_ACC': 0, 'ACC_Events': 0}
      request = {'id': 'a', 'boot_id': 'boot', 'issued_ns': 1, 'expires_ns': 100, 'profile': []}
      probe.write_json(root / 'request.json', request)
      self.assertEqual(p.apply(values, True), values)
      request.update(id='b', profile='overspeed')
      probe.write_json(root / 'request.json', request)
      self.assertIn('ACC_Texte_Primaeranz_02', p.apply(values, True))
      request.update(id='c', cancel=True)
      probe.write_json(root / 'request.json', request)
      self.assertEqual(p.apply(values, True), values)
      self.assertIsNone(p.active)

  def test_probe_rejects_reboot_moving_or_existing_event(self):
    for parked, event, request_boot in ((False, 0, 'boot'), (True, 4, 'boot'), (True, 0, 'old')):
      with TemporaryDirectory() as directory:
        root = Path(directory)
        boot = root / 'boot'
        boot.write_text('boot')
        p = probe.AccDisplayProbe(root, boot, lambda: 10)
        probe.write_json(root / 'request.json', {'id': 'a', 'boot_id': request_boot, 'issued_ns': 1,
                                               'expires_ns': 100, 'profile': 'overspeed'})
        values = {'ACC_Status_ACC': 0, 'ACC_Events': event}
        self.assertEqual(p.apply(values, parked), values)
        self.assertIsNone(p.active)


if __name__ == '__main__':
  unittest.main()
