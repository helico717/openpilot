import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('checkout_status',Path(__file__).resolve().parents[1]/'git_status.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class CheckoutTests(unittest.TestCase):
    def setUp(self):module._cached={};module._next_read=0

    def test_read_only_identity_cache_and_no_credentials(self):
        values=[subprocess.CompletedProcess([],0,v) for v in ('a'*40,'branch','https://github.com/helico717/openpilot.git')]
        with patch.object(module.subprocess,'run',side_effect=values) as run, patch.object(module.time,'monotonic',return_value=1):
            first=module.checkout_status();second=module.checkout_status()
            self.assertEqual(run.call_count,3)
            self.assertEqual(first,second)
            self.assertEqual(first['comma_git_repository'],'helico717/openpilot')
            self.assertEqual(first['comma_git_commit'],'a'*40)
            self.assertTrue(all(c.kwargs['timeout']==2 for c in run.call_args_list))

    def test_error_retains_observation_time(self):
        module._cached={'comma_git_commit':'a'*40,'comma_git_measured_at':'old'}
        with patch.object(module.subprocess,'run',side_effect=OSError('no git')):
            self.assertEqual(module.checkout_status()['comma_git_measured_at'],'old')

    def test_authenticated_remote_is_not_exported(self):
        values=[subprocess.CompletedProcess([],0,v) for v in ('a'*40,'branch','https://secret@github.com/org/repo.git')]
        with patch.object(module.subprocess,'run',side_effect=values):
            self.assertEqual(module.checkout_status(),{})
