"""Session completeness follows missing observations, never normal departure."""
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'charge_recorder.py'
spec = importlib.util.spec_from_file_location('quality_recorder', PATH)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

class ChargeQualityTests(unittest.TestCase):
    def setUp(self):
        self.state = {'charge_months': {}, 'charge_sessions': []}

    def signal(self, at, active=True, driving=False, code=4):
        return dict(charging=active, code=code if active else 1,
                    measured_at=r.stamp(at), source_kind='actual', driving=driving)

    def start(self):
        for t, wh in ((100, 20000), (130, 20050), (160, 20100)):
            r.update(self.state, t, self.signal(t), wh)

    def test_immediate_departure_is_complete_and_never_credits_driving_energy(self):
        self.start()
        r.update(self.state, 170, self.signal(170, False, True), 20200)
        c = self.state['charge_sessions'][0]
        self.assertFalse(c['partial'])
        self.assertEqual(c['partial_reasons'], [])
        self.assertAlmostEqual(c['energy_kwh'], .1)
        self.assertEqual(c['unknown_duration_s'], 0)

    def test_explicit_stop_then_departure_does_not_reopen_or_reclassify(self):
        self.start()
        r.update(self.state, 170, self.signal(170, False), 20150)
        first = dict(self.state['charge_sessions'][0])
        r.update(self.state, 180, self.signal(180, False, True), 20200)
        self.assertEqual(self.state['charge_sessions'], [first])
        self.assertFalse(first['partial'])

    def test_collector_restart_gap_is_not_confirmed_charging(self):
        self.start()
        # No calls at all while the collector cannot collect data.
        r.update(self.state, 460, self.signal(460), 20600)
        c = self.state['charge']
        self.assertTrue(c['partial'])
        self.assertIn('charging_signal_gap', c['partial_reasons'])
        self.assertEqual(c['confirmed_duration_s'], 60)
        self.assertEqual(c['unknown_duration_s'], 300)
        self.assertAlmostEqual(c['corrected_energy_kwh'], .5)
        r.update(self.state, 470, self.signal(470, False, True), 20600)
        self.assertTrue(self.state['charge_sessions'][0]['partial'])

    def test_restart_followed_by_departure_preserves_gap(self):
        self.start()
        r.update(self.state, 460, self.signal(460, False, True), 21000)
        c = self.state['charge_sessions'][0]
        self.assertTrue(c['partial'])
        self.assertEqual(c['partial_reasons'], ['charging_signal_gap_before_stop'])
        self.assertAlmostEqual(c['energy_kwh'], .1)

    def test_valid_low_power_and_quantized_energy_are_not_missing_data(self):
        for t in range(100, 1000, 30):
            r.update(self.state, t, self.signal(t), 20000)
        r.update(self.state, 1000, self.signal(1000, False, True), 20000)
        self.assertFalse(self.state['charge_sessions'][0]['partial'])

    def test_missing_energy_with_fresh_modes_has_reason(self):
        self.start()
        for t in (190, 220, 250, 280, 310):
            r.update(self.state, t, self.signal(t), None)
        self.assertTrue(self.state['charge']['partial'])
        self.assertIn('battery_energy_measurement_gap', self.state['charge']['partial_reasons'])

    def test_signal_gap_recovery_remains_partial_and_reasons_do_not_duplicate(self):
        self.start()
        r.update(self.state, 200, {'charging': None})
        r.update(self.state, 250, self.signal(250), 20200)
        r.update(self.state, 300, {'charging': None})
        r.update(self.state, 340, self.signal(340), 20300)
        c = self.state['charge']
        self.assertTrue(c['partial'])
        self.assertEqual(c['partial_reasons'].count('charging_signal_gap'), 1)

    def test_missing_start_energy_and_invalid_steps_are_explained(self):
        r.update(self.state, 100, self.signal(100), None)
        self.assertEqual(self.state['charge']['partial_reasons'], ['missing_start_energy'])
        self.setUp();self.start()
        r.update(self.state, 161, self.signal(161), 90000)
        self.assertIn('implausible_energy_increase', self.state['charge']['partial_reasons'])

if __name__ == '__main__':
    unittest.main()
