"""Explicit, boot-scoped onroad terminal opt-in. No vehicle CAN access."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

STATE = Path("/data/carrot_ha/terminal-onroad.json")
BOOT = Path("/proc/sys/kernel/random/boot_id")


def enabled(path=STATE, boot_path=BOOT):
  try:
    boot = boot_path.read_text().strip()
    data = json.loads(path.read_text())
    return bool(boot) and isinstance(data, dict) and data.get("boot_id") == boot and data.get("enabled") is True
  except (OSError, ValueError, TypeError):
    return False


def set_enabled(value, path=STATE, boot_path=BOOT):
  if not value:
    path.unlink(missing_ok=True)
    return
  boot = boot_path.read_text().strip()
  if not boot:
    raise ValueError("boot identity unavailable")
  path.parent.mkdir(parents=True, exist_ok=True)
  temporary = path.with_suffix(".tmp")
  temporary.write_text(json.dumps({"enabled": True, "boot_id": boot}) + "\n")
  temporary.replace(path)


def main():
  parser = argparse.ArgumentParser(description="Temporary onroad HA terminal access until disabled or Comma reboots")
  parser.add_argument("action", choices=("enable", "disable", "status"))
  action = parser.parse_args().action
  if action != "status":
    set_enabled(action == "enable")
  print("onroad terminal: " + ("enabled for current boot" if enabled() else "disabled"))


if __name__ == "__main__":
  main()
