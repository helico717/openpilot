import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'param_sync.py'
spec = importlib.util.spec_from_file_location('ha_param_sync', path)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class PollingTests(unittest.TestCase):
    def test_idle_active_and_expiry(self):
        clock = sync.PollSchedule()
        self.assertEqual(clock.delay({'ok': True, 'pending': []}, 0), 15)
        self.assertEqual(clock.delay({'ok': True, 'pending': [], 'poll_after_s': 3}, 10), 3)
        self.assertEqual(clock.delay({'ok': True, 'pending': []}, 50), 3)
        self.assertEqual(clock.delay({'ok': True, 'pending': []}, 71), 15)
        self.assertEqual(clock.delay({'ok': True, 'pending': [{'id': 1}]}, 80), 3)

    def test_failures_back_off_and_success_resets(self):
        clock = sync.PollSchedule()
        self.assertEqual([clock.delay(None, i) for i in range(5)], [15, 30, 60, 120, 120])
        self.assertEqual(clock.delay({'ok': True, 'pending': [], 'poll_after_s': -1}, 200), 15)
        self.assertEqual(clock.delay(None, 201), 15)

    def test_runtime_migration_preserves_ack_idempotency_outside_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)/'git'
            state = Path(tmp)/'persistent'
            store = sync.ProcessedQueueStore(base/'state'/'param_sync.sqlite3')
            store.record(123, 'car', 'Test', 3, 3, 'applied')
            with patch.object(sync,'BASE',base), patch.object(sync,'STATE',state):
                migrated = sync.persistent_queue_store()
                self.assertEqual(migrated.get(123)['status'],'applied')
                migrated.mark_acked([123])
                again = sync.persistent_queue_store()
                self.assertTrue(again.get(123)['acked'])
                self.assertFalse(store.get(123)['acked'])

    def test_replayed_command_only_resends_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = sync.ProcessedQueueStore(Path(tmp)/'params.sqlite3')
            store.record(123, 'car', 'Test', 3, 3, 'applied')
            calls=[]
            def http(url, **kwargs):
                calls.append(url)
                if '/pending?' in url:
                    return {'ok':True,'pending':[{'id':123,'param_name':'Test','param_value':'3'}]}
                return {'ok':True}
            with patch.object(sync,'_http_request',side_effect=http), patch.object(sync,'fetch_local_settings_snapshot',return_value=None), patch.object(sync,'apply_local_param') as apply, patch.object(sync.time,'sleep',side_effect=InterruptedError):
                with self.assertRaises(InterruptedError):
                    sync.run_param_sync({'url':'https://example.test','device':'car','token':'test'},store)
                apply.assert_not_called()
            self.assertTrue(store.get(123)['acked'])
            self.assertTrue(any('/api/params/ack' in url for url in calls))
