import os
import subprocess
import tempfile
import unittest
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[5]/'.github/scripts/sync_upstream_model_selector.sh'
class SyncWorkflowsTests(unittest.TestCase):
    def run_git(self,*args):
        return subprocess.run(['git',*args],cwd=self.root,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout.strip()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.run_git('init');self.run_git('config','user.email','test@example.invalid');self.run_git('config','user.name','Test')
        (self.root/'.github/workflows').mkdir(parents=True)
        (self.root/'.github/workflows/keep.yml').write_text('keep')
        (self.root/'.github/workflows/deleted.yml').write_text('base')
        (self.root/'code').write_text('base')
        self.commit();self.run_git('branch','upstream-test')
        (self.root/'.github/workflows/deleted.yml').unlink();(self.root/'code').write_text('fork')
        self.commit();self.fork=self.run_git('rev-parse','HEAD')
        self.run_git('checkout','upstream-test')
        (self.root/'.github/workflows/deleted.yml').write_text('upstream')
        (self.root/'upstream-code').write_text('new')
        self.commit()
    def commit(self):
        self.run_git('add','.');self.run_git('commit','-m','fixture')
    def sync(self):
        self.run_git('checkout','--detach',self.fork)
        return subprocess.run(['bash',str(SCRIPT)],cwd=self.root,env=dict(os.environ,UPSTREAM_REF='upstream-test',SYNC_PUSH='false',SYNC_WORKFLOWS='false'),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    def test_workflow_modify_delete_conflict_is_resolved_with_fork_tree(self):
        result=self.sync();self.assertEqual(result.returncode,0,result.stdout)
        self.assertFalse((self.root/'.github/workflows/deleted.yml').exists())
        self.assertTrue((self.root/'upstream-code').exists())
        self.assertEqual((self.root/'code').read_text(),'fork')
        self.assertEqual(self.run_git('diff',self.fork,'HEAD','--','.github/workflows'),'')
    def test_source_conflicts_fail_and_abort_instead_of_discarding_code(self):
        (self.root/'code').write_text('upstream-conflict');self.commit()
        result=self.sync();self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.run_git('rev-parse','HEAD'),self.fork)
        self.assertEqual(self.run_git('status','--porcelain'),'')
