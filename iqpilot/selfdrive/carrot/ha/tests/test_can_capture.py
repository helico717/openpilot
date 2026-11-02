import gzip
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

path=Path(__file__).resolve().parents[1]/'can_capture.py'
spec=importlib.util.spec_from_file_location('can_capture',path)
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

class CaptureTests(unittest.TestCase):
 def test_wire_preserves_all_buses_and_context(self):
  frames=[[123,1,0,'0011'],[124,2,1,'ff'],[125,3,2,'']]
  body=json.loads(gzip.decompress(c.encode_batch('car','a'*32+'-0000000001',frames,{'charging':True})))
  self.assertEqual(body['frames'],frames);self.assertTrue(body['context']['charging'])
  self.assertIsInstance(body['unix_ns'],int);self.assertIsInstance(body['boot_ns'],int)
 def test_disk_queue_survives_restart_and_records_overflow(self):
  with tempfile.TemporaryDirectory() as root:
   client=c.CaptureClient({'device':'car'},root,lambda:{})
   frames=[[1,1,0,'00']];client.save(frames)
   again=c.CaptureClient({'device':'car'},root,lambda:{})
   self.assertEqual(len(again.pending),1)
   previous=c.MAX_SPOOL;c.MAX_SPOOL=0
   try:again.save(frames)
   finally:c.MAX_SPOOL=previous
   self.assertEqual(again.dropped,1);self.assertEqual(len(again.pending),1)
 def test_large_batch_splits_without_losing_frames(self):
  with tempfile.TemporaryDirectory() as root:
   client=c.CaptureClient({'device':'car'},root,lambda:{})
   frames=[[i,1,0,'00'] for i in range(30001)];client.save(frames)
   recovered=[]
   for p in client.pending:recovered.extend(json.loads(gzip.decompress(p.read_bytes()))['frames'])
   self.assertEqual(recovered,frames)
