# ID.4 TM_01 parked experiment — 2026-11-11

Owner explicitly requests lock/unlock trial preparation for an already powered Comma
with sleeping vehicle CAN. HA exposes separate test buttons; no trial runs at install,
startup, reconnect or integration reload. This is an experimental signature-Init=0
hypothesis, not a validated remote locking implementation or wake protocol.

## Execution

HA Carrot HA -> device **시험용 기능** -> **잠금 요청** / **잠금해제 요청**.
Administrator direct service context is required. The existing reverse terminal must
be connected/offroad/ready and have no active session or controller. No other admin
session is taken over. One press invokes one fixed Git-managed command; cooldown15s.
No automatic retry, second-bus sweep, signature search, key emulation, UDS, remote
climate action, firmware flashing or reboot is performed by the button.

The Git-managed CLI is `python3 -m openpilot.selfdrive.debug.tm01_trial`.
Only explicit `--confirm-parked-trial` executes; `--observe-only` activates the
receive path without application CAN requests. HA's first trial fixes bus0, where
TM_01 has been observed historically; this is NOT proof of the native OCU/source
network. CLI bus1/2 require a separate explicit invocation, never automatic fallback.

The owner must keep the car parked, have the physical key outside the car, and
avoid touching the key/door handles during observation to distinguish causal wake.
No movement/ACC/steering control is requested. Existing CAN wiring stays unchanged.

## Layered bounds

- A boot-ID/nonce-bound `/data/carrot_ha/tm01-trial/lease` expires within12s. Read
  is bounded, nonblocking, regular-file-only and no symlink. No source/state in Git.
- pandad remains the single Panda owner. Single Panda, offroad, ignition false,
  no faults, controls disallowed and normal noOutput/explicit trial mode are required.
  The receiver-only phase temporarily enables transceivers while preserving noOutput.
- Before TX, the selected bus must have no active bus-off/error-warning/error-passive.
  Cached Park/lock state is never interpreted as fresh. Any fresh non-Park/moving
  carState, ignition, policy change or stale Panda status interrupts the trial.
- New CAN-FD-board safety mode35 has no forwarding and retains the closed stock
  relay. It permits ONLY standard8-byte0x5A7, selected bus, zero other fields,
  bit49(lock) OR bit50(unlock), signature Init0, at most3 same-action requests at
  >=900ms intervals within5s plus one neutral frame which terminates TX permission.
  Defaults noOutput, silent, ELM327 and normal MEB allowlists remain unchanged.
- The H7 driver forces Classic CAN/noBRS only in trial mode, preventing automatic
  FD conversion. Entry/exit discards pending software TX and reinitializes CAN.
  Limits refer to admitted host requests, NOT independently measured wire attempts;
  the CAN controller's normal arbitration/retransmission behavior is not proof of ACK.
- Cleanup removes the lease and observes actual noOutput/power-save return; if the
  car legitimately becomes onroad it verifies return to normal MEB policy instead.
  Firmware TX expiry and normal heartbeat fallback still apply if the CLI dies.
  No allOutput, stopping pandad, fake onroad or broad diagnostic permissions.

## Interpretation

Panda returned frames are emitted when the hardware TX slot is queued, before
independent ECU acceptance/ACK proof. They MUST NOT be called physical delivery.
The result separately records request publication, exact returned/rejected frames,
CAN counts before enable/receive-only/after request, available ZV_02 actual external
lock state, and policy restoration. No baseline or already-correct target gives
`target_state_observed`, never a command-success claim. Even a lock transition is
an observation requiring owner confirmation; request_accepted remains null.
No response cannot distinguish Init authentication rejection, incorrect source bus,
unsupported firmware feature or missing vehicle wake. It does not prove impossible.

## Verification and installation

Local actual safety-hook/native lease checks5pass; CLI semantic/guard checks3pass;
companion HA transport checks3pass. Full Linux pandad/schema and H7/F4 firmware
compilation are required in `.github/workflows/tm01-trial.yml` before declaring
installable. No physical TX/wake/lock/unlock has occurred during preparation.

User-only installation: `cd /data/openpilot && git pull --ff-only && sudo reboot`.
This update changes Panda firmware sources; normal Git startup may rebuild/flash
its matching firmware. HA code is separately backed up/directly deployed, user
restarts HA. No HACS tag/release is authorized by this feature request.
