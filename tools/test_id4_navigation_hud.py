"""Desktop regression: execute production HUD logic without native CAN/cereal bindings.

Only imports/hardware initialization are replaced; controller update, HUD packer values,
and controls navigation forwarding execute from the actual production AST.
"""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
VW = ROOT / "opendbc_repo/opendbc/car/volkswagen"
CV = NS(MS_TO_KPH=3.6, KPH_TO_MS=1 / 3.6)
FLAGS = NS(MEB=1, PQ=2, STOCK_HCA_PRESENT=4, STOCK_KLR_PRESENT=8, STOCK_EA_PRESENT=16)


def load_source(path, namespace, classes=False):
  tree = ast.parse(path.read_text(encoding="utf-8"))
  tree.body = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.Assign)) or
               (classes and isinstance(n, ast.ClassDef))]
  exec(compile(tree, str(path), "exec"), namespace)
  return NS(**namespace)


UTILS = load_source(VW / "mebutils.py", {"CV": CV})
CAN = load_source(VW / "mebcan.py", {"CV": CV, "VolkswagenFlags": FLAGS,
                                   "map_speed_to_acc_tempolimit": UTILS.map_speed_to_acc_tempolimit})
ENUM = NS(steerRequired=1, ldw=2, stopping=1, starting=2, pid=3)
STRUCTS = NS(CarState=NS(GearShifter=NS(park="park")), CarControl=NS(HUDControl=NS(VisualAlert=ENUM), Actuators=NS(LongControlState=ENUM)))
CONTROLLER = load_source(VW / "carcontroller.py", {
  "CarControllerBase": object, "structs": STRUCTS, "VolkswagenFlags": FLAGS,
  "CV": CV, "CANBUS": NS(pt=0, cam=2), "DT_CTRL": 0.01,
}, classes=True).CarController


class Packer:
  def make_can_msg(self, name, bus, values):
    return name, bus, values


def controller_frame(enabled=False, available=True, override=False, fault=False,
                     camera=60, event_type=0, event_speed=0, hold=False, own_long=True, road=0, controller=None):
  c = controller or CONTROLLER.__new__(CONTROLLER)
  c.CP = NS(flags=FLAGS.MEB, openpilotLongitudinalControl=own_long, pcmCruise=False)
  c.CCP = NS(STEER_STEP=100, ACC_CONTROL_STEP=100, LDW_STEP=100, ACC_HUD_STEP=6)
  c.CCS = CAN
  c.frame = 6  # HUD frame, skip unrelated steering/acceleration/LDW cycles
  c.packer_pt = Packer()
  c.apply_curvature_last = 0
  if controller is None:
    c.navi_event_last = c.navi_banner_frames = c.road_limit_last = c.road_banner_frames = 0
  c.lead_limit_disp = False
  c.lead_limit_cnt = 0
  hud = NS(setSpeed=80 / 3.6, leadDistance=0, leadVisible=False, leadDistanceBars=2,
           roadSpeedLimit=road, naviSpeedLimit=camera, naviEventType=event_type, naviEventSpeed=event_speed, leadLimiting=False)
  cc = NS(enabled=enabled, latActive=False, hudControl=hud, cruiseControl=NS(override=override),
          actuators=NS(as_builder=lambda: NS()))
  cs = NS(out=NS(gasPressed=False, accFaulted=fault, cruiseState=NS(available=available), vEgo=20, gearShifter="drive"),
          esp_hold_confirmation=hold, gra_stock_values={"COUNTER": 0})
  _, messages = c.update(cc, cs, 0)
  return [values for name, _, values in messages if name == "MEB_ACC_01"]


def forwarded_camera(alive=True, valid=True, active=2, kind=1, speed=60, return_hud=False):
  path = ROOT / "openpilot/selfdrive/controls/controlsd.py"
  tree = ast.parse(path.read_text(encoding="utf-8"))
  cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Controls")
  method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "publish")
  block = next(n for n in method.body if isinstance(n, ast.If) and isinstance(n.test, ast.Attribute)
               and n.test.attr == "is_vw_meb" and any(isinstance(x, ast.Assign) and
               any(isinstance(t, ast.Name) and t.id == "carrot_man" for t in x.targets) for x in n.body))
  # Execute the real forwarding prefix through naviSpeedLimit assignment.
  end = next(i for i, n in enumerate(block.body) if isinstance(n, ast.Assign) and
             any(isinstance(t, ast.Attribute) and t.attr == "naviSpeedLimit" for t in n.targets))
  module = ast.Module(body=block.body[:end + 1], type_ignores=[])
  class SM(dict):
    pass
  sm = SM(carrotMan=NS(activeCarrot=active, xSpdType=kind, xSpdLimit=speed, clusterRoadLimitKph=60,
                       clusterEnforcementKph=speed if active >= 2 and kind >= 0 and kind != 22 else 0))
  sm.alive, sm.valid = {"carrotMan": alive}, {"carrotMan": valid}
  hud = NS()
  exec(compile(module, str(path), "exec"), {"self": NS(sm=sm), "hudControl": hud})
  return hud if return_hud else hud.naviSpeedLimit


class TestId4NavigationHud(unittest.TestCase):
  def test_camera_in_every_acc_state_preserves_real_engagement(self):
    for enabled, available, override, fault, expected in [
      (False, False, False, False, 0), (False, True, False, False, 2),
      (True, True, False, False, 3), (True, True, True, False, 4),
      (False, True, False, True, 6),
    ]:
      with self.subTest(status=expected):
        v = controller_frame(enabled, available, override, fault)[0]
        self.assertEqual(v["ACC_Status_ACC"], expected)
        self.assertEqual(v["ACC_Enabled"], int(expected in (3, 4)))
        self.assertEqual(v["ACC_Events"], 4)
        self.assertEqual(v["ACC_Tempolimit"], 13)  # 60 km/h DBC enumeration
        self.assertAlmostEqual(v["ACC_Event_Wunschgeschw"], 60)
        self.assertEqual(v["ACC_Akustischer_Fahrerhinweis"], 0)

  def test_camera_removal_clears_inactive_banner_and_speed(self):
    for available in (False, True):
      v = controller_frame(available=available, camera=0)[0]
      self.assertEqual((v["ACC_Events"], v["ACC_Tempolimit"], v["ACC_Event_Wunschgeschw"]), (0, 0, 0))

  def test_other_events_still_require_engagement(self):
    for kind, speed in [(1, 40), (2, 30), (3, 60), (4, 30), (5, 0), (8, 60)]:
      with self.subTest(kind=kind):
        v = controller_frame(camera=0, event_type=kind, event_speed=speed)[0]
        self.assertEqual((v["ACC_Events"], v["ACC_Tempolimit"]), (0, 0))
    self.assertEqual(controller_frame(enabled=True, camera=0, event_type=8, event_speed=60, road=60)[0]["ACC_Events"], 5)
    self.assertEqual(controller_frame(enabled=True, camera=0, event_type=1, event_speed=40)[0]["ACC_Events"], 7)

  def test_camera_preempts_hold_and_turn(self):
    v = controller_frame(enabled=True, hold=True, event_type=2, event_speed=30)[0]
    self.assertEqual(v["ACC_Events"], 4)

  def test_stock_longitudinal_hud_is_not_taken_over(self):
    self.assertEqual(controller_frame(own_long=False), [])

  def test_fresh_navigation_only_and_bump_excluded(self):
    self.assertEqual(forwarded_camera(), 60)
    self.assertEqual(forwarded_camera(kind=4), 60)  # section control
    for args in ({"alive": False}, {"valid": False}, {"active": 0}, {"active": 1},
                 {"kind": -1}, {"kind": 22}, {"speed": 0}):
      with self.subTest(args=args):
        self.assertEqual(forwarded_camera(**args), 0)


if __name__ == "__main__":
  unittest.main()
