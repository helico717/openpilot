"""Semantic payload/feedback/guard checks, no vehicle access."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('tm01_runner',Path(__file__).with_name('tm01_trial.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Sm:
  valid={'pandaStates':True};recv_time={'pandaStates':100.};updated={'carState':False}
  def __init__(self):
    h=NS(busOff=False,errorWarning=False,errorPassive=False)
    self.p=NS(pandaType='cuatro',ignitionLine=False,ignitionCan=False,controlsAllowed=False,
              faults=[],heartbeatLost=False,safetyModel=NS(raw=19),canState0=h)
  def __getitem__(self,key):return [self.p] if key=='pandaStates' else NS(gearShifter='park',vEgo=0.)

class Tests(unittest.TestCase):
  def test_payload_is_exclusively_request_with_init_signature(self):
    self.assertEqual(int.from_bytes(m.payload('lock'),'little'),1<<49)
    self.assertEqual(int.from_bytes(m.payload('unlock'),'little'),1<<50)
    with self.assertRaises(ValueError):m.payload('wake')
  def test_lock_feedback_requires_availability_and_actual_external_state(self):
    self.assertIsNone(m.lock_observation(bytes(8)))
    self.assertIsNone(m.lock_observation(bytes(7)))
    self.assertIs(m.lock_observation(((1<<54)|(1<<17)).to_bytes(8,'little')),True)
    self.assertIs(m.lock_observation(((1<<54)|(1<<19)).to_bytes(8,'little')),False)
  def test_guards_fail_before_transmit_and_receive_phase_allows_error_diagnosis(self):
    sm=Sm()
    with patch.object(m.time,'monotonic',return_value=100.5),patch.object(m.Path,'read_text',return_value='0'):
      self.assertIs(m.require_panda(sm,0,{19}),sm.p)
      for key,value in (('ignitionCan',True),('ignitionLine',True),('controlsAllowed',True),
                        ('faults',[1]),('heartbeatLost',True),('pandaType','other')):
        old=getattr(sm.p,key);setattr(sm.p,key,value)
        with self.assertRaises(RuntimeError):m.require_panda(sm,0,{19})
        setattr(sm.p,key,old)
      sm.p.canState0.errorPassive=True
      with self.assertRaises(RuntimeError):m.require_panda(sm,0,{19})
      self.assertIs(m.require_panda(sm,0,{19},check_bus=False),sm.p)
    with patch.object(m.time,'monotonic',return_value=102.):
      with self.assertRaises(RuntimeError):m.require_panda(sm,0,{19})

if __name__=='__main__':unittest.main()
