"""Stock-to-HA activation on temporary local Git repositories, no vehicle."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('iq_install',Path(__file__).parents[1]/'bootstrap/install_from_stock.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def git(repo,*args):
    return subprocess.check_output(['git','-C',str(repo),*args],text=True,stderr=subprocess.DEVNULL).strip()


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.repo=self.base/'stock';self.repo.mkdir();git(self.repo,'init','-qb','release')
        for repo in [self.repo]:
            git(repo,'config','user.name','test');git(repo,'config','user.email','test@example.invalid')
        (self.repo/'.gitignore').write_text('.iqpilot/\n')
        (self.repo/'stock.txt').write_text('stock')
        for name in ['iqpilot/system/camerad/camerad','iqpilot/system/loggerd/encoderd']:
            p=self.repo/name;p.parent.mkdir(parents=True);p.write_text('#!/bin/sh\nexit 0\n');p.chmod(0o755)
        git(self.repo,'add','.');git(self.repo,'commit','-qm','stock');self.iq_sha=git(self.repo,'rev-parse','HEAD')
        self.bare=self.base/'upstream.git';subprocess.run(['git','clone','-q','--bare',str(self.repo),str(self.bare)],check=True)
        git(self.repo,'remote','add','origin',str(self.bare))
        self.stage=self.base/'candidate';self.stage.mkdir();git(self.stage,'init','-qb','iq-ha')
        git(self.stage,'config','user.name','test');git(self.stage,'config','user.email','test@example.invalid')
        (self.stage/'vendor').mkdir()
        subprocess.run(['git','clone','-q',str(self.bare),str(self.stage/'vendor/iqpilot')],check=True)
        (self.stage/'.gitmodules').write_text('[submodule "iqpilot-vendor"]\n path = vendor/iqpilot\n url = '+str(self.bare)+'\n')
        (self.stage/'HA_CANDIDATE.json').write_text(json.dumps({'iqpilot_sha':self.iq_sha,'required_os':'4.9.9.9.2'}))
        self.runtime=self.base/'runtime';(self.stage/'.iqpilot').symlink_to(self.runtime)
        for name in ['iqpilot/system/camerad/camerad','iqpilot/system/loggerd/encoderd']:
            p=self.stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.symlink_to(os.path.relpath(self.stage/'vendor/iqpilot'/name,p.parent))
        git(self.stage,'add','.');git(self.stage,'commit','-qm','HA candidate')
        self.params=self.base/'params';self.params.mkdir()
        for key,value in [('IsOffroad','1'),('IsOnroad','0'),('UpdaterState','idle')]: (self.params/key).write_text(value)
        self.version=self.base/'VERSION';self.version.write_text('4.9.9.9.2')
        (self.repo/'.iqpilot').mkdir();(self.repo/'.iqpilot/cache').write_text('runtime cache')

    def tearDown(self):self.temp.cleanup()

    def activate(self):
        with patch.object(module,'ORIGIN',str(self.stage)),patch.dict(os.environ,{'GIT_ALLOW_PROTOCOL':'file'}):
            module.activate(self.stage,self.repo,self.params,self.version,self.runtime)

    def test_git_activation_preserves_runtime_and_origin_tracking(self):
        self.activate()
        self.assertEqual(git(self.repo,'rev-parse','HEAD'),git(self.stage,'rev-parse','HEAD'))
        self.assertEqual(git(self.repo/'vendor/iqpilot','rev-parse','HEAD'),self.iq_sha)
        self.assertEqual((self.runtime/'cache').read_text(),'runtime cache')
        self.assertEqual(git(self.repo,'status','--porcelain','--untracked-files=no'),'')
        self.assertEqual(git(self.repo,'rev-parse','--abbrev-ref','@{u}'),'origin/iq-ha')
        self.assertFalse((self.repo/'.git/modules/iqpilot-vendor/objects/info/alternates').exists())

    def test_pending_update_missing_parked_or_wrong_os_refuses_before_changes(self):
        before=git(self.repo,'rev-parse','HEAD')
        for key,value in [('UpdaterState','downloading...'),('IsOffroad',''),('IsOnroad','1')]:
            original=(self.params/key).read_text();(self.params/key).write_text(value)
            with self.assertRaises((ValueError,OSError)):self.activate()
            (self.params/key).write_text(original)
        self.version.write_text('4.9.9.4')
        with self.assertRaises(ValueError):self.activate()
        self.assertEqual(git(self.repo,'rev-parse','HEAD'),before)
        self.assertTrue((self.repo/'.iqpilot/cache').is_file())
        self.assertFalse(self.runtime.exists())

    def test_checkout_collision_does_not_lose_runtime_cache(self):
        (self.repo/'HA_CANDIDATE.json').write_text('untracked collision')
        before=git(self.repo,'rev-parse','HEAD')
        with self.assertRaises(subprocess.CalledProcessError):self.activate()
        self.assertEqual(git(self.repo,'rev-parse','HEAD'),before)
        self.assertTrue((self.repo/'.iqpilot/cache').is_file())
        self.assertFalse(self.runtime.exists())
