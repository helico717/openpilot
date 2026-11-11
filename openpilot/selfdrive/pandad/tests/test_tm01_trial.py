"""Compile and exercise actual firmware hooks and pandad lease parser, no CAN IO."""
import ctypes
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]


class FirmwarePolicyTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.tmp = tempfile.TemporaryDirectory()
    source = Path(cls.tmp.name)/'harness.c'
    source.write_text('''#include <stdbool.h>
bool safety_tx_buffered_for_fwd = false;
#include "fake_stm.h"
#include "can.h"
#include "faults.h"
#include "safety.h"
void trial_time(uint32_t t) { timer.CNT = t; }
bool trial_send(int addr, int bus, int len, uint64_t data, int fd, int ext) {
  CANPacket_t p = {.addr=addr, .bus=bus, .data_len_code=len, .fd=fd, .extended=ext};
  for (int i=0; i<8; i++) p.data[i]=(data >> (i*8)) & 255;
  return safety_tx_hook(&p);
}
bool trial_controls(void) { return controls_allowed; }
int trial_forward(void) { CANPacket_t p={.addr=0x123,.bus=0}; return safety_fwd_hook(&p); }
''')
    so = Path(cls.tmp.name)/'hooks.so'
    subprocess.run(['cc','-shared','-fPIC','-std=gnu11','-Wall','-Werror','-Wno-pointer-to-int-cast',
                    '-I'+str(ROOT/'panda/board'), '-I'+str(ROOT/'opendbc_repo/opendbc/safety'),
                    str(source),'-o',str(so)],check=True,capture_output=True)
    cls.lib=ctypes.CDLL(str(so))
    cls.lib.trial_send.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint64,ctypes.c_int,ctypes.c_int]
    cls.lib.trial_send.restype=ctypes.c_bool
    cls.lib.trial_time.argtypes=[ctypes.c_uint32]
    cls.lib.trial_controls.restype=ctypes.c_bool

  @classmethod
  def tearDownClass(cls):cls.tmp.cleanup()

  def reset(self,bus=0,t=0):
    self.lib.trial_time(t)
    self.assertEqual(self.lib.set_safety_hooks(35,bus),0)

  def tx(self,data=2<<48,bus=0,addr=0x5a7,length=8,fd=0,ext=0):
    return self.lib.trial_send(addr,bus,length,data,fd,ext)

  def test_request_budget_same_action_release_and_terminal_stop(self):
    for action in (2,4):
      self.reset()
      for i in range(3):
        self.lib.trial_time(i*1000000)
        self.assertTrue(self.tx(action<<48))
      self.lib.trial_time(3000000)
      self.assertFalse(self.tx(action<<48))
      self.assertTrue(self.tx(0))
      self.assertFalse(self.tx(0))
      self.assertFalse(self.tx(action<<48))
      self.assertFalse(self.lib.trial_controls())
      self.assertEqual(self.lib.trial_forward(),-1)

  def test_wrong_id_bus_dlc_format_and_every_unrelated_bit_denied(self):
    for bus in range(3):
      self.reset(bus)
      for wrong in set(range(4))-{bus}:self.assertFalse(self.tx(bus=wrong))
      for addr in (0x303,0x14d,0x300,0x700,0x366):self.assertFalse(self.tx(addr=addr,bus=bus))
      for length in (0,7,9,15):self.assertFalse(self.tx(length=length,bus=bus))
      self.assertFalse(self.tx(fd=1,bus=bus))
      self.assertFalse(self.tx(ext=1,bus=bus))
      for bit in range(64):
        if bit not in (49,50):self.assertFalse(self.tx((2<<48)|(1<<bit),bus=bus))
      self.assertFalse(self.tx(6<<48,bus=bus))
      self.assertTrue(self.tx(bus=bus))
    self.reset(3)
    self.assertFalse(self.tx())

  def test_timeout_rate_action_change_and_timer_wrap(self):
    self.reset()
    self.assertTrue(self.tx())
    self.lib.trial_time(899999)
    self.assertFalse(self.tx())
    self.lib.trial_time(1000000)
    self.assertFalse(self.tx(4<<48))
    self.lib.trial_time(5000000)
    self.assertFalse(self.tx())
    self.assertFalse(self.tx(0))
    self.reset(t=0xfffffff0)
    self.lib.trial_time(0x00000020)
    self.assertTrue(self.tx())

  def test_default_modes_stay_unchanged(self):
    for mode in (0,19):
      self.lib.set_safety_hooks(mode,0)
      self.assertFalse(self.tx())
    self.lib.set_safety_hooks(3,1)
    self.assertFalse(self.tx())
    self.assertTrue(self.tx(addr=0x700))


class LeaseTests(unittest.TestCase):
  def test_native_boot_expiry_and_corruption_guards(self):
    with tempfile.TemporaryDirectory() as d:
      source=Path(d)/'lease.cc'; binary=Path(d)/'lease'
      source.write_text('''#include <cassert>
#include "selfdrive/pandad/tm01_trial.h"
int main() {
  using tm01_trial::parse;
  const std::string nonce="0123456789abcdef0123456789abcdef";
  assert(parse("boot "+nonce+" 10 20 0 1","boot",11).valid);
  assert(!parse("boot "+nonce+" 10 20 0 1","other",11).valid);
  assert(!parse("boot "+nonce+" 10 20 0 1","boot",20).valid);
  assert(!parse("boot "+nonce+" 10 23 0 1","boot",11).valid);
  assert(!parse("boot "+nonce+" 12 20 0 1","boot",11).valid);
  assert(!parse("boot "+nonce+" 10 20 3 1","boot",11).valid);
  assert(!parse("boot "+nonce+" 10 20 0 2","boot",11).valid);
  assert(!parse("boot "+nonce+" 10 20 0 1 extra","boot",11).valid);
  assert(!parse("boot short 10 20 0 1","boot",11).valid);
  assert(!parse("boot "+nonce+" nan 20 0 1","boot",11).valid);
  assert(!parse("", "boot",11).valid);
  assert(!parse("boot "+nonce+" 10 20 0 0","boot",11).transmit);
}
''')
      subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-I'+str(ROOT/'openpilot'),str(source),'-o',str(binary)],check=True,capture_output=True)
      subprocess.run([str(binary)],check=True)


if __name__=='__main__':unittest.main()
