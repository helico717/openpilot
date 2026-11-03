# ID.Light warning-path isolation experiment — 2026-11-03

## Scope and authorization

The user explicitly requested preparing remote, video-observed tests from the already working hands-on warning path. This is NOT a claim of finding OEM navigation animation commands. No request is submitted automatically at startup/install. Actual candidate requests wait for the user's explicit “명령을 보내” instruction.

The ID.4 MK1 controller already generates LDW_02, CAN0, ID0x397,8B, at the existing HUD cadence. The new optional hook only overrides one allowlisted display field in this existing message. It does not create an independent CAN publisher, change HCA/ACC/EA/KLR, alter Panda safety, change forwarding, or modify DLC/TLC, vibration amplitude or timing fields. No speed/brake conditions were introduced. An independently occurring LDW_Texte warning aborts the experiment rather than masking that warning.

## Evidence and candidate order

Current carcontroller maps visualAlert steerRequired/ldw to LDW_Texte8. The DBC defines0 none,8 laneAssistTakeOver,4 laneAssistTakeOverUrgent. The user's observed ID.Light warning response has not yet been causally assigned to one field. `text8` is the initial sufficiency test; `text4` compares the second defined warning level. Other values1..3/5..7/9..15 are NOT included as undocumented animation numbers.

| Profile | Only changed field | Value | Meaning/uncertainty |
|---|---|---|---|
| text8 | LDW_Texte |8| Existing takeover warning request |
| text4 | LDW_Texte |4| Defined urgent takeover warning |
| left3 | LDW_Lernmodus_links |3| Left lane departure display state; ID.Light response unknown |
| right3 | LDW_Lernmodus_rechts |3| Right equivalent; not navigation proof |
| sw-left | LDW_SW_Warnung_links |1| Left warning bit; effect uncertain |
| sw-right | LDW_SW_Warnung_rechts |1| Right warning bit; effect uncertain |
| warn-left | LDW_Warnung_links |1| Left warning bit; effect uncertain |
| warn-right | LDW_Warnung_rechts |1| Right warning bit; effect uncertain |

Lernmodus fields are2bit (0..3). The existing control code can calculate4 in some contexts; the wire cannot contain4. This experiment uses3 and does not fix unrelated baseline calculations.

## Installation and commands

Git-only deployment on carrot-wip-model_selector-ha; user clean pull and reboot. Device source edits over SSH/SCP/terminal are prohibited. Runtime mailbox and status live under /data/carrot_ha/idlight-probe, outside Git.

Commands are run by the operator through the existing authenticated HA terminal:

```sh
cd /data/openpilot
python opendbc_repo/opendbc/car/volkswagen/idlight_probe.py status
python opendbc_repo/opendbc/car/volkswagen/idlight_probe.py check
```

`check` requests acknowledgement of an UNMODIFIED normal LDW frame from the running carcontroller. It does not request a changed display. A matching `observed_normal_packed` status verifies mailbox consumption, not physical CAN delivery. Carcontroller must actually be running; offroad without carcontroller yields no acknowledgement and expires.

After explicit user instruction ONLY:

```sh
python opendbc_repo/opendbc/car/volkswagen/idlight_probe.py request text8 --duration 1
```

Follow with `status`. `cancel` asks for normal values on the next HUD frame. Every request is boot-scoped, UUID-identified and bounded by monotonic issue/expiry timestamps; expired requests cannot be replayed. Duration default1s, supported0.1..2s. Default restores on next normal HUD frame after expiry. Disconnect alone does not stop arbitrary shell programs, but this hook does not need a persistent remote command to expire.

Reboot also resets the separate temporary onroad-terminal permission; re-enable that permission after updating.

## Observation and interpretation

1. Install and verify commit/clean tracked files. Confirm onroad terminal permission.
2. With running controller, issue check, confirm its status refers to that new request and observed_normal_packed.
3. User starts video; only on explicit send instruction issue text8 for1s.
4. Read matching candidate_packed and expired_normal_packed status; independently examine CAN TX echo/reject frames where available. `packed_frames` means generator output, NOT Panda acceptance/bus delivery/ECU effect. hardware_transmission_confirmed remainsfalse.
5. User video establishes visible response. text8 alone producing the known animation supports that field's sufficiency in that state. No response does not prove irrelevance (routing/enable/priority/delivery remain possible).
6. Compare text4, then left/right independently only after reviewing previous result. No automatic sequence or arbitrary value sweep.

Final OEM navigation goal remains unresolved even if warnings work. This experiment isolates an existing working path to guide further candidates, as specifically requested by the user.

## Validation and remaining checks

Nine desktop tests using actual vw_meb CANPacker and real create_lka_hud_control cover all8 profiles' exact field masks, original-frame equivalence, expiry restoration, no replay, cancel, passive check, real-warning preservation, malformed/stale/future/other-boot requests and status-I/O failure. Windows-only unused Params import shim; Python UTF8 and isolated pycapnp dependency required. No mocked DBC/packer. No physical CAN transmission or ID.Light acceptance result yet.
