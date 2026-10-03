# Carrot HA charge classification correction — 2026-10-03

## Evidence

The attached HA archive shows October slow energy advancing by 25 Wh at
October 2 22:31 KST, another 25 Wh at 22:35, and 50 Wh during the October 3
15:21 fast-charge startup. The first two increments coincide with BMS readings
alternating between 63950 and 63975 Wh. The old recorder classified every
90–240-second energy window separately at an 11 kW threshold, and summed
positive changes without accounting for rebounds. HA displays that recorder ledger.

## Change

The recorder latches fast classification per inferred session once a valid
window exceeds 11 kW. It reclassifies only that session's recorded startup
contributions, including their month-specific estimated costs. Other AC sessions
are untouched. Each session retains its counted battery peak; dips and rebounds
below that value add nothing and do not extend the last-charge-increase timer.
A lone 25 Wh tail increment is held until net growth reaches 50 Wh, accounting
for 25/50 Wh CAN quantization. Small genuine increments accumulate from the last
counted peak. State persists through restart and promotion across a month boundary.
The original sampling cadence, confirmation thresholds, stale expiry, driving
interlock and cloud polling behavior are unchanged. AC/DC is still a power-based
estimate, not proof of connector type.

Legacy pending candidates without the new energy anchors are discarded. Active
legacy sessions retain their totals; their recorded average power can retain fast
evidence for future additions. Their old per-month classification cannot be
reconstructed reliably because they lack a contribution journal. No arbitrary
historical ledger rewrite is performed: the already displayed 0.1 kWh can remain.

## Validation and rollout

Nine focused tests cover fast startup promotion, unrelated AC preservation,
tapering, rebound rejection, quantized tail noise, accumulated small increases,
restart, month boundaries and legacy state. The full daemon suite runs 62 tests;
58 pass and the same four unrelated camera/terminal failures seen before this
change remain (including system Python 3.9 lacking asyncio.timeout).
No HA runtime or Worker/schema changes are required, so no HACS release or Worker
deployment is needed. Publish through the Comma Git branch. The user applies it
only through HA remote-terminal Connect, Carrot Git Pull and device Reboot buttons.
Physical device behavior still requires post-update observation.
