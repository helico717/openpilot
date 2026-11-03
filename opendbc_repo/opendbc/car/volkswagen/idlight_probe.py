"""Explicit one-field LDW display experiments. No independent CAN sender.

Run this Git-managed file directly: status | check | request <profile> | cancel.
A running ID.4 MK1 controller consumes a request; otherwise it expires unused.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time
import uuid

ROOT = Path("/data/carrot_ha/idlight-probe")
BOOT = Path("/proc/sys/kernel/random/boot_id")
PROFILES = {
  # User-authorized full 4-bit exploration; only 0/4/8 have defined MEB meanings.
  **{f"text{value}": {"LDW_Texte": value} for value in range(16)},
  "left3": {"LDW_Lernmodus_links": 3},
  "right3": {"LDW_Lernmodus_rechts": 3},
  "sw-left": {"LDW_SW_Warnung_links": 1},
  "sw-right": {"LDW_SW_Warnung_rechts": 1},
  "warn-left": {"LDW_Warnung_links": 1},
  "warn-right": {"LDW_Warnung_rechts": 1},
}


def atomic_json(path, data):
  path.parent.mkdir(parents=True, exist_ok=True)
  temporary = path.with_suffix(".tmp")
  temporary.write_text(json.dumps(data, sort_keys=True) + "\n")
  temporary.replace(path)


class DisplayProbe:
  def __init__(self, root=ROOT, boot_path=BOOT, clock=time.monotonic_ns):
    self.root, self.clock = root, clock
    try:
      self.boot_id = boot_path.read_text().strip()
    except OSError:
      self.boot_id = ""
    self.request_id = None
    self.active = None
    self.report = None
    self.pending_report = None

  def publish(self, phase, **fields):
    if self.report is None:
      return
    self.report.update(phase=phase, **fields)
    try:
      atomic_json(self.root / "status.json", self.report)
    except OSError:
      pass  # Telemetry failure must never stop the vehicle controller.

  def apply(self, values):
    now = self.clock()
    try:
      data = json.loads((self.root / "request.json").read_text())
    except (OSError, ValueError):
      data = None
    if isinstance(data, dict) and data.get("id") != self.request_id:
      self.request_id = data.get("id")
      self.active = None
      self.report = {"id": self.request_id, "profile": data.get("profile"), "packed_frames": 0}
      issued, expires = data.get("issued_ns"), data.get("expires_ns")
      valid = (isinstance(self.request_id, str) and bool(self.request_id) and self.boot_id
               and data.get("boot_id") == self.boot_id
               and type(issued) is int and type(expires) is int
               and issued <= now < expires and 0 < expires - issued <= 2_000_000_000)
      if not valid:
        self.publish("rejected", reason="invalid_or_expired_request")
      elif data.get("observe") is True:
        self.pending_report = "observed_normal_packed"
      elif data.get("cancel") is True:
        self.pending_report = "cancelled_normal_packed"
      elif not isinstance(data.get("profile"), str) or data["profile"] not in PROFILES:
        self.publish("rejected", reason="unknown_profile")
      else:
        self.active = data
    if self.active is None:
      return values
    if now >= self.active["expires_ns"]:
      self.active = None
      self.pending_report = "expired_normal_packed"
      return values
    # Do not mask an independently occurring real HUD warning during isolation.
    if values.get("LDW_Texte", 0) != 0:
      self.active = None
      self.pending_report = "aborted_existing_warning_normal_packed"
      return values
    result = dict(values)
    result.update(PROFILES[self.active["profile"]])
    self.pending_report = "candidate_packed"
    return result

  def packed(self, message):
    if self.pending_report is None:
      return
    address, payload, bus = message
    if address != 0x397 or bus != 0 or len(payload) != 8:
      self.active = None
      self.pending_report = None
      self.publish("rejected", reason="unexpected_frame")
      return
    phase, self.pending_report = self.pending_report, None
    count = self.report["packed_frames"] + (phase == "candidate_packed")
    self.publish(phase, packed_frames=count, packed_at_ns=self.clock(),
                 can_id=address, bus=bus, payload_hex=bytes(payload).hex(),
                 hardware_transmission_confirmed=False)


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  commands = parser.add_subparsers(dest="action", required=True)
  commands.add_parser("status")
  commands.add_parser("cancel")
  commands.add_parser("check")
  request = commands.add_parser("request")
  request.add_argument("profile", choices=tuple(PROFILES))
  request.add_argument("--duration", type=float, default=1.0)
  args = parser.parse_args()
  if args.action == "status":
    path = ROOT / "status.json"
    print(path.read_text() if path.exists() else "No display probe has been handled by the controller")
    return
  duration = args.duration if args.action == "request" else 1.0
  if not 0.1 <= duration <= 2.0:
    parser.error("duration must be between 0.1 and 2 seconds")
  now = time.monotonic_ns()
  data = {"id": str(uuid.uuid4()), "boot_id": BOOT.read_text().strip(),
          "issued_ns": now, "expires_ns": now + int(duration * 1e9)}
  if args.action == "check":
    data["observe"] = True
  elif args.action == "cancel":
    data["cancel"] = True
  else:
    data["profile"] = args.profile
  atomic_json(ROOT / "request.json", data)
  print(json.dumps({"request_id": data["id"], "state": "queued_locally", "duration": duration,
                    "hardware_transmission_confirmed": False}))


if __name__ == "__main__":
  main()
