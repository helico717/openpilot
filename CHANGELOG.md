# Personal IQpilot HA candidate

## 2026-11-02 — Initial installation candidate

- Pinned IQpilot release 5c9291b9df6d90007d73ecd749b135bd5008e80d as an unmodified Git submodule.
- Ported HA companion from the actual Carrot vehicle commit 5ec4868a12a9038547b373eb95be3a5fa86d30aa.
- Preserved vehicle identity/configuration and HA outbox paths outside Git; paused Carrot-only parameter writes.
- Added administrator reverse-terminal PTY without a Carrot local web server or new network listener.
- Added separate parked-camera ownership and fail-closed IQ Sentry/Live View exclusion.
- Added source/runtime diagnostics; no CAN actuation, camera startup or reboot in diagnostics.
- Vendor binaries remain in the original pinned repository; public Python sources retain the upstream license.
- Local validation: 10 source assembly checks and 35 functional checks pass. Linux CI/device/OS rollback status
  is tracked in the companion helico717/carrot-ha preparation report. No vehicle installation performed.
- Initial Linux CI exposed a test expectation for Bash bracketed-paste ANSI output; normalize terminal
  controls before checking the actual standalone output line. Git ignore files are regular tracked files.
- Stock automatic source updating is disabled; companion updates use this Git branch only.
- Finalized camera TS remux can use IQpilot's PyAV when the ffmpeg command is unavailable.

## 2026-11-02 — Carrot return readiness

- Diagnostics report read-only inactive-slot write access for the Carrot OS flasher and sudo availability.
- Added a Git-only return script to the pinned Carrot commit; it refuses onroad, local tracked
  changes, an unexpected ha-back commit and untracked collisions, and never reboots.
- Not yet tried on a device; the IQ.OS -> Carrot OS flash remains unverified.
