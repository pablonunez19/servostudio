# Servo Studio

[Download releases](https://github.com/pablonunez19/servostudio/releases) · [Build status](https://github.com/pablonunez19/servostudio/actions)

## Standalone downloads

Download and fully extract the release archive for your computer:

| Platform | Archive | Launch |
| --- | --- | --- |
| Windows x64 | `ServoStudio-windows-x64.zip` | `ServoStudio/ServoStudio.exe` |
| macOS Apple Silicon | `ServoStudio-macos-arm64.zip` | `ServoStudio.app` |
| macOS Intel | `ServoStudio-macos-x64.zip` | `ServoStudio.app` |
| Linux x64 | `ServoStudio-linux-x64.tar.gz` | `ServoStudio/ServoStudio` |

No Python installation is needed for these downloads. The executable starts a local server and opens your default browser at the correct address with the access key supplied automatically. It waits for **Connect servo** before opening USB. The default port is 8108; if occupied, a free localhost port is selected. Use **Quit Servo Studio** in the page to release and close the server. Closing the tab alone does not quit it. Windows/Linux builds keep a console window open for startup information; macOS uses an app bundle.

The first release is a preview and is not publisher-signed or Apple-notarized. Your OS may require approval or block first launch. The program does not install USB drivers or change device permissions. Windows needs a working AT32/DPC-20 virtual COM driver if Windows does not supply one. Linux needs permission to access the serial device (commonly membership in the device's `dialout` group). Do not run the app as root. Linux artifacts target Ubuntu 22.04-compatible x64 systems (glibc 2.35+); platform hardware compatibility still needs testing.

Saved workspaces live outside the application:

- macOS: `~/Library/Application Support/ServoStudio/`
- Windows: `%LOCALAPPDATA%/ServoStudio/`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/servostudio/`

Hardware and simulation data use separate subfolders. Updating the app does not overwrite them. Existing users of the original folder-based prototype can copy their `data-hardware/workspace.json` into the new `hardware/` folder, and `data/workspace.json` into `simulation/`, while both apps are stopped. Configuration is still read from the real servo; these files mainly preserve named positions for hardware mode.

## Development and releases

Use Python 3.9+ for source runs (release CI uses 3.12):

```sh
python -m venv .venv
# Activate the environment for your shell, then:
python -m pip install -r requirements-build.txt
python launcher.py --simulate
python -m unittest discover -s tests -v
python -m PyInstaller --noconfirm --clean ServoStudio.spec
```

`python launcher.py` starts hardware mode. `--simulate` avoids USB; `--no-browser` supports headless runs; `--serial-port COM4` (or the appropriate `/dev/...` path) chooses a device. `--data-dir PATH` overrides the mode's workspace folder. `SERVOSTUDIO_DATA_DIR` overrides the application data root. `--self-test` runs a temporary HTTP/simulator check without hardware. Each running instance has its own key. Avoid launching multiple hardware instances; one serial device must have one owner.

Builds must run natively on each target OS. The included GitHub Actions workflow runs tests and a packaged smoke test on Windows x64, Linux x64, macOS arm64 and macOS Intel. Branch pushes produce downloadable Actions artifacts. Push a `v*` tag to create a GitHub prerelease after all builds pass:

```sh
git tag v0.1.0
git push origin v0.1.0
```

Release permissions are limited to the publish job. Binaries include the UI and Python runtime but exclude user data, live access keys and development files. SHA-256 checksum files accompany each archive. Dependencies are pinned in the requirements files. No license grant has been selected yet.

## Servo operation

Local control panel and authenticated JSON API for the DPC-20 / Blue Trail SER-2131 (Hitec MDB961). Python 3.9+ and pySerial for source runs; dependencies are bundled in releases.

### Launch from source

- **Real servo:** double-click `Start.command`, or run `python3 server.py --open`. Browser address: http://127.0.0.1:8108.
- **Simulator:** double-click `Simulate.command`, or run `python3 server.py --simulate --port 8109 --open`.

Keep the server terminal open. Use the access-key link printed there; a new key is generated at each launch. Connect the USB programmer and powered servo, then click Connect servo. This hardware setup uses 12 V with a 1 A supply current limit. Run only one hardware controller at a time.

## Control and named positions

Dragging the angle slider sends movement immediately. Typing a valid angle sends it after a one-second pause; **Move now** skips that pause. New input replaces the active live target instead of queuing old positions. Stop cancels pending typing and invalidates late live requests. Switching tabs or hiding the page cancels unsent edits; an accepted movement still completes unless stopped. You can also move to Min / Max / Center or jog by 1°. Named positions support **Save**, **Edit**, **Move**, and **Remove**. They are stored on this Mac, separately for hardware (`hardware/workspace.json`) and simulation (`simulation/workspace.json`) under the application data directory. A named position does not change the servo's travel limits.

Fast uses the current configured speed limit. Slow and Medium temporarily cap it at the previous tested slow/medium values. The configured speed is restored after each move. Hold after moving keeps torque enabled. Stop & release cancels pending motion and removes holding torque through the USB/CAN link. It is not a hardware emergency stop. Closing a browser does not cancel a sequence or release holding. Control-C in the server terminal attempts release before shutdown.

## Configure the real servo

The form reads actual device values. Hardware configuration is enabled for the inspected product/version pair (7961 / 21062). Other identities retain movement support but reject configuration writes.

Editable hardware fields:

- Minimum, maximum and center angles
- Speed limit in native units
- Position deadband in encoder ticks (about 0.022° per tick)
- Motor output limit (%)
- Acceleration time (ms)
- Overload delay (s) and output during overload (%)

**Set to current position**, beside Minimum, Maximum and Center, reads the current encoder position and applies just that field. It does not copy the requested target or save to flash. Apply or reload any other manual edits first. Normal validation still applies: the center must remain within the travel range and minimum must stay below maximum.

**Apply settings** releases the motor, validates the complete configuration, writes only changes, and reads them back. If a write fails, it attempts to restore previous values and reports any unverified rollback. New travel limits must include the current shaft position and center. Move inside the proposed range first if necessary.

**Reload form** rereads the hardware settings. **Restore connection baseline** reapplies the values read when this server connected, or the values most recently sent to flash by this server. It does not load the servo's entire saved page. A baseline is not proof of nonvolatile state.

**Save to servo flash** is an explicit, separate action, with a confirmation in the browser. Hitec's save command saves all current device settings, not just the visible fields. Runtime values are checked afterward; persistence still requires a power-cycle check. Ordinary movement, Apply, preset operations and sequences do not issue flash-save commands.

Profiles use this app's JSON format. Hardware and simulator profiles cannot be mixed. Hardware profiles check the product/version identity, not the individual servo serial number. Import applies configuration and replaces named positions; it does not automatically save to flash. Hitec proprietary files are not supported.

## Test bench

Hardware mode supports an angle list, 1–20 cycles, and a pause at each position. Use Min / Max fills the current endpoints. Every leg uses fresh voltage, fault and travel checks. Stop cancels the remaining sequence, including dwell time. Long acceleration settings or very low speed/output can trigger the conservative stall watchdog; a sequence error releases holding torque.

Fault injection, simulated signal loss, virtual reboot and demo reset are shown only in simulation. Real fail-safe programming, direction reversal, CAN identity changes, firmware flashing, multiple servos and additional operating modes remain unavailable. See CAPABILITIES.md.

## API

Every API request requires `Authorization: Bearer YOUR_KEY`. GET reads; POST accepts JSON. Commands return 202 and a job ID when accepted. Poll `/api/status` until `busy` is false and then inspect `error`, `phase` and measured position. 400 indicates invalid input; 409 indicates conflicting state or unavailable capability. A job ID identifies the latest job, not a permanent job history.

| Route | Example body |
| --- | --- |
| `GET /api/status` | none |
| `GET /api/capabilities` | none; includes the current mode's form schema |
| `GET /api/profile` | none |
| `POST /api/connect` | `{}` |
| `POST /api/move` | `{"angle":150,"speed":"slow","hold":false}` |
| `POST /api/min`, `/api/max`, `/api/center` | optional speed and hold |
| `POST /api/release` | `{}` |
| `POST /api/presets/add` | `{"name":"Open","angle":170}` |
| `POST /api/presets/update` | `{"name":"Open","new_name":"Open valve","angle":175}` |
| `POST /api/presets/move` | `{"name":"Open valve","speed":"slow","hold":true}` |
| `POST /api/presets/remove` | `{"name":"Open valve"}` |
| `POST /api/sequence` | `{"angles":[100,180],"cycles":2,"dwell_s":0.5,"speed":"slow","hold":false}` |
| `POST /api/settings/read` | `{}` |
| `POST /api/settings/apply` | `{"revision":1,"settings":{"speed_native":1500}}` in hardware mode |
| `POST /api/settings/reload` | `{}`; connection baseline in hardware mode |
| `POST /api/settings/save` | `{}`; explicitly saves to hardware flash |
| `POST /api/profile/import` | `{"profile":<exported object>}` |

Read `config_revision` from status and pass it as `revision` on settings/apply. Stale revisions and externally changed hardware values are rejected. Available fields differ by mode; use the schema from capabilities. Release is asynchronous too; check final state and errors. `updated_at` is a Unix timestamp in seconds; stale telemetry is not live feedback.

Additional simulation-only routes: `/api/settings/reset`, `/api/sim/power-cycle`, `/api/sim/signal-loss`, and `/api/sim/fault` with `{"kind":"none|stall|undervoltage|overvoltage|overheat"}` (choose one kind).

## Validation

Run `python3 -m unittest discover -s tests -v` from this folder. The original 24 tests passed, including configuration validation, rollback, stale state, presets/editing, sequences/cancellation, mode separation, persistence and authentication.

Live checks on the connected servo passed: configuration readout, temporary speed register change and restore, named-position add/edit/move/remove, and a small two-position sequence returning within the normal encoder tolerance. No flash save was issued during verification. Other exposed fields use documented registers with runtime read-back and fake-device rollback tests; their individual physical effects and power-cycle persistence have not all been tested.

## Portable build validation

The serial transport now uses pySerial instead of macOS-only termios calls. Port selection prefers DPC-20/AT32 identification and rejects ambiguous USB devices. Packaged tests verify bundled HTML, authentication, simulator movement and shutdown without touching USB. The original physical checks above used the previous native macOS transport; they do not establish Windows/Linux hardware validation.

## Live control API

`POST /api/live` accepts `{"angle":150,"stream":"unique-client-session","seq":1,"speed":"slow","hold":true}`. Increase seq for each request. Only the owning stream may retarget its active live move; regular moves and sequences reject competing live requests. When a move is finishing, HTTP 409 tells the client to retry its latest target. A stale seq is rejected. Stop can include `{"stream":"unique-client-session"}` to invalidate requests even if none has arrived yet; create a new stream ID for later input.

`POST /api/settings/capture` accepts `{"field":"center_deg","revision":1}`. Fields are `min_deg`, `max_deg`, or `center_deg`. Read config_revision from status first. The worker reads the encoder and uses the usual validated configuration-write path.

### CAN protocol selection

Configure → **CAN protocol** shows the detected firmware, configured protocol and
supported choices. Servo Studio discovers one servo with read-only Hitec register
queries over DroneCAN-style extended frames, then CAN 2.0A (11-bit) and CAN 2.0B
(29-bit) custom register messages. The CAN 2.0A/B paths have automated packet tests;
physical validation so far covers the MDB961 **1.6(2) /U** variant only.

**This /U servo is DroneCAN-only.** Its mode register reads zero but is ignored by
that firmware; zero must not be interpreted as CAN 2.0A support. The app disables
unsupported modes. It uses Hitec register access, not a full DroneCAN controller
with node discovery, heartbeats and standard ArrayCommand control. CAN FD is not
supported.

On recognized /A and /C firmware versions 1.4 through 2.3, changing protocol requires
acknowledging that **all current device settings are saved**. The app releases the
motor, writes and verifies the mode, sends the flash save, and disconnects. Power-cycle
the servo and click Connect; motion does not resume automatically. /C supports A/B;
/A supports A/B/DroneCAN. Existing CAN IDs must fit the destination protocol. This
feature does not rewrite IDs, flash firmware, or convert /U firmware into /A firmware.
Use only one servo on this bench connection. The simulator can exercise all choices
without hardware and performs a virtual save/reboot.

API: `POST /api/protocol/change` with `protocol` (`can2a`, `can2b`, `dronecan`),
current `revision`, and `acknowledge_save: true`. Status includes `protocol_info`
and `protocol_pending`. Unsupported choices are rejected by the server too.

References: [Hitec protocol manual v2.5](https://www.hiteccs.com/public/uploads/ckeditor/69f10885c7bb61777404037.pdf).
Legacy firmware value 21062 is decoded as 1.6(2) /U using the decoder in Hitec's
2024-04-03 configuration app; the newer manual describes a different /U offset.
