"""openpilot assist statistics (carrot-ha docs/OPENPILOT_ASSIST_STATS_PLAN_2026-11-05.md)."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('ha_engine_assist', Path(__file__).resolve().parents[1]/'engine.py')
engine = importlib.util.module_from_spec(spec); spec.loader.exec_module(engine)

BOTH = {'lat': True, 'long': True, 'enabled': True}
MANUAL = {'lat': False, 'long': False, 'enabled': False}
LAT_ONLY_NOT_ENABLED = {'lat': True, 'long': False, 'enabled': False}
STALE = {'lat': None, 'long': None, 'enabled': None}
CLASSES = ('manualM', 'latOnlyM', 'longOnlyM', 'bothM', 'unknownM')


class AssistStatsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = engine.Store(Path(self.tmp.name)/'state.sqlite3')
        self.e = engine.Engine(self.store, 'car')
        self.base = 1800000000  # 2027-01-15T08:00:00Z, a 15-minute boundary

    def tick(self, t, control, speed=20, odo=None, motion=True):
        return self.e.tick(self.base+t, True, control=control,
                           sampled={'odometer_km': odo} if odo is not None else None,
                           motion={'gear': 'drive', 'speed_mps': speed} if motion else None,
                           monotonic_now=self.base+t)

    def finish(self, t):
        events = self.e.tick(self.base+t, False, motion={'gear': 'park', 'speed_mps': 0}, monotonic_now=self.base+t)
        return next(body for path, body in events if path == '/api/trips')

    def assertConsistent(self, a):
        self.assertAlmostEqual(sum(a[k] for k in CLASSES), a['basisDistanceM'], delta=1)
        self.assertAlmostEqual(sum(b[k] for b in a['buckets'] for k in CLASSES), a['basisDistanceM'], delta=1)
        self.assertAlmostEqual(sum(a['enabled'].values()), a['basisDistanceM'], delta=1)
        json.dumps(a, allow_nan=False)

    def test_tunnel_without_gps_counts_full_assist_distance(self):
        for t in range(601): self.tick(t, BOTH)
        trip = self.finish(601)
        a = trip['assist']
        self.assertEqual(trip['distanceM'], 12000)
        self.assertEqual(trip['route'], [])
        self.assertEqual(a['bothM'], 12000)
        self.assertEqual(a['basisDistanceM'], 12000)
        self.assertEqual(a['enabled']['onM'], 12000)
        self.assertEqual((a['engagements'], a['disengagements']), (0, 0))  # first sample is not an engagement
        self.assertEqual(a['longestStreakM'], 12000)
        self.assertEqual(a['streaks'][0]['brokenByGap'], False)
        self.assertConsistent(a)

    def test_previous_sample_classifies_each_interval_and_counts_transitions(self):
        plan = [(0, 100, MANUAL), (100, 200, BOTH), (200, 300, MANUAL), (300, 400, LAT_ONLY_NOT_ENABLED)]
        for start, end, control in plan:
            for t in range(start, end): self.tick(t, control)
        trip = self.finish(400)
        a = trip['assist']
        # Interval [t-1, t] uses the sample taken at t-1, so each 100-tick block
        # contributes 100 intervals except the last one, which ends at park.
        self.assertEqual(a['manualM'], 2000 + 2000)
        self.assertEqual(a['bothM'], 2000)
        self.assertEqual(a['latOnlyM'], 1980)  # tick 399 -> park tick 400 adds no distance
        self.assertEqual((a['engagements'], a['disengagements']), (2, 1))
        self.assertEqual(a['streakCount'], 2)
        self.assertConsistent(a)

    def test_lateral_assist_is_counted_even_when_selfdrive_not_enabled(self):
        for t in range(101): self.tick(t, LAT_ONLY_NOT_ENABLED)
        a = self.finish(101)['assist']
        self.assertEqual(a['latOnlyM'], 2000)
        self.assertEqual(a['manualM'], 0)
        self.assertEqual(a['enabled']['offM'], 2000)
        self.assertConsistent(a)

    def test_signal_loss_while_engaged_is_unknown_and_not_an_engagement(self):
        for t in range(100): self.tick(t, BOTH)
        for t in range(100, 110): self.tick(t, STALE)
        for t in range(110, 201): self.tick(t, BOTH)
        a = self.finish(201)['assist']
        self.assertEqual(a['unknownM'], 200)
        self.assertEqual((a['engagements'], a['disengagements']), (0, 0))
        self.assertEqual(a['streakCount'], 2)
        broken = sorted(s['brokenByGap'] for s in a['streaks'])
        self.assertEqual(broken, [False, True])
        self.assertEqual(a['longestStreakM'], 2000)  # the gap-broken first streak
        self.assertEqual(a['bothM'], 3800)
        self.assertEqual(a['knownDurationS'], 190)
        self.assertConsistent(a)

    def test_downward_odometer_recovery_keeps_wheel_basis(self):
        self.tick(0, BOTH, odo=1000)
        for t in range(1, 401):
            self.tick(t, BOTH, odo=1007 if t == 400 else None, motion=(t != 200))
        trip = self.finish(401)
        a = trip['assist']
        self.assertEqual(trip['distanceSource'], 'odometer_gap_recovery')
        self.assertEqual(trip['distanceM'], 7000)
        self.assertGreater(a['basisDistanceM'], trip['distanceM'])  # recovery difference is negative
        self.assertEqual(a['basisDistanceM'], 7960)
        self.assertConsistent(a)

    def test_restart_while_engaged_closes_streak_and_does_not_count_reengagement(self):
        for t in range(100): self.tick(t, BOTH)
        self.e = engine.Engine(self.store, 'car')
        for t in range(100, 201): self.tick(t, BOTH)
        a = self.finish(201)['assist']
        self.assertEqual(a['engagements'], 0)
        self.assertEqual(a['streakCount'], 2)
        self.assertIn(True, [s['brokenByGap'] for s in a['streaks']])
        self.assertConsistent(a)

    def test_increment_crossing_a_15_minute_boundary_is_split_by_time(self):
        start = self.base - 10.5  # boundary falls inside one 1s interval
        for i in range(21):
            self.e.tick(start+i, True, control=BOTH, motion={'gear': 'drive', 'speed_mps': 20}, monotonic_now=start+i)
        events = self.e.tick(start+21, False, motion={'gear': 'park', 'speed_mps': 0}, monotonic_now=start+21)
        a = next(body for path, body in events if path == '/api/trips')['assist']
        before, after = a['buckets']
        self.assertEqual(before['at'], '2027-01-15T07:45:00+00:00')
        self.assertEqual(after['at'], '2027-01-15T08:00:00+00:00')
        self.assertEqual(before['bothM'], 210)
        self.assertEqual(after['bothM'], 190)
        self.assertConsistent(a)

    def test_short_streaks_are_counted_but_not_listed_and_list_is_bounded(self):
        t = 0
        for _ in range(60):  # 60 streaks of 200m, separated by manual driving
            for _ in range(10): self.tick(t, BOTH); t += 1
            for _ in range(3): self.tick(t, MANUAL); t += 1
        for _ in range(3): self.tick(t, BOTH); t += 1  # final 40m streak
        a = self.finish(t)['assist']
        self.assertEqual(a['streakCount'], 60)
        self.assertEqual(len(a['streaks']), 50)
        self.assertEqual(a['engagements'], 60)
        self.assertEqual(a['disengagements'], 60)
        self.assertConsistent(a)

    def test_missing_control_is_reported_as_unknown(self):
        for t in range(51): self.e.tick(self.base+t, True, motion={'gear': 'drive', 'speed_mps': 20}, monotonic_now=self.base+t)
        a = self.finish(51)['assist']
        self.assertEqual(a['unknownM'], 1000)
        self.assertEqual(a['knownDurationS'], 0)
        self.assertEqual(a['enabled']['unknownM'], 1000)
        self.assertConsistent(a)


if __name__ == '__main__':
    unittest.main()
