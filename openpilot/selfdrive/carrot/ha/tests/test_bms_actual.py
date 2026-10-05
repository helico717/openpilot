import importlib.util
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
fields=load('telemetry_fields');engine=load('engine');mode=load('charging_mode')
class ActualTests(unittest.TestCase):
 def frame(self,code=4,amps=4,volts=350):
  b=bytearray(8);b[2]=code;i=round(amps*10+16300);b[3]=i&255;b[4]=i>>8;v=round(volts*4);b[6]=(v&15)<<4;b[7]=v>>4;return bytes(b)
 def test_current_voltage_scaling_and_init(self):
  d=fields.decode_bms_actual(self.frame(),1);self.assertEqual(d['bms_power_w_bus1'],1400);self.assertEqual(d['bms_voltage_v_bus1'],350)
  self.assertIsNone(fields.decode_bms_actual(self.frame(7),1)['bms_power_w_bus1'])
  self.assertEqual(fields.decode_bms_actual(b'\0'*7,1),{})
  self.assertEqual(fields.decode_bms_actual(self.frame(),128),{})
 def test_engine_charges_without_energy_increase_then_stop_expiry_and_init(self):
  with tempfile.TemporaryDirectory() as p:
   e=engine.Engine(engine.Store(Path(p)/'db'),'test');t=1800000000
   def sample(code,at):
    d=fields.decode_bms_actual(self.frame(code),1);d['_battery_can_measured_at']={k:at for k in d};d['battery_wh']=13650;return d
   e.tick(t,False,sampled=sample(4,t-1));self.assertEqual(e.s['vehicle']['charge_power_w'],1400)
   e.tick(t+30,False,sampled=sample(4,t+29));self.assertEqual(e.s['vehicle']['charge_power_w'],1400)
   self.assertTrue(e.s['vehicle']['charging']);self.assertEqual(e.s['vehicle']['charge_state_source'],'can_actual')
   self.assertEqual(e.s['charge']['source'],'can_actual')
   e.tick(t+31,False,sampled=sample(1,t+30));self.assertFalse(e.s['vehicle']['charging']);self.assertEqual(e.s['vehicle']['charge_power_w'],0)
   e.tick(t+32,False,sampled=sample(7,t+31));self.assertIsNone(e.s['vehicle']['charge_power_w']);self.assertIsNone(e.s['vehicle']['hv_voltage'])
   e.tick(t+140,False);self.assertIsNone(e.s['vehicle']['charging'])
