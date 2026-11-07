# ID.4 road and enforcement notices / parked display checks — 2026-11-07

Road information is independent of ACC engagement and speed-control candidate selection.
A valid external road limit requests event 5 (recognized) for 40 HUD frames (~2.4s)
on first receipt/change. Repeated unchanged observations do not repeat it. Unknown
values reset the episode. Changes hidden by a higher-priority event age out rather
than playing an old notice after the camera/turn ends. Inactive ACC has no permanent
road-control icon. Active road-control icons and other event gates are retained.

Camera/section information uses event 4 (ahead), strict enforcement classifications,
and the original sign value, without the speed controller's safety factor/offset.
Road60 and enforcement50 therefore request ahead50. New navigation input can show
information with speed-control settings disabled; legacy raw SDI is also classified
for display independently. Bumps/other hazards do not acquire enforcement signs.
External navigation expiry and invalid/off-route v2 input clear the information.
Legacy road input must be genuinely received/accepted, younger than20s and have an
active source; initial/fallback30 is not a new road observation. Legacy decoding
and control calculations are otherwise unchanged. Powered-off/passive/stock-long
configurations do not gain a new CAN sender. Native rendering remains unverified.

## Optional parked checks (after Git update and user reboot)

These use the existing ID.4 MK1 controller and ACC HUD publisher. No standalone CAN
publisher, Panda/forwarding change, activation spoof, acceleration/steering command,
signal-control activation or sound request is introduced. Maximum2s per request;
P gear, abs speed<0.1m/s, ACC and lateral control inactive and no ACC fault required.
An existing ACC event/text/warning aborts the request. Requests expire unused if the
normal vehicle controller is not running; offroad power alone is not proof of readiness.

From the existing authorized HA terminal, in /data/openpilot:

```sh
python opendbc_repo/opendbc/car/volkswagen/acc_display_probe.py check
python opendbc_repo/opendbc/car/volkswagen/acc_display_probe.py status
```

Match the request ID and require observed_normal_packed before a candidate test.
Then choose one request at a time and observe the physical cluster:

```sh
python opendbc_repo/opendbc/car/volkswagen/acc_display_probe.py request overspeed
python opendbc_repo/opendbc/car/volkswagen/acc_display_probe.py request signal-vertical
python opendbc_repo/opendbc/car/volkswagen/acc_display_probe.py request signal-horizontal
```

These set only ACC_Texte_Primaeranz_02=36/44/45. A signal symbol does not prove
red/green direction/countdown can be controlled. No change is also a meaningful
result: check candidate_packed versus aborted/unused before interpreting rejection.
After each request require expired_normal_packed and visual restoration. `cancel`
queues immediate restoration on the next HUD cycle. Reboot/stale requests are rejected.
Packed status is software evidence, not Panda delivery or ECU acceptance proof.
Do not use the LDW ID.Light probe for these tests. The user controls installation,
reboot and whether to perform each physical display experiment.

## Validation

Stdlib production-AST tests cover old camera states and new road lifetime/priority,
input classification and probe expiry/park/warning/reboot guards. Real schema and
both MK1/MK2 DBC packer tests verify events4/5, original sign encoding, unchanged ACC
state/enabled fields, only six primary-text bits changing, and exact restoration.
Unbuilt desktop/CI environments may shim the unused Hyundai Params import only;
schema and CAN packer imports remain real on both platforms. Physical display and road behavior remain untested.
