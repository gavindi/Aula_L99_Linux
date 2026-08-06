# AULA L99 Linux - Keyboard App & Tools

Reverse engineering of the **AULA L99** mechanical keyboard and its built-in
touchscreen, with working Linux tools for everything the vendor's
Windows-only software does over USB: per-key RGB, built-in lighting effects,
host-driven animations, the on-board clock, the touchscreen's system-monitor
and weather readout, its audio spectrum analyser, keyboard settings, and
uploading images and animated GIFs to the panel — plus a PySide6 GUI that
ties it all together.

![The GUI's Device tab, wearing the vendor's own skin](screenshots/00-HomeDevice.png)

[![License: GPL v2](https://img.shields.io/badge/License-GPL_v2-blue.svg)](LICENSE)

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/P5P21M7MBS)

Everything here was derived from USB captures of the vendor's
`DeviceDriver.exe`, static analysis of its DLLs and firmware updaters, and
byte-level experimentation against real hardware. No vendor code runs on
Linux; no vendor code is required at runtime.

## The hardware

The L99 is really **two independent USB devices** in one chassis:

| Device | IDs | Transport |
|---|---|---|
| Keyboard (vendor channel) | `0C45:800A` wired, `05AC:024F` 2.4G dongle | HID feature reports, interface 3, 64-byte packets |
| Touchscreen | `EEEF:268A` | CDC-ACM USB serial (`/dev/ttyACMn`) |

They share no protocol and no code. One crossover exists: the panel's
CPU/GPU/weather readout is fed through the *keyboard's* HID channel (riding
in the RTC packet), which the keyboard forwards to the panel.

## The tools

All three live under [tools/](tools/) and are pure Python. Each has its own
README with full protocol documentation and usage.

### [tools/aula_l99_hacky/](tools/aula_l99_hacky/README.md) — keyboard CLI

Talks to the keyboard's vendor HID channel via `/dev/hidraw*` (no root
needed with the udev rule in [packaging/90-aula-l99.rules](packaging/90-aula-l99.rules)).
Confirmed on real hardware:

- Session handshake, per-key RGB **write and read-back** (84 keys)
- All 20 built-in lighting effects, with speed/brightness
- A second, session-less realtime colour-stream path (opcode `0x20`) used
  for host-driven animation
- RTC clock set, carrying the panel's CPU/GPU load & temperature, air
  temperature, forecast highs/lows, weather condition and humidity — each
  field verified by writing a distinctive value and reading the panel
- The audio spectrum feed (opcode `0x78`) driving the panel's analyser —
  the host does the FFT, the keyboard just receives 23 levels (the panel
  renders 17 of them)
- Settings writes (opcode `0x17`): response time, sleep timer
- `--send-hex` for replaying candidate packets straight from a capture

The protocol (framing, checksums, block layout, timing constraints, and the
gotchas that will corrupt a capture analysis) is documented in its
[README](tools/aula_l99_hacky/README.md), with deeper working notes in
[re_notes/](tools/aula_l99_hacky/re_notes/).

### [tools/aula_l99_screen/](tools/aula_l99_screen/README.md) — touchscreen CLI

Talks to the panel over USB serial (`dialout` group membership suffices).
Confirmed on real hardware:

- **Single-image upload** to the photo-frame and background flash slots
  (any format Pillow reads, auto-resized to 320×480)
- **Animated GIF upload** — building the panel's proprietary GIF container
  from scratch, from frame images, an existing `.gif`, or video frames.
  Currently limited to "safe" colors (`max(R,G,B)` exactly 0 or 255); the
  vendor encoder's dithering for anything else is characterised but not yet
  reimplemented
- `--convert` / `--describe` for building and inspecting the panel's `.bin`
  blobs offline

The GIF container was the hardest single artifact in the project: a
proprietary format with a per-frame RGB565 palette, a run-length encoding
that runs *continuously across row boundaries*, a fallback raw
indexed-bitmap mode for heavily-dithered frames, per-length CRC
initialisation values for the final wire chunk, and a firmware-side content
validator with genuinely strange rules (it tolerates exactly 8 stray bytes
in a padding region; it rejects a foreign pixel in a stripe's interior but
accepts one at a colour boundary). All of it was decoded through 18+
targeted Wireshark captures and dozens of single-byte mutation experiments
against the live panel — the full lab notebook is in the tool's
[README](tools/aula_l99_screen/README.md).

### [tools/aula_l99_gui/](tools/aula_l99_gui/README.md) — PySide6 GUI

A desktop app wrapping both CLIs' protocol modules directly (no
shelling-out), wearing the vendor's own extracted skin artwork. Seven tabs:

**Device** — hidraw/serial discovery and selection

![Device tab](screenshots/00-HomeDevice.png)

**Keyboard** — connection test, all-keys colour, clock set

![Keyboard tab](screenshots/01-KeyboardMacros.png)

**Lighting** — the 20 built-in effects with speed/brightness, and a live
preview that mirrors the keyboard's actual LED state

![Lighting tab](screenshots/02-Lighting.png)

**User Lighting** — per-key colour editing on a rendered keyboard overlay,
plus host-animated effects (breathing, rainbow wave, starlight, …)
streamed at ~17 fps for single keys the firmware can't animate itself

![User Lighting tab](screenshots/03-UserLighting.png)

**Touchscreen** — image and GIF upload with live packet-by-packet progress

![Touchscreen tab](screenshots/04-Touchscreen1.png)

**Music** — live 17-band spectrum for the panel's analyser, captured from an
ALSA input device via `arecord` and streamed over the keyboard's audio feed
(`0x78`, cable only), with an on-tab bar preview. The tab also carries the
vendor "Music Rhythm" controls: Rhythm and Background Mode dropdowns (the
same 15-entry list the Windows app uses) and Amplitude / Background Brightness
sliders, all persisted across launches.

**Config** — polling and app settings

![Config tab](screenshots/09-Config.png)

Supports system-tray/app-indicator mode (`--tray`, `--start-hidden`).

## Requirements

Python 3.10+ (the GUI's floor; the keyboard CLI itself runs on 3.9+).

| Module | Version | Needed by |
|---|---|---|
| [`PySide6`](https://pypi.org/project/PySide6/) | ≥ 6.5 | GUI only |
| [`Pillow`](https://pypi.org/project/Pillow/) | ≥ 10.0 | GUI; touchscreen CLI's image/GIF/video features |
| [`defusedxml`](https://pypi.org/project/defusedxml/) | any | GUI only — parsing saved User Lighting profiles |
| [`pytest`](https://pypi.org/project/pytest/) | any | running the test suites only |

```bash
pip install PySide6 pillow defusedxml
```

**The keyboard CLI (`aula_l99_hacky`) needs nothing but the standard
library** — hidraw is driven through `fcntl`/`os`, so it works on a bare
Python install.

**The touchscreen CLI (`aula_l99_screen`) needs nothing installed for device
discovery, `--describe`, or uploading a pre-built `.bin`.** Pillow is
imported lazily, only where an actual image is decoded (`--upload`,
`--upload-gif`, `--convert`), and each of those exits with an install hint
rather than a traceback if it is missing.

**Not a Python module:** building an animation from a video source needs
`ffmpeg` and `ffprobe` on `PATH` (`apt install ffmpeg`). Every other source
format is handled by Pillow. This applies to both the GUI's Touchscreen tab
and the CLI's video path.

**Another external binary, audio capture:** the GUI's Music tab needs
`arecord` on `PATH` (part of `alsa-utils`) to capture from an ALSA input
device; the spectrum maths itself is pure Python with no extra dependency.

**None of the above applies to the packaged GUI.** `./package.sh` builds a
self-contained tarball that carries its own CPython and Qt, so the binary
inside needs no Python and no `pip install` — only `ffmpeg` for video sources.
See [Quick start](#quick-start) below and
[tools/aula_l99_gui/README.md](tools/aula_l99_gui/README.md#packaged-build).
Building it (as opposed to running it) needs a C compiler.

## Quick start

```bash
# GUI (uses uv if present, else .venv, else system python)
./run.sh
./run.sh --tray --start-hidden

# CLIs
cd tools
python3 -m aula_l99_hacky.cli --list          # find the keyboard
python3 -m aula_l99_hacky.cli --color 00FF00  # all keys green
python3 -m aula_l99_screen.cli --list         # find the panel
python3 -m aula_l99_screen.cli --upload picture.png

# syntax-check everything under tools/
./compile.sh

# build a standalone GUI tarball (no Python needed to run the result)
./package.sh

# or build an installable .deb (desktop entry, icon, udev rule included)
./make_deb.sh
```

See [Requirements](#requirements) above for what to install, and
[tools/aula_l99_gui/README.md](tools/aula_l99_gui/README.md) for venv/`uv`
setup.

**Permissions:** the touchscreen is a USB serial port (`/dev/ttyACMn`) and
needs membership in the `dialout` group. The keyboard needs read/write on its
hidraw node — installing the packaged `.deb` (see below) brings
`packaging/90-aula-l99.rules`, a udev rule that grants it (`MODE="0660"`,
`GROUP="plugdev"` plus `TAG+="uaccess"`, so systemd-logind hands the logged-in
desktop session access with no group membership); without the `.deb`, drop the
rules file into `/usr/lib/udev/rules.d/` yourself (or rely on the usual distro
hidraw ACL). No root otherwise.

## How the reverse engineering was done

1. **USB captures** — the vendor's `DeviceDriver.exe` running under Windows
   with USBPcap/Wireshark, one isolated action per capture. The raw
   captures are kept in [wireshark_dumps/](wireshark_dumps/) (named for
   what was being tested: `save_to_gif_*.pcapng`, `response_time_1.pcapng`,
   `system_monitor_2.pcapng`, …) so every claim in the protocol docs can be
   re-verified against its source.
2. **Byte-for-byte reproduction** — every packet builder in both
   `protocol.py` modules reproduces the vendor app's own packets exactly,
   checked against the captures before ever touching hardware.
3. **Hardware mutation experiments** — for the parts no capture could
   explain (the GIF encoding, the panel's content validator), known-good
   blobs were re-uploaded with controlled single-byte changes and the
   panel's behaviour photographed and compared. The screen README reads as
   the lab notebook for this.
4. **Static analysis** — the vendor package under
   [Windows/AULA L99/](Windows/AULA%20L99/) (config, layouts, language
   tables, skins, fonts, the qt-tool DLLs) and the firmware updaters were
   disassembled where captures weren't enough: `pic_scan.dll` for the image
   pipeline, and the Enigma-Protector-wrapped screen firmware updater
   (unpacked sections in [documentation/Firmware/](documentation/Firmware/))
   for a possible custom-code path to the panel's LT7689 controller.
   Working notes live in each tool's `re_notes/` directory.

### What's still open

- The GIF encoder's dithering algorithm (error-diffusion-like, per-channel;
  characterised but not reimplemented) — the blocker on arbitrary-colour
  GIF uploads
- A general formula for the final-chunk CRC init values (currently a
  per-length lookup table solved from captures)
- The panel's content-validation mechanism (its behaviour is mapped across
  ~20 hardware data points; the algorithm isn't decoded)
- Keyboard macros; the 2.4G dongle's colour/effect/settings path (its handshake
  and RTC-set are confirmed; the rest still awaits a capture of the vendor app
  driving the dongle); touchscreen touch input, brightness and power
- One unidentified flash slot at `0x04200000`

## Repository layout

```
tools/aula_l99_hacky/    keyboard HID protocol + CLI (+ re_notes/)
tools/aula_l99_screen/   touchscreen serial protocol + CLI (+ re_notes/)
tools/aula_l99_gui/      PySide6 GUI over both (+ vendor skin assets)
wireshark_dumps/         the USB captures everything was derived from
Windows/                 vendor software package + firmware updaters (analysis source)
documentation/Firmware/  unpacked PE sections of the screen firmware updater
test_images/             image/GIF test fixtures
run.sh                   launch the GUI
compile.sh               byte-compile everything under tools/
package.sh               build a standalone GUI tarball with Nuitka
make_deb.sh              build an installable .deb from that tarball build
packaging/               .deb pieces: udev rule, launcher template, installer
CHANGELOG.md             detailed, versioned history of the whole effort
```

## Related work

The touchscreen's *serial widget* protocol was independently documented in
[Salamor/aula-l99-open-widgets](https://github.com/Salamor/aula-l99-open-widgets);
this project covers everything that project doesn't — the keyboard's HID
channel and the panel's image/GIF upload path.

## Disclaimer

Not affiliated with or endorsed by AULA. Everything here was derived by
observing a device its owner bought; use at your own risk. Uploads to the
touchscreen write to its flash — interrupting one mid-transfer can freeze
the panel until a restart.
