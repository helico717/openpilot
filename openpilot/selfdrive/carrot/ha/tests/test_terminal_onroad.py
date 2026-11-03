import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from openpilot.selfdrive.carrot.ha.terminal_onroad import enabled, set_enabled
from openpilot.selfdrive.carrot.ha.terminal import TerminalAgent


class OnroadAccessTest(unittest.TestCase):
  def test_default_enable_disable_and_reboot(self):
    with tempfile.TemporaryDirectory() as root:
      state, boot = Path(root) / "state.json", Path(root) / "boot"
      boot.write_text("boot-a")
      self.assertFalse(enabled(state, boot))
      set_enabled(True, state, boot)
      self.assertTrue(enabled(state, boot))
      boot.write_text("boot-b")
      self.assertFalse(enabled(state, boot))
      set_enabled(True, state, boot)
      set_enabled(False, state, boot)
      self.assertFalse(enabled(state, boot))

  def test_malformed_and_missing_boot_fail_closed(self):
    with tempfile.TemporaryDirectory() as root:
      state, boot = Path(root) / "state.json", Path(root) / "boot"
      state.write_text("[]")
      boot.write_text("boot-a")
      self.assertFalse(enabled(state, boot))
      state.write_text("invalid")
      self.assertFalse(enabled(state, boot))
      boot.unlink()
      self.assertFalse(enabled(state, boot))

  def test_agent_uses_override_without_falsifying_offroad(self):
    with patch("openpilot.selfdrive.carrot.ha.terminal.is_offroad", return_value=False), patch("openpilot.selfdrive.carrot.ha.terminal_onroad.enabled", return_value=True):
      agent = TerminalAgent()
      self.assertFalse(agent.offroad_status())
      self.assertTrue(agent.status())
      agent.onroad_override = lambda: False
      self.assertFalse(agent.status())


if __name__ == "__main__":
  unittest.main()
