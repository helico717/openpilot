# IQpilot + Carrot HA personal installation candidate

This is a personal, non-commercial IQpilot fork with a pinned, unmodified upstream Git submodule.
It preserves the upstream license and proprietary runtime verification. Vendor binaries are fetched
from the upstream Git repository, not redistributed in this superproject.

Candidate only: local/CI tests do not establish vehicle compatibility or successful OS rollback.
An off-device Carrot settings/database backup is required before switching. Do not wipe/reset the device.
The initial boot downloads the pinned upstream repository and follows its normal IQ.OS update path.
HA, Comma installation and reboot must be performed by the owner; do not patch device sources by SSH/SCP.

For a matching clean stock IQ install, clone this branch into a separate staging directory,
then use `python3 bootstrap/install_from_stock.py --prepare-vendor`. Only after CI and version
checks, the owner runs the same script without arguments to activate through Git. Shallow
stock repositories are supported. The script never reboots or restores credentials.
Full procedure: helico717/carrot-ha docs/IQPILOT_HA_UPDATE_PATH_2026-11-02.md.

After installation, while parked, run:

    cd /data/openpilot
    /usr/local/venv/bin/python3 -m iqpilot.selfdrive.carrot.ha.iq_preflight

This diagnostics command does not start cameras, send CAN or change settings. Confirm live HA
measurement time, one short recorded trip/charge, camera display and onroad shutdown, terminal
reconnect, raw log/video transfer and the return path before accepting the candidate.

Carrot parameter synchronization is paused. Do not use the Carrot parameter card during IQ testing.
IQ settings remain on the device; there is no claimed IQ parameter editor in HA yet. General logs
and video reuse the existing upload API; Carrot-specific log analysis is not claimed compatible.
IQ Sentry/Live View take precedence over the HA parked camera. No vehicle runtime tests have passed yet.
Do not use an updater/branch selector to replace this companion branch with stock IQ inadvertently.

The runtime diagnostics also print `carrot_return`. It checks, read-only, whether the inactive-slot
partitions are writable by the Carrot OS flasher (IQ.OS removes owner root). Only
`SOFTWARE_RETURN_POSSIBLE_UNVERIFIED` allows the software return; otherwise plan a recovery first.
Return to the pinned Carrot commit with Git only (no force/reset/clean, stops on any conflict):

    cd /data/openpilot
    bash bootstrap/switch_to_carrot.sh

Then reboot. Full owner procedure: carrot-ha docs/IQPILOT_HA_INSTALL_AND_RETURN.md.
