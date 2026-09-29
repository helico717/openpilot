# Parked Carrot HA camera service

This is the sole Comma runtime source. Deploy on `carrot-wip-model_selector-ha`
by committing/pushing, then clean Git pull and reboot. HA relay code remains in
`helico717/carrot-ha:main`; both speak CHV1 media/control protocol v1.

The manager's `carrot_camera` process runs only when configured. Settings and
enable markers live in `/data/carrot_ha/camera`, never the Git checkout.
On the first offroad start, an enabled legacy `/data/carrot-camera` install is
migrated without changing its source or `continue.sh`. Its credentials are
atomically copied with mode 600; its enabled marker is removed. The replacement
waits for the legacy supervisor flock and retains that lock while connected.
An existing native configuration takes precedence, including disabled state.
A legacy installation that was disabled is never automatically enabled.

`compatibility.require_runtime` checks executable availability, GNU timeout,
PyAV remux support and all three encoded-stream schemas before camera startup.
There is no Git revision allowlist, so ordinary merges and commits do not block
capture. Incompatible runtime APIs still fail closed; API checks do not prove
hardware/video compatibility for arbitrary future upstream changes.
Offroad/ownership checks, non-conflated H.264, lease expiry, 300-second limit,
process timeouts and cleanup remain in capture/probe. Manager output includes
connection state and capture errors; the legacy agent.log stops updating.

For new installations use `python -m openpilot.selfdrive.carrot.ha.camera.configure`
then the same command with `--enable`. Use `--disable` before editing settings.
These commands only write runtime state. Existing enabled installs need neither
new credentials nor manual copying. The full HA setup guide is in carrot-ha's
`docs/CAMERA_SETUP.md`.

Desktop regression suite (Python 3.11+, aiohttp and av):

```
python -m unittest discover -s openpilot/selfdrive/carrot/ha/tests
```

The suite covers unrelated Git commits, missing capabilities, migration restart,
legacy lock handoff, disabled/invalid configuration, onroad refusal, manager
registration, protocol vectors and actual H.264/TS/HLS remux. This is not a
physical device playback or onroad validation claim.
