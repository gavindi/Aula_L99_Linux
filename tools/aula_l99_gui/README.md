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
pip install PySide6 pillow defusedxml
```

`defusedxml` is imported at module scope by the User Lighting tab (it parses
saved profiles), so the GUI won't start without it. Building an animation
from a video source additionally needs `ffmpeg`/`ffprobe` on `PATH` — that
one is an external binary, not a pip package.

Keep Pillow and `ffmpeg` current. The Touchscreen tab hands whatever image,
GIF or video you pick straight to their decoders, which are C and are the only
part of this project where a malformed file meets memory-unsafe code — the
Python here can be wrong but not corrupted. `pyproject.toml`'s Pillow floor is
set for that reason rather than for any API it needs.

(There's a `pyproject.toml` here for `uv` users: `uv run --project aula_l99_gui
python3 -m aula_l99_gui.main` handles the venv and install automatically instead of
the steps above.)

### Packaged build

`../../package.sh` compiles all of this into a self-contained directory with
Nuitka and packs it as a tarball, for handing to someone who has no Python and
no wish to set one up:

```bash
./package.sh                     # from the repo root
```

The result is `build/aula-l99-gui-<version>-<arch>.tar.gz` — about 56 MB
packed, 147 MB unpacked — containing its own CPython and Qt alongside the skin
assets. Unpack it anywhere and run the `aula-l99-gui` binary inside; nothing
needs installing. `ffmpeg`/`ffprobe` remain an outside requirement, and only
for video sources.

Note that this buys distribution and nothing else. Measured on one machine, the
packaged binary reaches its first window in ~0.37 s against ~0.34 s for the
interpreted app, and uses ~126 MB RSS against ~130 MB. Qt sets both floors, so
compiling the Python does not move them.

The build takes ~80 s and needs a C compiler. It creates its own
`tools/.venv-build` from the declared dependencies rather than reusing the dev
venv, and pins Python 3.13 when `uv` is available, because Nuitka 4.1.3 still
calls 3.14 experimental (3.14 does build and run correctly — it just warns).

## Run

Must be run with `tools/` on `sys.path` — either run it as a module from `tools/`,
or use `uv run` as above, which does this for you:

```bash
cd tools
python3 -m aula_l99_gui.main
```

Running it from the repo root (`python3 -m aula_l99_gui.main` without `cd tools`
first) will fail with `ModuleNotFoundError: No module named 'aula_l99_gui'.`

### Tray mode

The GUI can also run with a system tray/app indicator icon. When the tray mode
is active, closing the window hides it instead of quitting the app.

```bash
cd tools
python3 -m aula_l99_gui.main --tray
```

To start hidden and keep the app running in the tray:

```bash
cd tools
python3 -m aula_l99_gui.main --tray --start-hidden
```

## Using it

Three tabs in an icon rail down the left-hand side: **Device**, then one per
device. The buttons are icon-only — the icons come from the vendor's own tab
artwork, the current one turns orange and gets an orange left edge, and each
carries its name as a tooltip. No root is needed as long as the same
permissions the CLIs need are already set up (a udev rule for the keyboard's hidraw
node, membership in the `dialout` group for the touchscreen's serial port — see the
permission-error dialogs, or each tool's own README, for details).

**Device tab** — picks which hidraw node and which serial port the other two tabs
act on. One selector each, with a "Refresh" button and a status line; if a device
isn't found, plug it in and click Refresh. Both control tabs mirror the relevant
status line read-only at the top of the tab and disable their buttons while no
usable device is selected, so a greyed-out tab always says why. The keyboard is
recognized on both its connections — the wired `0C45:800A` and the 2.4G dongle
(`05AC:024F`, its vendor interface 3) — and Test Connection works on either: the
dongle path runs the same session-init/session-query handshake the CLI uses.
Only the dongle is present, the lighting, colour and clock features stay
disabled (they're cable-only), and the status line says so. The connection
badge left of the minimise button follows which connection the keyboard is on:
the 2.4G radio-wave icon (`24g_mode.png`) over the dongle, the USB-plug icon
(`usb_mode.png`) on the cable.

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

**Music tab** — drive the touchscreen's spectrum analyser from live audio.
Pick an ALSA capture device (enumerated with `arecord -l`), press Start, and the
tab streams the audio feed (opcode `0x78`) to the panel at ~21 frames/s: the host
captures raw PCM via `arecord`, computes a 17-band spectrum with a pure-Python
Goertzel FFT (`audio_spectrum.py`), and sends it over the *keyboard's* vendor
channel — the cable only, since the spectrum feed is a cable path. The tab shows
a live 17-bar preview of exactly what the panel renders (the analyser draws wire
bands 0..16). The stream is not "busy": closing the app stops it quietly, and it
holds the keyboard's colour poll off while it owns the hidraw handle. Requires
`arecord` on `PATH`.

## Files

- `main.py` — entry point (`sys.path` bootstrap + `QApplication`)
- `main_window.py` — top-level window, hosts the tabs
- `device_tab.py` — the Device tab and the `DeviceSelector` widget the other
  tabs are wired to; owns all enumeration, selection and auto-detect logic
- `keyboard_tab.py` / `lighting_tab.py` / `touchscreen_tab.py` — the control
  tabs (RTC clock; per-key color and effects; image/GIF upload)
- `music_tab.py` / `audio_spectrum.py` — the Music tab and its arecord-driven,
  pure-Python Goertzel spectrum generator (the audio feed `0x78` to the panel)
- `workers.py` — background `QThread` workers that do the actual device I/O, so the
  UI stays responsive during a handshake, upload or spectrum stream
- `device_utils.py` — device enumeration and permission-error hint text shared by
  the control tabs
- `theme.py` / `slice_skin.py` / `assets/` — the vendor skin, see below

## The skin

The GUI wears the vendor's own artwork, extracted from the Windows package:
`assets/skins/theme1/main_bkg.png` behind the window, and its button, checkbox,
radio, combo, progress and scrollbar sprites driving a Qt stylesheet in
`theme.py`. The accent is the vendor's orange (`#EF6C00` hover, `#CF4D00`
pressed).

The vendor ships each widget as a single strip of equally sized frames — four
for most (`normal, hover, pressed, disabled`), eight for the check and radio
boxes (an unchecked and a checked set, interleaved). A Qt stylesheet can only
point `url()` at a whole file, never a sub-rectangle, so `slice_skin.py` splits
the strips into per-state PNGs under `assets/skins/theme1/slices/`. Those are
committed, so a normal run never needs the script — re-run it only after
changing something under `assets/skins/theme1/`:

```bash
cd tools && python3 -m aula_l99_gui.slice_skin
```

The background is cover-scaled (aspect ratio preserved, overflow cropped) and
anchored to the bottom of the window, which keeps the blue grid — the only part
of an otherwise near-black image with any detail — visible at any window size.

The left-hand icon rail is a `QTabWidget` in Qt's `West` position paired with
`SidebarTabBar` (in `main_window.py`), which draws the tab shape west-facing but
its label as if the tab faced north — otherwise Qt stands the icons on their side
along with the shape. For the same reason the button size is
`theme.SIDEBAR_TAB_SIZE` applied via `tabSizeHint` rather than a stylesheet
`min-width`: Qt evaluates that in the rotated frame, where a "width" turns into
the button's vertical extent. `SIDEBAR_TAB_SIZE` is derived as twice
`TAB_ICON_SIZE` rather than hardcoded, so changing the icon size keeps the
buttons proportioned.

Because the buttons carry no text, the tab titles live in `MainWindow._tab_titles`
rather than in `tabText()` — that list is both the key for the per-tab icon lookup
and the source of the tooltips.
