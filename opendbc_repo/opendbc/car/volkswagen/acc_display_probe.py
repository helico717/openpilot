"""Park-only, expiring ACC display experiments through the existing HUD publisher.

CLI: check | status | request overspeed|signal-vertical|signal-horizontal | cancel.
Packed is software evidence, never proof of bus delivery or cluster rendering.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time
import uuid

ROOT = Path('/data/carrot_ha/acc-display-probe')
BOOT = Path('/proc/sys/kernel/random/boot_id')
PROFILES = {'overspeed': 36, 'signal-vertical': 44, 'signal-horizontal': 45}


def write_json(path, value):
  path.parent.mkdir(parents=True, exist_ok=True)
  temporary = path.with_suffix('.tmp')
  temporary.write_text(json.dumps(value, sort_keys=True) + '\n')
  temporary.replace(path)


class AccDisplayProbe:
  def __init__(self, root=ROOT, boot_path=BOOT, clock=time.monotonic_ns):
    self.root, self.clock = root, clock
    try:
      self.boot = boot_path.read_text().strip()
    except OSError:
      self.boot = ''
    self.seen = None
    self.active = None
    self.status = None
    self.phase = None

  def apply(self, values, parked):
    now = self.clock()
    try:
      request = json.loads((self.root / 'request.json').read_text())
    except (OSError, ValueError):
      request = None
    if isinstance(request, dict) and request.get('id') != self.seen:
      self.seen = request.get('id')
      self.active = None
      self.status = {'id': self.seen, 'profile': request.get('profile'), 'candidate_frames': 0,
                     'hardware_transmission_confirmed': False}
      issued, expires = request.get('issued_ns'), request.get('expires_ns')
      valid = (isinstance(self.seen, str) and bool(self.seen) and bool(self.boot)
               and request.get('boot_id') == self.boot and type(issued) is int and type(expires) is int
               and issued <= now < expires and 0 < expires - issued <= 2_000_000_000)
      if not valid:
        self.phase = 'rejected_normal_packed'
      elif request.get('cancel') is True:
        self.phase = 'cancelled_normal_packed'
      elif request.get('observe') is True:
        self.phase = 'observed_normal_packed'
      elif isinstance(request.get('profile'), str) and request['profile'] in PROFILES:
        self.active = request
      else:
        self.phase = 'rejected_normal_packed'
    if self.active is None:
      return values
    if now >= self.active['expires_ns']:
      self.active = None
      self.phase = 'expired_normal_packed'
      return values
    # Abort instead of hiding an independent warning or navigation event.
    if (not parked or values['ACC_Status_ACC'] not in (0, 2)
        or any(values.get(field, 0) for field in ('ACC_Events', 'ACC_Texte_Primaeranz_02',
                                                'ACC_Texte_Zusatzanz_02', 'ACC_Optischer_Fahrerhinweis',
                                                'ACC_Akustischer_Fahrerhinweis'))):
      self.active = None
      self.phase = 'aborted_normal_packed'
      return values
    self.phase = 'candidate_packed'
    # One defined text field only. Never ACC_Regelung_AIO or any control/status/sound field.
    return {**values, 'ACC_Texte_Primaeranz_02': PROFILES[self.active['profile']]}

  def packed(self, message):
    if self.phase is None or self.status is None:
      return
    address, payload, bus = message
    phase, self.phase = self.phase, None
    if address != 0x300 or bus != 0 or len(payload) != 48:
      self.active = None
      phase = 'unexpected_frame'
    self.status.update(phase=phase, packed_at_ns=self.clock(),
                       candidate_frames=self.status['candidate_frames'] + int(phase == 'candidate_packed'))
    try:
      write_json(self.root / 'status.json', self.status)
    except OSError:
      pass


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  commands = parser.add_subparsers(dest='action', required=True)
  for name in ('check', 'status', 'cancel'):
    commands.add_parser(name)
  request = commands.add_parser('request')
  request.add_argument('profile', choices=tuple(PROFILES))
  args = parser.parse_args()
  if args.action == 'status':
    path = ROOT / 'status.json'
    print(path.read_text() if path.exists() else 'No ACC display request handled')
    return
  now = time.monotonic_ns()
  data = {'id': str(uuid.uuid4()), 'boot_id': BOOT.read_text().strip(),
          'issued_ns': now, 'expires_ns': now + 2_000_000_000}
  if args.action == 'request':
    data['profile'] = args.profile
  else:
    data['observe' if args.action == 'check' else 'cancel'] = True
  write_json(ROOT / 'request.json', data)
  print(json.dumps({'id': data['id'], 'state': 'queued_locally', 'hardware_transmission_confirmed': False}))


if __name__ == '__main__':
  main()
