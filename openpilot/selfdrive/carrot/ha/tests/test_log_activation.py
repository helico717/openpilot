import json
from pathlib import Path
import tempfile
import time
import unittest
from openpilot.selfdrive.carrot.ha.driving_logs import ActivationTracker


class ActivationTests(unittest.TestCase):
  def test_existing_including_open_segments_excluded_and_new_segments_survive_restart(self):
    with tempfile.TemporaryDirectory() as temp:
      root=Path(temp)/'logs';root.mkdir();receipt=Path(temp)/'activation.json'
      old=root/'route--0';old.mkdir();(old/'rlog.lock').touch()
      tracker=ActivationTracker(receipt)
      policy={'enabled':True,'generation':'first','since':time.time()-1}
      self.assertTrue(tracker.observe(policy,root))
      self.assertIsNone(tracker.started(old.name))
      new=root/'route--1';new.mkdir();tracker.observe(policy,root)
      self.assertIsNotNone(tracker.started(new.name))
      tracker=ActivationTracker(receipt);tracker.observe(policy,root)
      self.assertIsNotNone(tracker.started(new.name))
      tracker.observe({'enabled':False,'generation':'off'},root)
      missed=root/'route--2';missed.mkdir()
      tracker.observe({'enabled':True,'generation':'second','since':time.time()-1},root)
      for name in (old.name,new.name,missed.name):self.assertIsNone(tracker.started(name))
      latest=root/'route--3';latest.mkdir();tracker.observe({'enabled':True,'generation':'second','since':time.time()-1},root)
      self.assertIsNotNone(tracker.started(latest.name))

  def test_missing_permission_and_lost_receipt_never_backfill(self):
    with tempfile.TemporaryDirectory() as temp:
      root=Path(temp)/'logs';root.mkdir();(root/'route--0').mkdir();receipt=Path(temp)/'activation.json'
      tracker=ActivationTracker(receipt)
      for policy in ({},{'enabled':True},{'enabled':True,'generation':'x','since':float('nan')}):
        self.assertFalse(tracker.observe(policy,root))
      receipt.write_text('corrupt')
      tracker=ActivationTracker(receipt);tracker.observe({'enabled':True,'generation':'x','since':time.time()-1},root)
      self.assertIsNone(tracker.started('route--0'))


if __name__=='__main__':unittest.main()
