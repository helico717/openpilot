"""Update transaction ordering and IQ.OS's supported origin-only Git interface."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('iq_update',Path(__file__).parents[1]/'bootstrap/update_iq_ha.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.params=Path(self.temp.name)
        (self.params/'IsOffroad').write_text('1');(self.params/'IsOnroad').write_text('0')
        self.calls=[];self.updated=False;self.fail_vendor=False;self.diverged=False
    def tearDown(self):self.temp.cleanup()
    def git(self,repo,*args):
        self.calls.append((Path(repo),args))
        vendor=Path(repo).name=='iqpilot'
        if args==('branch','--show-current'):return 'iq-ha'
        if args==('remote','get-url','origin'):return 'https://github.com/helico717/openpilot.git'
        if args[0]=='diff':return ''
        if args[0]=='merge-base' and self.diverged:raise subprocess.CalledProcessError(1,args)
        if args==('rev-parse','HEAD'):return ('b'*40 if self.updated else 'a'*40) if vendor else 'c'*40
        if args[0]=='rev-parse':return 'c'*40
        if args[0]=='ls-tree':return '160000 commit '+'b'*40+'\tvendor/iqpilot'
        if args[0]=='fetch' and vendor and self.fail_vendor:raise subprocess.CalledProcessError(1,args)
        if args[:2]==('submodule','update'):self.updated=True
        return ''
    def test_download_before_pull_and_supported_commands(self):
        with patch.object(module,'git',side_effect=self.git):module.update(Path('/device'),self.params,True)
        commands=[a for p,a in self.calls]
        self.assertLess(commands.index(('fetch','--depth','1','origin','b'*40)),commands.index(('pull','origin')))
        self.assertLess(commands.index(('config','pull.ff','only')),commands.index(('pull','origin')))
        self.assertIn(('submodule','update','--init','--no-fetch','--','vendor/iqpilot'),commands)
        self.assertFalse(any('reset' in c or 'clean' in c for c in commands))
    def test_network_failure_and_divergence_do_not_pull(self):
        for failure in ['vendor','diverged']:
            self.calls=[];self.fail_vendor=failure=='vendor';self.diverged=failure=='diverged'
            with patch.object(module,'git',side_effect=self.git),self.assertRaises(subprocess.CalledProcessError):
                module.update(Path('/device'),self.params,True)
            self.assertFalse(any(a[0] in ('pull','checkout') for _,a in self.calls))
    def test_missing_or_onroad_state_never_calls_git(self):
        for off,on in [('','0'),('1','1')]:
            (self.params/'IsOffroad').write_text(off);(self.params/'IsOnroad').write_text(on)
            with patch.object(module,'git') as git,self.assertRaises(ValueError):module.update(Path('/device'),self.params,True)
            git.assert_not_called()
