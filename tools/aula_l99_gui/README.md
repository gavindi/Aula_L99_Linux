# aula_l99_gui

A small PySide6 GUI for controlling the AULA L99 keyboard (`aula_l99_hacky`) and
touchscreen (`aula_l99_screen`) without typing CLI flags. It imports both tools'
`protocol.py`/`device.py` modules directly — it does not shell out to their CLIs.

Covers the well-trodden path from each tool, not full CLI parity: no raw-hex-send,
`--convert`/`--describe`, `--address` override, `--ignore-nak`, or video-file GIF
extraction. Use the CLIs directly (`python3 -m aula_l99_hacky.cli --help` /
`python3 -m aula_l99_screen.cli --help`) for those.

## Install

From `tools/`:

```bash
cd tools
python3 -m venv .venv          # optional but recommended
source .venv/bin/activate
pip install PySide6 pillow
```

(There's a `pyproject.toml` here for `uv` users: `uv run --project aula_l99_gui
python3 -m aula_l99_gui.main` handles the venv and install automatically instead of
the steps above.)

## Run

Must be run with `tools/` on `sys.path` — either run it as a module from `tools/`,
or use `uv run` as above, which does this for you:

```bash
cd tools
python3 -m aula_l99_gui.main
```

Running it from the repo root (`python3 -m aula_l99_gui.main` without `cd tools`
first) will fail with `ModuleNotFoundError: No module named 'aula_l99_gui'`.

## Using it

Three tabs: **Device**, then one per device. No root is needed as long as the same
permissions the CLIs need are already set up (a udev rule for the keyboard's hidraw
node, membership in the `dialout` group for the touchscreen's serial port — see the
permission-error dialogs, or each tool's own README, for details).

**Device tab** — picks which hidraw node and which serial port the other two tabs
act on. One selector each, with a "Refresh" button and a status line; if a device
isn't found, plug it in and click Refresh. Both control tabs mirror the relevant
status line read-only at the top of the tab and disable their buttons while no
usable device is selected, so a greyed-out tab always says why. The keyboard is
cable-only (`0C45:800A`) — the 2.4G dongle path is unimplemented here same as in
the CLI, and finding only a dongle is reported here as an unsupported device.

**Keyboard tab**
- **Test Connection**: opens and closes a session, proving the channel works.
- **Color**: pick a color, apply it to every key.
- **Effect**: pick one of the 20 built-in effects (tagged confirmed/untested — see
  `aula_l99_hacky/README.md` for what that means) plus speed and brightness, and run
  it.
- **Clock**: set the keyboard's RTC to the current time.

**Touchscreen tab**
- **Upload Image**: send a single image to `photo-frame` or `background`. Pick an
  image, see a scaled preview, upload.
- **Upload GIF**: build and send a from-scratch GIF to the `gif` target, from a
  folder of frame images, a set of individually chosen images, or an existing
  animated `.gif`. Every frame uses the same delay (set via the spinbox) regardless
  of source — a source GIF's own per-frame delays are not read, since the panel
  requires a uniform delay across frames anyway. Colors that need dithering (any
  pixel whose brightest channel isn't exactly 0 or 255) aren't supported by the
  encoder; the GUI checks for these before uploading and lists the offending colors
  instead of sending something broken.

Both upload paths show live packet-by-packet progress and a scrolling log at the
bottom of the tab. The window refuses to close while an upload or keyboard
transaction is still in flight, since interrupting a screen upload partway through
can freeze the panel.

## Files

- `main.py` — entry point (`sys.path` bootstrap + `QApplication`)
- `main_window.py` — top-level window, hosts the three tabs
- `device_tab.py` — the Device tab and the `DeviceSelector` widget both control
  tabs are wired to; owns all enumeration, selection and auto-detect logic
- `keyboard_tab.py` / `screen_tab.py` — the two control tabs
- `workers.py` — background `QThread` workers that do the actual device I/O, so the
  UI stays responsive during a handshake or upload
- `device_utils.py` — device enumeration and permission-error hint text shared by
  both tabs
