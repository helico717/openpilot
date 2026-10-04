import importlib.util
import unittest
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'charge_recorder.py'
spec=importlib.util.spec_from_file_location('charge_recorder',p)
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class RecorderTests(unittest.TestCase):
 def setUp(self):self.s={'charge_months':{},'charge_sessions':[]}
 def signal(self,t,code=6):return {'charging':code in (4,6),'code':code,'measured_at':r.stamp(t)}
 def test_parked_increase_does_not_start_session(self):
  r.update(self.s,100,self.signal(100,1),20000)
  r.update(self.s,130,self.signal(130,1),20150)
  self.assertNotIn('charge',self.s);self.assertEqual(self.s['charge_months'],{})
 def test_mode_starts_and_ends_without_energy_increase(self):
  r.update(self.s,100,self.signal(100),20000)
  self.assertIn('charge',self.s)
  r.update(self.s,130,self.signal(130,1),20000)
  self.assertNotIn('charge',self.s);self.assertEqual(len(self.s['charge_sessions']),1)
 def test_gap_correction_once_and_unknown_time_separate(self):
  r.update(self.s,100,self.signal(100),20000)
  r.update(self.s,130,self.signal(130),20500)
  r.update(self.s,230,{'charging':None})
  r.update(self.s,400,self.signal(400),22000)
  c=self.s['charge'];self.assertAlmostEqual(c['energy_kwh'],2)
  self.assertAlmostEqual(c['corrected_energy_kwh'],1.5)
  self.assertEqual(c['unknown_duration_s'],270)
  r.update(self.s,400,self.signal(400),22000)
  self.assertAlmostEqual(c['energy_kwh'],2)
 def test_changed_mode_not_merged(self):
  r.update(self.s,100,self.signal(100),20000)
  r.update(self.s,230,{'charging':None})
  r.update(self.s,400,self.signal(400,4),22000)
  self.assertEqual(len(self.s['charge_sessions']),1)
  self.assertEqual(self.s['charge']['can_mode'],4)
 def test_expired_gap_closes_partial_without_inventing_energy(self):
  r.update(self.s,100,self.signal(100),20000)
  r.update(self.s,2001,{'charging':None})
  self.assertNotIn('charge',self.s)
  self.assertTrue(self.s['charge_sessions'][0]['partial'])
  r.update(self.s,2030,self.signal(2030),24000)
  self.assertEqual(self.s['charge']['energy_kwh'],0)
 def test_decreased_or_implausible_gap_energy_starts_separate_session(self):
  for wh in (19950,50000):
   with self.subTest(wh=wh):
    self.setUp()
    r.update(self.s,100,self.signal(100),20000)
    r.update(self.s,200,{'charging':None})
    r.update(self.s,230,self.signal(230),wh)
    self.assertEqual(len(self.s['charge_sessions']),1)
    self.assertEqual(self.s['charge']['energy_kwh'],0)
    self.assertEqual(self.s['charge']['unknown_duration_s'],0)
 def test_confirmed_noncharging_during_gap_prevents_reconstruction(self):
  r.update(self.s,100,self.signal(100),20000)
  r.update(self.s,200,{'charging':None})
  r.update(self.s,250,self.signal(250,1),22000)
  self.assertTrue(self.s['charge_sessions'][0]['partial'])
  self.assertEqual(self.s['charge_sessions'][0]['energy_kwh'],0)
  r.update(self.s,400,self.signal(400),23000)
  self.assertEqual(self.s['charge']['energy_kwh'],0)
 def test_invalid_energy_does_not_credit_gap(self):
  r.update(self.s,100,self.signal(100),20000)
  r.update(self.s,200,{'charging':None})
  r.update(self.s,400,self.signal(400),102350)
  self.assertEqual(self.s['charge']['energy_kwh'],0)
  self.assertTrue(self.s['charge']['partial'])
 def test_dip_and_rebound_are_counted_once(self):
  for t,wh in ((100,20000),(130,20500),(160,20400),(190,20500),(220,20600)):
   r.update(self.s,t,self.signal(t),wh)
  self.assertAlmostEqual(self.s['charge']['energy_kwh'],0.6)
