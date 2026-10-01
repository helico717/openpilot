# Carrot HA daemon performance contract — 2026-10-01

This daemon belongs to helico717/openpilot, branch carrot-wip-model_selector-ha.
The user's two-repository instructions take precedence over unrelated top-level
branch-consolidation history. HA/Worker/card changes belong to helico717/carrot-ha.

- Commit-managed source only. Never patch or copy code into Comma through SSH/SCP
  or the reverse terminal. Deployment is a clean Git update and restart.
- Runtime state belongs outside the Git tree. Parameter queue ACK identities use
  /data/carrot_ha/param_sync.sqlite3; preserve old identities with the read-only
  legacy database migration. Do not erase them or reapply already handled IDs.
- Keep parameter polling at 15s idle, 3s during an expiring active-settings lease
  or pending work, with 15–120s failure backoff. Command handling precedes periodic
  catalog publication. Do not restore unconditional 3s polling to hide latency.
- Idle-to-active discovery is polling, not push: allow up to the idle interval plus
  network/processing time. Keep local validation, readback and failure ACKs; do not
  falsely report a command as applied from its requested value alone.
- CAN sampling/telemetry cadence, driving interlocks, and terminal revocation
  checks are separate correctness contracts. Do not slow them just to save requests.
- Any future optimization requires measured latency/usage evidence and relevant
  tests. The maintained design is a baseline, not proof of an absolute optimum.
- Run ha/tests/test_param_polling.py and the daemon test suite when touching this
  path. Full release validation also includes carrot-ha's incremental Worker and
  dashboard tests, D1 migration before Worker deployment, and operational 24-hour
  quota/freshness observation. Local results are not physical-device validation.
