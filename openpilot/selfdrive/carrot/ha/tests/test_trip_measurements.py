import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('ha_engine',Path(__file__).resolve().parents[1]/'engine.py')
engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(engine)

class TripMeasurementsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=engine.Store(Path(self.tmp.name)/'state.sqlite3');self.e=engine.Engine(self.store,'car');self.base=1800000000
    def tick(self,t,wh,onroad):
        return self.e.tick(self.base+t,onroad,sampled={'battery_wh':wh},motion={'gear':'drive' if onroad else 'park','speed_mps':10 if onroad else 0})
    def test_boundary_saved_before_throttled_telemetry_and_offroad(self):
        self.tick(0,50000,False)
        self.tick(1,50000,True)
        for t in range(2,22):self.tick(t,50000-(t-1)*10,True)
        events=self.tick(22,49800,False)
        trip=next(body for path,body in events if path=='/api/trips')
        m=trip['tripMeasurements'];self.assertTrue(m['complete'])
        self.assertEqual(m['start']['battery_wh'],50000);self.assertEqual(m['end']['battery_wh'],49800)
    def test_restart_and_invalid_sample_do_not_create_complete_energy(self):
        self.tick(0,50000,False);self.tick(1,50000,True)
        for t in range(2,22):self.tick(t,50000-t*10,True)
        self.e=engine.Engine(self.store,'car')
        self.tick(22,None,True)
        trip=next(body for path,body in self.tick(23,49800,False) if path=='/api/trips')
        self.assertFalse(trip['tripMeasurements']['complete'])
        self.assertIsNotNone(trip['tripMeasurements']['start'])
