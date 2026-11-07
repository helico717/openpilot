## 2026-11-04 — Charging record quality CI passed

- Published code27e02e26baa3c905f6de484fa501912ab2404639 on carrot-wip-model_selector-ha. Dedicated Linux charging-record CI41765211369 completed success: https://github.com/helico717/openpilot/actions/runs/41765211369 . Remote SHA matched before recording this result.
- Existing unrelated camera2/sync1 desktop failures remain documented separately. Companion report/HA reason preservation published as carrot-ha06cbfc5; home VPN unavailable, so HA direct application and owner vehicle Git Pull/reboot remain pending. No IQ publication, vehicle source SSH/SCP edits, reboot or release.

## 2026-11-04 — Charge completeness: normal departure and missing measurements

- User request: preserve a normal charge-to-drive boundary as complete; use partial only for missing/invalid collection evidence and explain its cause. Legacy energy-led collector could mark a normal departure partial before closing a session; current CAN-led recorder already avoids that condition.
- Add deduplicated partial_reasons and detect measurement gaps across collector downtime/restarts even without update(None). Same-mode reconstructed gaps remain unknown time and partial, not confirmed collection. Track missing battery energy separately from stable quantized energy. Preserve driving boundaries and never credit a driving energy sample.
- Files: openpilot/selfdrive/carrot/ha/charge_recorder.py and tests/test_charge_quality.py. Companion carrot-ha preserves reason metadata and provides a historical replay report/tool. User confirmed carrot-wip-model_selector-ha (not IQpilot). Charge tests20 + existing CAN recorder9 + polling4 pass. Full121 tests:118 pass; camera2/sync1 failures also reproduce on the unchanged HEAD baseline. Actual archive replay26 sessions preserves energy; five old partial flags reproduce the normal-departure pattern; archive-only gaps remain inconclusive. No vehicle edits/install/reboot. Git-only publication pending.

# Changelog

## 2026-11-07 — Separate ID.4 road recognized and enforcement ahead notices

- Request: valid external road limits should briefly show recognized even with ACC
  inactive; camera/section warnings should show ahead with their own original limit.
- Add independent display fields through navigation producer, cereal, controls and
  HUD. Keep initial/fallback/stale road values out, classify enforcement separately,
  preserve raw signs without control factors, and expire hidden road changes.
- Road banner40 HUD frames (~2.4s), no inactive control icon; real ACC status and
  steering/longitudinal commands unchanged. No Panda/forwarding changes.
- Optional MK1 parked probe: primary text36/44/45 only, P/near-zero speed/inactive
  ACC+lateral/fault/event guards,2s expiry, boot binding, matched status, cancellation.
  No live request sent; software packing is not vehicle rendering confirmation.
- Files: navigation_hud, carrot_serv, custom/car schemas, controlsd, MEB controller/
  packer/probe, focused tests, sync regression gate, CI and docs/id4_speed_notices_20261107.md.
- Validation: local20 tests (6 existing+11 new+3 real schema/DBC), including20 real DBC/state/
  event combinations and6 exact-bit probe/restore combinations, schema roundtrips,
  Python syntax and Git whitespace checks pass. Dedicated Linux CI added.
  Vehicle installation/rendering remains pending.
- Delivery: Git-only carrot-wip-model_selector-ha publication; user pull/reboot.
  No device source copying, physical CAN test or reboot by the agent.


## 2026-11-03 — Full 4-bit LDW_Texte experiment range

- User clarified that1..9 was illustrative and explicitly requested all raw values0..15. Added text0..text15 as individual profiles;0 is neutral,4/8 defined warnings, other meanings unverified.
- Same1s default expiry, restoration and existing-warning preservation. No automatic sweep, CAN ID/control/Panda changes, or startup request.
- Validation:10 focused real-DBC tests now cover all22 profiles and exact text range0..15; CLI list and diff checks pass. No additional vehicle trial performed. Docs-Not-Needed: internal operator experiment without settings changes.

## 2026-11-03 — Explore user-selected LDW_Texte values

- User explicitly authorized adding raw values1,2,3,5,6,7,9 to the existing one-field display experiment after warning8/4 worked and three left-field trials showed no visible response. Meanings remain unknown on MEB; do not label these as navigation presets.
- Added exactly seven allowlisted profiles; same1s default expiry and normal restoration. No generic numeric send, automatic sweep, new CAN IDs, Panda or control changes.
- Validation:10 real-DBC packer tests cover all15 profiles and explicit text allowlist1..9; CLI help and syntax checked. Seven new values not yet vehicle-tested; user Git update/reboot required.
- Docs-Not-Needed: internal operator experiment; no settings/catalog changes. See docs/idlight_warning_probe_20261103.md.

## 2026-11-03 — ID.4 LDW display-field isolation probe

- User requested preparing one-field remote experiments from the working hands-on warning path, with actual transmission only after an explicit send instruction. Added an optional ID4 MK1-only existing LDW_02 packer hook and a Git-managed request/check/status/cancel CLI.
- Profiles cover defined takeover text8/text4 and separate left/right lane/warning fields. Default1s expiry restores normal generator values; no startup request, independent sender, control CAN, Panda safety or forwarding changes. Runtime state outside Git. No speed/brake gate added.
- Nine real-DBC/packer desktop tests pass, including bit-mask preservation, expiry, passive check, malformed/replay rejection and existing-warning preservation. Windows Params import shim only. Physical device installation, request handling and visible ID.Light responses remain unverified. No vehicle CAN/UDS test sent. This is cause-isolation preparation, not discovery of navigation animation IDs.
- Details: docs/idlight_warning_probe_20261103.md. Docs-Not-Needed: internal experiment without user settings/catalog changes.

## 2026-11-03 — Temporary onroad HA terminal opt-in

- User explicitly requested temporary onroad remote terminal access without speed or brake conditions for ID.Light testing.
- Added boot-scoped enable/disable/status CLI under selfdrive/carrot/ha/terminal_onroad.py; runtime state stays outside Git. Default off; reboot or disable restores offroad-only access.
- Agent reports actual offroad separately from the explicit override. Existing authentication, single-controller lease and input limits remain enforced by HA.
- Validation: 9 terminal/override tests pass on desktop. Companion HA real-WebSocket tests 5 pass. No CAN/UDS transmission, physical onroad test or device installation performed. User clean pull/reboot required; enable only after reboot.

## 2026-11-03 — ID.4 cluster display catalog

- User requested a complete explanation of the factory-cluster messages, icons,
  numeric fields, unused mappings and stock-relayed warnings, plus HA terminal update guidance.
- Added `docs/id4_cluster_display_catalog_20261103.md`, audited against runtime
  `cd5bfae1a`, MEB controller/packer/controls, values, speed table and MK1 DBC.
- Includes all primary/secondary ACC text enums as explicitly dormant protocol choices;
  separates automatic OP events from stock EA relay and unknown/unverified rendering.
- Validation: source/DBC cross-check; appendix entry counts checked programmatically;
  Markdown links and Git whitespace checked. Documentation only; no new runtime test,
  version bump, vehicle installation, restart or physical CAN transmission.
- Delivery: documentation commit on `carrot-wip-model_selector-ha`; no separate
  vehicle update required for the catalog. Remote publication verified in task report.

## 2026-11-03 — ID.4 navigation camera notice while ACC is inactive

- Request/reason: show the cluster's speed-camera/section-control "ahead" notice
  whenever valid navigation enforcement data is received, independent of ACC engagement.
- Runtime: `opendbc_repo/opendbc/car/volkswagen/carcontroller.py` now selects camera
  event 4 before the ACC active/override gate; `mebcan.py` includes its speed-limit
  enumeration in inactive states. Real ACC status/enabled flags and actuation are unchanged.
- Freshness: `openpilot/selfdrive/controls/controlsd.py` forwards camera data only
  while carrotMan is alive/valid and activeCarrot >= 2. Bump type 22 remains excluded.
  Existing navigation source timeout behavior is retained; disconnect is not instantaneous.
- Scope: existing MEB openpilot-longitudinal HUD path only. Stock longitudinal,
  passive/dashcam mode and a powered-off Comma do not acquire a new HUD transmit path.
  Road-limit "recognized" and turn/curve events retain their engagement conditions.
- Upstream preservation: `.github/scripts/sync_upstream_model_selector.sh` runs
  `tools/test_id4_navigation_hud.py` before committing/pushing an upstream merge.
  A regression aborts the merge; existing source-conflict abort behavior is retained.
- Validation: six stdlib desktop regression tests pass, including inactive/main-off,
  standby, active, override, fault status, clearing, camera priority, other-event gating,
  stock-longitudinal exclusion and stale/invalid navigation. Reverting each of the three
  runtime files separately makes the regression suite fail. Python AST parsing,
  bash syntax and Git whitespace checks pass. Isolated Git integration fixtures verify
  successful preservation, regression abort and source-conflict abort (3/3).
- Test limits: production controller/packer-value code runs with hardware/native imports
  substituted; native CAN binary encoding and physical cluster rendering are unverified.
- Deployment artifact: Git source commit on `carrot-wip-model_selector-ha`. Vehicle
  installation remains pending; no live file changes, CAN transmission or reboot.
  User applies Git pull/reboot; remote publication is verified in the task report.
