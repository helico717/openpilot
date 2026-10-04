import importlib.util
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

spec=importlib.util.spec_from_file_location('charge_engine',Path(__file__).resolve().parents[1]/'engine.py')
engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)

class ChargeClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=engine.Store(Path(self.tmp.name)/'state.sqlite3')
        self.e=engine.Engine(self.store,'car')
        self.base=datetime(2026,10,2,tzinfo=timezone.utc).timestamp()
    def sample(self,t,wh,code=6):
        self.e.tick(self.base+t,False,sampled={'battery_wh':wh,'charge_can_bms_request_bus1':code},motion={'gear':'park','speed_mps':0})
    def ledger(self):
        return self.e.s['charge_months']['2026-10']
    def test_fast_promotion_includes_slow_startup_but_not_other_ac_session(self):
        self.e.s['charge_months']['2026-10']={'slow_kwh':7,'fast_kwh':0,'cost_krw':1960}
        for t,wh in [(0,30000),(90,30025),(180,30050),(270,32050),(360,32100)]:self.sample(t,wh)
        self.assertAlmostEqual(self.ledger()['slow_kwh'],7)
        self.assertAlmostEqual(self.ledger()['fast_kwh'],2.1)
        self.assertAlmostEqual(self.ledger()['cost_krw'],1960+2.1*320)
        self.assertAlmostEqual(self.e.s['charge']['energy_kwh'],2.1)
    def test_dip_rebound_does_not_count_again_or_extend_session(self):
        for t,wh in [(0,30000),(90,32000),(180,32025),(270,32000),(360,32025)]:self.sample(t,wh)
        self.assertAlmostEqual(self.ledger()['fast_kwh'],2)
        self.assertEqual(self.ledger()['slow_kwh'],0)
        self.assertEqual(self.e.s['charge']['peak_wh'],32000)
        self.sample(450,32100)
        self.assertAlmostEqual(self.ledger()['fast_kwh'],2.1)
    def test_actual_ac_remains_slow(self):
        for t,wh in [(0,30000),(90,30150),(180,30300)]:self.sample(t,wh,4)
        self.assertAlmostEqual(self.ledger()['slow_kwh'],.3)
        self.assertEqual(self.ledger()['fast_kwh'],0)
    def test_fast_latch_and_peak_survive_restart(self):
        for t,wh in [(0,30000),(90,32000),(180,32050)]:self.sample(t,wh)
        self.store.save(self.e.s,[],self.base+180)
        self.e=engine.Engine(self.store,'car')
        self.sample(270,32025);self.sample(360,32050);self.sample(450,32100)
        self.assertAlmostEqual(self.ledger()['fast_kwh'],2.1)
        self.assertEqual(self.ledger()['slow_kwh'],0)
    def test_month_boundary_promotion_corrects_each_month(self):
        self.base=datetime(2026,9,30,14,58,tzinfo=timezone.utc).timestamp()
        for t,wh in [(0,30000),(90,30100),(180,32100)]:self.sample(t,wh)
        for month,expected in [('2026-09',.1),('2026-10',2)]:
            ledger=self.e.s['charge_months'][month]
            self.assertAlmostEqual(ledger['fast_kwh'],expected)
            self.assertAlmostEqual(ledger['slow_kwh'],0)
            self.assertAlmostEqual(ledger['cost_krw'],expected*320)
    def test_legacy_pending_windows_are_discarded_without_touching_totals(self):
        self.e.s['charge_candidate']={'windows':[{'delta':25,'dt':90,'power':1000}], 'ended_at':self.base}
        self.e.s['charge_months']['2026-10']={'slow_kwh':.1,'fast_kwh':10,'cost_krw':3228}
        self.store.save(self.e.s,[],self.base)
        self.e=engine.Engine(self.store,'car')
        self.assertNotIn('charge_candidate',self.e.s)
        self.assertEqual(self.ledger()['slow_kwh'],.1)
    def test_legacy_active_charge_is_preserved_as_partial_then_can_session_starts(self):
        self.e.s.update(charge={'id':'old','energy_kwh':1,'duration_s':90,'partial':True},
            energy_sample={'wh':30000,'at':self.base,'onroad':False})
        self.sample(90,32000)
        self.assertEqual(self.e.s['charge_sessions'][0]['energy_kwh'],1)
        self.assertTrue(self.e.s['charge_sessions'][0]['partial'])
        self.assertEqual(self.e.s['charge']['source'],'can_request')
        self.assertEqual(self.e.s['charge']['energy_kwh'],0)

    def test_quantized_tail_oscillation_does_not_add_charge(self):
        for t,wh in [(0,30000),(90,32000),(180,32025),(270,32000),
                     (360,32025),(450,32025)]:self.sample(t,wh)
        self.assertEqual(self.ledger()['fast_kwh'],2)
        self.assertEqual(self.ledger()['slow_kwh'],0)
        self.assertEqual(self.e.s['charge']['peak_wh'],32000)

    def test_small_real_increases_accumulate_before_confirmation(self):
        for t,wh in [(0,30000),(90,30100),(180,30125),(270,30150)]:self.sample(t,wh,4)
        self.assertAlmostEqual(self.ledger()['slow_kwh'],.15)
