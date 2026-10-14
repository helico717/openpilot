import hashlib
import hmac
from pathlib import Path
import tempfile
import time
import unittest

from openpilot.selfdrive.carrot.ha.driving_logs import completed, credential


class DrivingLogsTest(unittest.TestCase):
  def test_upload_credential_is_purpose_scoped(self):
    token = 't' * 64
    self.assertEqual(credential(token), hmac.new(token.encode(), b'carrot-driving-logs-v1', hashlib.sha256).hexdigest())
    self.assertNotEqual(credential(token), token)

  def test_only_finalized_original_files_and_newest_first(self):
    import os
    with tempfile.TemporaryDirectory() as temp:
      root = Path(temp)
      for index in range(3):
        directory = root / f'00000315--4742c01c35--{index}'
        directory.mkdir()
        for file in ('rlog.zst','qcamera.ts'):
          path = directory / file
          path.write_bytes(b'original')
          os.utime(path, (time.time() - 100 + index, time.time() - 100 + index))
      (root / '00000315--4742c01c35--2' / 'rlog.lock').touch()
      (root / 'outside--3').symlink_to(root / '00000315--4742c01c35--1',target_is_directory=True)
      items = completed(root)
      self.assertEqual([i[0].name for i in items],['00000315--4742c01c35--1','00000315--4742c01c35--0'])
      self.assertEqual((items[0][0] / 'rlog.zst').read_bytes(),b'original')


if __name__ == '__main__':unittest.main()
