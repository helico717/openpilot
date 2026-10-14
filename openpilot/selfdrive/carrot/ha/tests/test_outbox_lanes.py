import json
from pathlib import Path
import tempfile
import unittest
from openpilot.selfdrive.carrot.ha.engine import Store


class OutboxLaneTests(unittest.TestCase):
    def test_failed_telemetry_does_not_block_trip_and_replay_is_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'collector.sqlite3'
            store = Store(path)
            store.save({}, [('/api/telemetry', {'deviceId':'car','updatedAt':'old'}),
                            ('/api/trips', {'id':'trip','distanceM':1000}),
                            ('/api/telemetry', {'deviceId':'car','updatedAt':'new'})], 1)
            failed = store.first_for('/api/telemetry')
            trip = store.first_for('/api/trips')
            self.assertEqual(trip[0], 'trip')
            self.assertEqual(json.loads(store.latest_telemetry()[2])['updatedAt'], 'new')
            store.acknowledge(trip[0])
            restarted = Store(path)
            self.assertEqual(restarted.first_for('/api/telemetry'), failed)
            self.assertIsNone(restarted.first_for('/api/trips'))
            self.assertEqual(restarted.count(), 2)
