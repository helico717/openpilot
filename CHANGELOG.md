# Changelog

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
