"""Explicit parked TM_01 experiment. No daemon, automatic wake frame or retry."""
from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import re
import time

ROOT = Path('/data/carrot_ha/tm01-trial')
MODE = 35


def payload(action):
  if action not in ('lock', 'unlock'):
    raise ValueError('Unknown action')
  return bytes(6) + bytes([2 if action == 'lock' else 4, 0])


def lock_observation(data):
  if len(data) != 8:
    return None
  v = int.from_bytes(data, 'little')
  return bool((v >> 17) & 1) if (v >> 54) & 1 else None


def model_number(state):
  return int(state.safetyModel.raw)


def require_panda(sm, bus, expected, check_bus=True):
  if not sm.valid['pandaStates'] or time.monotonic() - sm.recv_time['pandaStates'] > 1:
    raise RuntimeError('panda_status_stale')
  states = sm['pandaStates']
  if len(states) != 1:
    raise RuntimeError('single_panda_required')
  p = states[0]
  if str(p.pandaType) != 'cuatro' or p.ignitionLine or p.ignitionCan or p.controlsAllowed or list(p.faults) or p.heartbeatLost:
    raise RuntimeError('parked_panda_guard_failed')
  if model_number(p) not in expected:
    raise RuntimeError('unexpected_safety_mode_or_firmware_not_installed')
  h = getattr(p, 'canState'+str(bus))
  if check_bus and (h.busOff or h.errorWarning or h.errorPassive):
    raise RuntimeError('selected_can_bus_error')
  if Path('/data/params/d/IsOnroad').read_text() != '0':
    raise RuntimeError('vehicle_not_offroad')
  if sm.updated['carState'] and sm.valid['carState']:
    cs = sm['carState']
    if str(cs.gearShifter) != 'park' or abs(cs.vEgo) > .01:
      raise RuntimeError('fresh_vehicle_state_not_parked')
  return p


def execute(action, bus, nonce, observe_only=False):
  from openpilot.cereal import car, messaging
  from openpilot.selfdrive.pandad import can_list_to_can_capnp
  # Cached identity identifies the intended vehicle, not its present lock/gear state.
  with car.CarParams.from_bytes(Path('/data/params/d/CarParamsPersistent').read_bytes()) as cp:
    if cp.carFingerprint != 'VOLKSWAGEN_ID4_MK1':
      raise RuntimeError('id4_mk1_required')
  sm = messaging.SubMaster(['pandaStates', 'carState'])
  can = messaging.sub_sock('can')
  result = {'action': action, 'bus': bus, 'signature_hypothesis': 'Init_zero',
            'authorization_verified': False, 'request_accepted': None, 'physical_delivery_verified': False,
            'published_requests': 0, 'tx_echo_requests': 0, 'rejected_frames': 0,
            'frames_before_enable': 0, 'frames_receive_only': 0, 'frames_after_request': 0,
            'lock_before': None, 'lock_after': None, 'restored': False}
  phase = 'frames_before_enable'
  expected_payload = payload(action)

  def sample(seconds, modes, require_active=False):
    deadline = time.monotonic()+seconds
    latest = None
    while time.monotonic() < deadline:
      sm.update(0)
      latest = require_panda(sm, bus, modes, check_bus=phase == 'frames_after_request')
      if require_active and (latest.powerSaveEnabled or model_number(latest) != MODE or latest.safetyParam != bus):
        raise RuntimeError('trial_policy_not_active')
      # Bound drain work so a busy bus cannot postpone the trial's deadline.
      for _ in range(100):
        msg = messaging.recv_one_or_none(can)
        if msg is None:
          break
        for f in msg.can:
          src, data = int(f.src), bytes(f.dat)
          if src in (0, 1, 2):
            result[phase] += 1
            if int(f.address) == 0x583:
              state = lock_observation(data)
              if state is not None:
                result['lock_after' if phase == 'frames_after_request' else 'lock_before'] = state
          if phase == 'frames_after_request' and result['published_requests'] and int(f.address) == 0x5A7 and data == expected_payload:
            if src == bus+128:
              result['tx_echo_requests'] += 1
            elif src in (bus+192, bus+64):
              result['rejected_frames'] += 1
      time.sleep(.02)
    return latest

  def lease(transmit, seconds):
    now = time.clock_gettime(time.CLOCK_BOOTTIME)
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    tmp = ROOT/'lease.tmp'
    tmp.write_text(f'{boot} {nonce} {now:.6f} {now+seconds:.6f} {bus} {int(transmit)}\n')
    tmp.chmod(0o600)
    tmp.replace(ROOT/'lease')

  # Wait for the first status before requiring freshness. No Panda direct handle.
  sm.update(1500)
  for _ in range(20):
    if sm.valid['pandaStates'] and len(sm['pandaStates']):
      break
    sm.update(100)
  try:
    sample(1, {19})
    lease(False, 12)
    phase = 'frames_receive_only'
    p = sample(2, {19})
    if p.powerSaveEnabled:
      raise RuntimeError('receive_path_not_activated_update_pandad')
    if not observe_only:
      require_panda(sm, bus, {19})
      publisher = messaging.pub_sock('sendcan')
      lease(True, 8)
      # Policy handshake; waiting does not publish CAN.
      deadline = time.monotonic()+1.5
      while True:
        sm.update(100)
        p = require_panda(sm, bus, {19, MODE})
        if model_number(p) == MODE and p.safetyParam == bus and not p.powerSaveEnabled:
          break
        if time.monotonic() > deadline:
          raise RuntimeError('trial_policy_handshake_timeout')
      phase = 'frames_after_request'
      for _ in range(3):
        sm.update(0)
        require_panda(sm, bus, {MODE})
        publisher.send(can_list_to_can_capnp([(0x5A7, expected_payload, bus)], 'sendcan'))
        result['published_requests'] += 1
        sample(1, {MODE}, True)
      publisher.send(can_list_to_can_capnp([(0x5A7, bytes(8), bus)], 'sendcan'))
      sample(.2, {MODE}, True)
      # Receive feedback while leaving request transmission disabled.
      lease(False, 5)
      sample(2, {MODE, 19})
  except Exception as exc:
    result['error'] = str(exc)[:160]
  finally:
    (ROOT/'lease').unlink(missing_ok=True)
    # Wait for actual policy and power-save restoration, no forced API writes.
    deadline = time.monotonic()+2
    while time.monotonic() < deadline:
      sm.update(100)
      states = sm['pandaStates']
      if (sm.valid['pandaStates'] and time.monotonic()-sm.recv_time['pandaStates'] < 1
          and len(states) == 1 and model_number(states[0]) == 19 and states[0].powerSaveEnabled):
        result['restored'] = True
        result['restored_to'] = 'noOutput_power_save'
        break
      if (sm.valid['pandaStates'] and time.monotonic()-sm.recv_time['pandaStates'] < 1
          and len(states) == 1 and model_number(states[0]) == 34
          and (states[0].ignitionCan or states[0].ignitionLine)):
        result['restored'] = True
        result['restored_to'] = 'normal_vehicle_policy'
        break
    # Additional feedback after restore may arrive, but must not imply CAN TX.
    if result['published_requests'] and 'error' not in result:
      try:
        sample(3, {19})
      except Exception as exc:
        result['feedback_error'] = str(exc)[:160]
  if 'error' in result:
    result['status'] = 'blocked'
  elif observe_only:
    result['status'] = 'receive_only_completed'
  elif result['lock_after'] is (action == 'lock'):
    result['status'] = 'lock_transition_observed' if result['lock_before'] is not None and result['lock_before'] != result['lock_after'] else 'target_state_observed'
  elif result['tx_echo_requests']:
    result['status'] = 'panda_echo_no_target_state'
  else:
    result['status'] = 'published_delivery_unconfirmed'
  if not result['restored']:
    result['status'] = 'restoration_unconfirmed'
  return result


def main():
  p = argparse.ArgumentParser(description=__doc__)
  p.add_argument('--action', choices=('lock', 'unlock'), required=True)
  p.add_argument('--bus', type=int, choices=(0, 1, 2), default=0)
  p.add_argument('--request-id', required=True)
  p.add_argument('--observe-only', action='store_true')
  p.add_argument('--confirm-parked-trial', action='store_true')
  args = p.parse_args()
  if not re.fullmatch('[0-9a-f]{32}', args.request_id):
    p.error('Invalid request id')
  result = {'status': 'blocked', 'error': 'explicit_parked_confirmation_required'}
  if args.confirm_parked_trial:
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (ROOT/'run.lock').open('a') as lock:
      try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = execute(args.action, args.bus, args.request_id, args.observe_only)
      except Exception as exc:
        result = {'status': 'blocked', 'error': str(exc)[:160]}
      result['request_id'] = args.request_id
      (ROOT/'last_result.json').write_text(json.dumps(result))
  print('TM01_RESULT '+args.request_id+' '+json.dumps(result), flush=True)


if __name__ == '__main__':
  main()
