import ast
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from openpilot.selfdrive.carrot.ha import direct_connection as direct
from openpilot.selfdrive.carrot.ha import param_sync


class DirectConnectionTests(unittest.TestCase):
    def config(self):
        return {'transport': 'direct', 'url': 'https://ha.example/carrot-receiver',
                'device': 'car', 'token': 'u' * 32}

    def test_setup_is_atomic_persistent_and_never_changes_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'direct-connection.json'
            direct.configure(self.config(), path)
            self.assertEqual(json.loads(path.read_text()), self.config())
            self.assertFalse(path.with_suffix('.tmp').exists())
            for field, value in (('url', 'http://ha.example'), ('url', 'https://ha.example/unrelated'),
                                 ('token', 'weak'), ('device', '../device')):
                with self.assertRaises(ValueError):
                    direct.configure({**self.config(), field: value}, path)
                self.assertEqual(json.loads(path.read_text()), self.config())

    def test_queue_identity_never_reuses_legacy_or_other_receiver_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            legacy = param_sync.ProcessedQueueStore(state / 'param_sync.sqlite3')
            legacy.record(1, 'car', 'Test', 1, 1, 'applied')
            first = param_sync.ProcessedQueueStore(direct.queue_store_path(state, 'server-one'))
            second = param_sync.ProcessedQueueStore(direct.queue_store_path(state, 'server-two'))
            self.assertIsNone(first.get(1))
            first.record(1, 'car', 'Test', 2, 2, 'applied')
            self.assertIsNone(second.get(1))
            self.assertEqual(legacy.get(1)['actual_val'], '1')
            self.assertEqual(param_sync.ProcessedQueueStore(direct.queue_store_path(state, 'server-one')).get(1)['actual_val'], '2')

    def test_provision_mapping_failure_never_falls_back_to_cloud(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'profile.json'
            target = Path(directory) / 'direct.json'
            profile.write_text(json.dumps({'previous_url': 'https://cloud.example',
                                          'receiver_url': self.config()['url']}))
            legacy = {'url': 'https://cloud.example', 'device': 'car', 'token': 'p' * 32}
            with patch.object(direct, '_retry_at', 0), patch.object(direct.urllib.request, 'build_opener') as opener:
                opener.return_value.open.side_effect = OSError('offline')
                self.assertIsNone(direct.resolve(legacy, profile, target))
                self.assertFalse(target.exists())
            class Response:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self, size): return json.dumps({'config': self_config}).encode()
            self_config = self.config()
            with patch.object(direct, '_retry_at', 0), patch.object(direct.urllib.request, 'build_opener') as opener:
                opener.return_value.open.return_value = Response()
                self.assertEqual(direct.resolve(legacy, profile, target), self_config)
                self.assertEqual(json.loads(target.read_text()), self_config)
                self.assertEqual(direct.resolve(legacy, profile, target), self_config)
                self.assertEqual(opener.return_value.open.call_count, 1)
                request = opener.return_value.open.call_args.args[0]
                self.assertEqual(request.full_url, self_config['url'] + '/api/provision')
            target.unlink()
            target.with_suffix('.disabled').write_text('explicit rollback')
            with patch.object(direct.urllib.request, 'build_opener') as opener:
                self.assertEqual(direct.resolve(legacy, profile, target), legacy)
                opener.assert_not_called()
            direct.configure(self_config, target)
            self.assertFalse(target.with_suffix('.disabled').exists())

    def test_direct_poll_handles_replay_with_its_own_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            legacy = param_sync.ProcessedQueueStore(state / 'param_sync.sqlite3')
            legacy.record(1, 'car', 'Test', 1, 1, 'applied')
            calls = []
            def http(url, **kwargs):
                calls.append((url, kwargs))
                if '/pending?' in url:
                    return {'ok': True, 'queue_namespace': 'server-one',
                            'pending': [{'id': 1, 'param_name': 'Test', 'param_value': '2'}]}
                return {'ok': True}
            with patch.object(param_sync, 'STATE', state), patch.object(param_sync, '_http_request', side_effect=http), \
                 patch.object(param_sync, 'fetch_local_settings_snapshot', return_value=None), \
                 patch.object(param_sync, 'apply_local_param', return_value={'value': 2}) as apply, \
                 patch.object(param_sync.time, 'sleep', side_effect=InterruptedError):
                for _ in range(2):
                    with self.assertRaises(InterruptedError):
                        param_sync.run_param_sync(self.config(), legacy)
                self.assertEqual(apply.call_count, 1)
            acks = [args['data'] for url, args in calls if '/api/params/ack' in url]
            self.assertEqual(len(acks), 2)
            self.assertTrue(all(ack['queue_namespace'] == 'server-one' for ack in acks))


if __name__ == '__main__':
    unittest.main()
