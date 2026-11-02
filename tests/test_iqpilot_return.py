"""Carrot return readiness and Git-only switch; synthetic partitions and local repositories only."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / 'bootstrap/switch_to_carrot.sh'
spec = importlib.util.spec_from_file_location('iq_preflight_adapter', ROOT / 'iqpilot/selfdrive/carrot/ha/iq_preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class ReturnReadinessTests(unittest.TestCase):
    def run_check(self, slot, writable):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            bin_dir, parts = folder / 'bin', folder / 'parts'
            bin_dir.mkdir()
            parts.mkdir()
            (bin_dir / 'abctl').write_text(f'#!/bin/sh\necho {slot}\n')
            (bin_dir / 'abctl').chmod(0o755)
            for name in preflight.CARROT_RETURN_PARTITIONS:
                for suffix in ('_a', '_b'):
                    node = parts / (name + suffix)
                    node.write_bytes(b'')
                    node.chmod(0o644 if writable else 0o444)
            path = os.environ['PATH']
            os.environ['PATH'] = f'{bin_dir}{os.pathsep}{path}'
            try:
                return preflight.check_carrot_return(parts)
            finally:
                os.environ['PATH'] = path

    def test_writable_inactive_slot_is_only_possible(self):
        result = self.run_check('_a', True)
        self.assertEqual(result['current_slot'], '_a')
        self.assertTrue(result['inactive_slot_partitions_writable'])
        self.assertEqual(result['verdict'], 'SOFTWARE_RETURN_POSSIBLE_UNVERIFIED')

    @unittest.skipIf(os.geteuid() == 0, 'root bypasses file permissions')
    def test_read_only_partitions_block_return(self):
        result = self.run_check('_b', False)
        self.assertEqual(result['verdict'], 'SOFTWARE_RETURN_BLOCKED')
        self.assertEqual(result['blocked_partitions'], list(preflight.CARROT_RETURN_PARTITIONS))

    def test_unknown_slot_blocks_return(self):
        self.assertEqual(self.run_check('', True)['verdict'], 'SOFTWARE_RETURN_BLOCKED')


class SwitchScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.origin = base / 'helico717/openpilot.git'
        self.device = base / 'device'
        self.params = base / 'params'
        self.params.mkdir()
        (self.params / 'IsOnroad').write_text('0')
        seed = base / 'seed'
        seed.mkdir()
        git(seed, 'init', '-q', '-b', 'ha-back')
        git(seed, 'config', 'user.email', 'test@example.invalid')
        git(seed, 'config', 'user.name', 'test')
        (seed / 'carrot.txt').write_text('carrot\n')
        git(seed, 'add', '.')
        git(seed, 'commit', '-qm', 'carrot')
        self.carrot_sha = git(seed, 'rev-parse', 'HEAD')
        git(seed, 'checkout', '-q', '--orphan', 'iq-ha')
        git(seed, 'rm', '-rqf', '.')
        (seed / 'bootstrap').mkdir()
        (seed / 'bootstrap/switch_to_carrot.sh').write_bytes(SCRIPT.read_bytes())
        (seed / 'iq.txt').write_text('iq\n')
        git(seed, 'add', '.')
        git(seed, 'commit', '-qm', 'iq')
        self.origin.parent.mkdir(parents=True)
        subprocess.run(['git', 'clone', '-q', '--bare', str(seed), str(self.origin)], check=True)
        subprocess.run(['git', 'clone', '-q', '-b', 'iq-ha', str(self.origin), str(self.device)], check=True)

    def tearDown(self):
        self.temp.cleanup()

    def switch(self, expected=None):
        env = dict(os.environ, IQ_HA_PARAMS_DIR=str(self.params),
                   IQ_HA_CARROT_RETURN_SHA=expected or self.carrot_sha)
        return subprocess.run(['bash', str(self.device / 'bootstrap/switch_to_carrot.sh')],
                              env=env, capture_output=True, text=True)

    def test_switches_to_pinned_carrot_without_reboot(self):
        result = self.switch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(git(self.device, 'rev-parse', 'HEAD'), self.carrot_sha)
        self.assertTrue((self.device / 'carrot.txt').is_file())
        self.assertFalse((self.device / 'iq.txt').exists())
        self.assertIn('CARROT_CHECKED_OUT', result.stdout)

    def test_refuses_unexpected_commit(self):
        before = git(self.device, 'rev-parse', 'HEAD')
        self.assertNotEqual(self.switch('0' * 40).returncode, 0)
        self.assertEqual(git(self.device, 'rev-parse', 'HEAD'), before)

    def test_refuses_tracked_changes_and_onroad(self):
        before = git(self.device, 'rev-parse', 'HEAD')
        (self.device / 'iq.txt').write_text('edited\n')
        self.assertNotEqual(self.switch().returncode, 0)
        (self.device / 'iq.txt').write_text('iq\n')
        (self.params / 'IsOnroad').write_text('1')
        self.assertNotEqual(self.switch().returncode, 0)
        self.assertEqual(git(self.device, 'rev-parse', 'HEAD'), before)

    def test_untracked_collision_stops_before_checkout(self):
        (self.device / 'carrot.txt').write_text('untracked device file\n')
        result = self.switch()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.device / 'carrot.txt').read_text(), 'untracked device file\n')
        self.assertNotEqual(git(self.device, 'rev-parse', 'HEAD'), self.carrot_sha)


if __name__ == '__main__':
    unittest.main()
