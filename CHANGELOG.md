# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.10.13] - 2026-08-31

**The Config tab now has a "Start on login" option, with a "Start hidden in
tray" toggle to go with it.** The app's `--tray`/`--start-hidden` flags
already worked, but nothing installed them anywhere — a user had to launch
the app by hand every session to get their lighting/monitor config running
again. The new Startup group writes a standard XDG autostart entry
(`~/.config/autostart/aula-l99-gui.desktop`) that relaunches with `--tray`
always, and `--start-hidden` when the (default-on) hidden toggle is checked.
The one real problem this raised: a running instance has to work out its own
correct relaunch command, and that differs across all five package forms —
a flatpak's internal `/app/bin/...` path is meaningless outside the sandbox
(`flatpak run <app-id>` instead), a snap's `argv[0]` is under a
revision-numbered path that rotates on every refresh (`/snap/bin/<name>`
instead), an AppImage's `argv[0]` is a random per-run FUSE mount gone by the
next login (the `APPIMAGE` env var instead), and a Nuitka-compiled
deb/rpm/tarball binary or a plain dev checkout each need their own case too.
If none of those resolve to something real, both checkboxes disable
themselves with an explanatory tooltip rather than writing a broken entry.

### Added
- `autostart.py`: new module owning the XDG autostart `.desktop` file —
  `is_supported()`, `is_installed()`, `install(hidden)`, `uninstall()` — plus
  the per-package-form relaunch-command resolution described above and a
  best-effort copy of the app's icon into the user's icon theme for package
  forms that don't register it anywhere else (tarball without `install.sh`,
  AppImage).
- `settings.py`: `start_on_login()` / `set_start_on_login()` and
  `start_hidden()` / `set_start_hidden()` (default `True`), stored under a
  new `"startup"` key with the same atomic-write pattern as every other
  setting here.
- `config_tab.py`: a "Startup" group with "Start on login" and "Start hidden
  in tray" checkboxes. The hidden checkbox is only enabled while login is
  checked; a failed install/uninstall (permissions, disk full) reverts the
  checkbox and reports through the existing debug log rather than leaving
  the UI out of sync with the actual file.

### Changed
- `packaging/flatpak/io.github.gavindi.AulaL99Gui.yml`: added
  `--filesystem=xdg-config/autostart:create` to `finish-args` — without it
  the sandbox silently redirects the autostart write to
  `~/.var/app/<id>/config/autostart`, which no host session manager reads,
  so the checkbox would appear to work while doing nothing.

## [0.10.12] - 2026-08-31

**The Config tab's System Monitor now has a 1-60s spinner for the CPU/GPU
send interval, and logs every poll.** The interval was a hardcoded 5-second
constant with no UI control, and the debug log only ever got one line when
the stream started — nothing per-send, so there was no way to confirm from
the log that it was actually still polling. The new spinner sits next to the
"Send CPU/GPU Load" checkbox, persists like the checkbox's own run state
does, and retunes a running stream live via `MonitorStreamWorker.set_period()`
— the same cross-thread attribute-swap idiom `AudioSpectrumWorker` already
uses for its own controls — so changing it takes effect on the next send
rather than requiring a stop/restart.

### Added
- `settings.py`: `monitor_period_seconds()` / `set_monitor_period_seconds()`,
  stored under the existing `"monitor"` key alongside the toggle's run state.
- `workers.py`: `MonitorStreamWorker.set_period()` for a live retune of a
  running stream's cadence.
- `config_tab.py`: a "Update every (s):" `QSpinBox` (range 1-60) in the
  System Monitor group, enabled whenever the toggle itself is (including
  while streaming); a new `monitor_period_changed` signal carries changes to
  `keyboard_tab.py`'s `set_monitor_period()`.
- `keyboard_tab.py`: `_on_monitor_sent()` appends a `-- polled: CPU …% · GPU
  …%` debug-log line for every send, not just the stream's start.

### Changed
- `keyboard_tab.py`'s hardcoded `MONITOR_PERIOD_SECONDS = 5.0` constant is
  now `MIN_/MAX_/DEFAULT_MONITOR_PERIOD_SECONDS` (1/60/5), and the stream's
  period is seeded from the persisted setting instead.

## [0.10.11] - 2026-08-31

**The Music tab's Audio Input list now includes loopback (all audio out) and
single-application sources, not just microphones.** Device listing was
ALSA-only (`arecord -l`), which has no concept of "capture whatever is
currently playing" or "capture only this one app" — those are session-level
routing that only the desktop audio server exposes. This machine runs plain
PipeWire (no `pactl`/pipewire-pulse), so the new listing shells out to
`pw-dump` instead: each `Audio/Sink` node (a speaker/HDMI/interface output)
becomes a "Loopback: …" entry, and each transient `Stream/Output/Audio` node
(one per actively-playing app) becomes an "App: …" entry labelled with the
app name and track/tab title where available. Selecting either kind and
pressing Start runs `pw-record --target <node serial>` instead of `arecord`
— PipeWire links the capture stream straight to the sink's monitor ports or
to the specific app stream, so a per-app capture is isolated from anything
else making noise, with no null-sink or extra routing needed. The existing
ALSA mic entries are unchanged and still list first; a separator divides
them from the new PipeWire group. A system without PipeWire tooling falls
back to the ALSA-only list exactly as before.

### Added
- `audio_spectrum.py`: `list_pipewire_devices()` / `parse_pipewire_devices()`
  parse `pw-dump`'s JSON into loopback/application `CaptureDevice` entries;
  `pw_record_command()` builds the matching raw-PCM capture argv;
  `list_all_devices()` combines these with the existing ALSA listing,
  swallowing a PipeWire-side failure so it degrades to ALSA-only rather than
  blanking the combo.

### Changed
- `CaptureDevice` gained a `kind` field (`"alsa"` / `"pipewire"`); its ALSA
  field was renamed `plughw` → `target` to also hold a PipeWire node's
  `object.serial`.
- `music_tab.py`: the combo now stores the whole `CaptureDevice` as each
  item's data (a separator marks the ALSA/PipeWire boundary), and Start
  picks `arecord_command()` or `pw_record_command()` from the selected
  device's `kind`.
- `workers.py`'s `AudioSpectrumWorker` error messages no longer hardcode
  "arecord", since the capture subprocess may now be `pw-record`.

## [0.10.10] - 2026-08-26

**A manually-triggered GitHub Actions workflow now builds and packages a full
release in one run.** `workflow_dispatch` takes a bare version number
(`0.10.10`, matching this project's existing tag style — no leading `v`),
compiles the GUI once with the existing `package.sh` (Nuitka), and fans that
single build out into `.deb`, `.rpm`, a classic-confinement snap, a flatpak
bundle and an AppImage — plus the raw tarball `package.sh` already
produces — collating all six onto a GitHub Release. Building once and
sharing the dist across the packaging jobs, rather than recompiling per
format, guarantees every package wraps identical bytes and avoids repeating
the Nuitka build four more times.

`tools/aula_l99_gui/pyproject.toml`'s version string is hand-maintained and
has drifted from the git tags before (`0.10.5` in the file against `0.10.9`
tagged). Rather than trust it, every job patches that file's version line to
the workflow's input version right after checkout — ephemeral, never
committed — before calling any build script. Since `package.sh` and
`make_deb.sh` already independently derive `VERSION` via `sed` from that same
line, this makes every existing and new packaging script agree on one
version with no script changes and no new flags.

Neither `.rpm`, snap, flatpak nor AppImage tooling existed before this;
`.rpm` is the only one built on top of existing work — `make_rpm.sh` points
`fpm` at the same `build/deb-root` tree `make_deb.sh` stages, reusing its
copyright/changelog/postinst placement rather than duplicating it. The snap
and flatpak both need a hardware-access workaround with no clean fix:
neither format has an interface/portal for raw `/dev/hidraw` access, so the
snap uses `confinement: classic` (install with `snap install --classic
--dangerous`, still needing `packaging/90-aula-l99.rules` installed
separately) and the flatpak grants `--device=all` in its `finish-args`. Both
are pragmatic for a GitHub-Release artifact and would be rejected by the
Snap Store / Flathub outright — this workflow does not publish to either.

This has not yet been run against real CI — the job graph, package
contents and scripts are believed correct from reading the existing
`package.sh`/`make_deb.sh` closely, but things like AppImage's FUSE
availability on GitHub-hosted runners, `snapcraft pack --destructive-mode`
working unmodified there, and whether `org.freedesktop.Platform` (rather
than a KDE runtime) is actually sufficient for the Nuitka-bundled Qt binary
are unverified until a real workflow run is triggered.

### Added
- `.github/workflows/release.yml`: `prepare` (validates the version input)
  → `build` (runs `package.sh` once, uploads the dist and tarball as
  artifacts) → `package-deb-rpm` / `package-snap` / `package-flatpak` /
  `package-appimage` (each downloads the dist artifact and runs its script)
  → `release` (downloads every packaging job's output, extracts the latest
  `CHANGELOG.md` entry via `awk` for the release body, and runs
  `gh release create` with all six files).
- `make_rpm.sh`: `fpm -s dir -t rpm` against `make_deb.sh`'s staged
  `build/deb-root`, mapping the `.deb`'s `Recommends: ffmpeg, alsa-utils` to
  the RPM equivalent via `--rpm-tag` and reusing its `postinst` verbatim as
  `--after-install`.
- `make_snap.sh` / `packaging/snap/snapcraft.yaml`: copies the manifest into
  `snap/snapcraft.yaml` (where `snapcraft` expects it) with the version
  patched in, `plugin: dump`s the Nuitka dist as-is so Nuitka's assets/font
  siblings resolve the same way they do unpacked, and runs
  `snapcraft pack --destructive-mode`.
- `make_flatpak.sh` / `packaging/flatpak/io.github.gavindi.AulaL99Gui.yml` +
  `aula-l99-gui-wrapper.sh`: copies the already-built dist into `/app/lib`
  rather than recompiling inside `flatpak-builder`'s sandbox, patches the
  dist's own `@EXEC@` desktop template for the `/app/bin` wrapper path, and
  produces a single-file `.flatpak` via `flatpak build-bundle` (no hosted
  repo exists to point users at otherwise).
- `make_appimage.sh` / `packaging/appimage/AppRun`: stages an `AppDir` from
  the dist (desktop file and icon moved to the AppDir root per the AppImage
  spec) and packs it with `appimagetool`, downloaded from its GitHub
  releases if not already present.

## [0.10.9] - 2026-08-26

**Clicking a key on the Keyboard tab now assigns it.** A left-click on any key
in the layout opens an assignment dialog: a "Key Type" dropdown whose single
entry is the one remap type decoded so far ("Key Function"), a field to its
right where the key to act as is typed, and Apply / Cancel buttons — with the
title-bar X closing like Cancel. Apply resolves the typed name and writes the
remap through the tab's usual transaction path, inheriting its progress bar,
debug log and write-behind-an-in-flight-read queue; Cancel and X close without
writing anything.

This is the first code to drive the `0x11` key-profile table that 0.10.8
decoded. The vendor app rewrites the whole table on every apply and there is
no read-back, so each assignment sends exactly one non-default entry —
applying a second remap resets whatever an earlier one did, whether that one
came from this GUI or from the vendor app. Only "Key Function"
(`02 00 <usage> 00`) is offered; the panel's other types (multimedia,
disable, macro) wait until their encodings are driven too.

### Added
- `tools/aula_l99_gui/key_assignment_dialog.py`: `KeyAssignmentDialog`, modal
  and titled `Assign Key — <name>`. The Key Type combo carries the wire type
  (`KEY_ENTRY_KEY`) as its item data for when more entries arrive; Apply is
  the default button (Enter applies, Esc cancels); an unresolvable name warns
  and keeps the dialog open rather than half-applying. Like the main window
  it is frameless with its own title strip — Qt cannot skin native chrome —
  black with the vendor close button only (no minimise/maximise), reusing the
  main window's `TitleBar`/`TitleCloseButton` styling, and draggable via
  `startSystemMove` the same Wayland-safe way.
- `protocol.py`: `OP_KEY_PROFILE` named at last; the five captured entry-type
  constants (`KEY_ENTRY_DEFAULT`/`KEY`/`MEDIA`/`DISABLE`/`MACRO`);
  `build_key_remap_blocks()` / `build_key_remap_transfer(key_id, hid_usage)`
  building the 9-block table — 4-byte entries at `key_id * 4`, with the AA 55
  inside the last block's bytes 62..63 rather than in a terminator block of
  its own, unlike the colour path; `resolve_hid_usage()` and
  `HID_USAGE_NAMES` (~100 names — letters, digits, F-keys and keypad digits
  generated from their consecutive ranges, navigation/modifiers named by
  hand), case-insensitive with aliases ("return" = "enter", "pgup" =
  "pageup") and raw numbers via `int(x, 0)`; usage `0x00` ("no event")
  refused like an unknown name; `HID_USAGE_DISPLAY_NAMES` picking the first
  alias per usage as the user-facing form.
- `keyboard_tab.py`: `_on_key_clicked()`, wired to the overlay's previously
  unused `keyClicked` signal. Gated on device-ready and not busy/monitoring;
  the overlay's toggle-deselect (-1, shared contract with User Lighting)
  opens nothing. Dialog titles prefer HID names over the layout XML's keycap
  legends — "capslock", not `.>` or `!1`.
- Tests: 21 protocol cases anchoring against the re_notes witnesses (Caps
  Lock entry at offset 220 = `02 00 29 00`, Pause at 460, the empty table
  reproducing the vendor's all-zero startup table, transfer framing,
  range/name validation); 10 GUI cases covering apply/cancel/X/warn-and-stay-
  open and the click → dialog → wire path end to end.

## [0.10.8] - 2026-08-13

**Key remapping and macros are now decoded — the last big unknown on the
keyboard's HID channel** (documentation only; nothing in the tools drives
them yet).

Capturing the vendor app under Wine with the existing shim while performing
isolated UI actions produced the wire formats, verified on hardware:

- **`0x11` key-profile write** — 9 blocks, 4-byte entries at
  `key_index * 4` (layout XML index), whole table rewritten per change.
  Entry = `[type, p1, p2, p3]`: `02 00 <usage> 00` remap-to-key (Esc =
  `0x29`), `03 <consumer> 00 00` multimedia (Volume Up = `0xE9`), `05 03 00 00`
  disable, `06 00 00 00` macro trigger. Remaps/disables/media bindings
  survive the driver closing — they live on the keyboard.
- **`0x15` macro-slot write**, preceded per round by `0x19`, 9-10 blocks of
  8-byte events `00 00 <usage> <B0|30> <delay> 00 00 50` (down/up flag,
  delay ms), growing cumulatively per recorded keystroke. Macro playback is
  on-board (a recorded "go" macro replayed with the app closed).
- **`0x27`** — same table shape as `0x11`, seen only at startup with an
  all-zero table; Fn-layer table is the working hypothesis. The old
  "profile read" reading of `0x11`/`0x27` in `profile_read_1.pcapng` was a
  direction misjudgement and is corrected in the notes.

Full byte layouts and the complete opcode reference are in
`tools/aula_l99_hacky/re_notes/key_remap_macros.md`; the opcode table in the
hacky README now lists `0x11`, `0x15`, `0x19` and `0x27`. The Fn-layer
encoding, the remaining key types (mouse/shortcut/text/multi-key), the macro
play parameters and the `0x00` opcode are still open.

## [0.10.7] - 2026-08-07

**The Settings tab now has the two keyboard-panel dropdowns, backed by the
first new protocol decode to come out of a reusable capture toolchain.** The
vendor's response-time and sleep-time panel (opcode `0x17`) is now fully
understood and drivable from this project's own GUI and CLI.

The decoding came from a new, reusable capture setup for the vendor app under
Wine: `tools/aula_l99_hacky/capture/` holds an `LD_PRELOAD` shim that logs the
app's HID feature-report ioctls in `winedevice.exe` with full 65-byte payloads
(the `0x00` report-id byte plus the 64-byte packet), a launcher that kills
`wineserver` before preloading it, and a parser that strips the vendor's
~27 Hz colour poll, normalises the report-id byte away, and byte-checks
captured sessions against the protocol builders. The shim logs only the AULA
devices, resolved from sysfs by VID/PID and interface — otherwise every mouse
report and keystroke lands in the capture, which is exactly what happened to
the first attempt. The `0x17` panel then decoded cleanly: byte 6 is the sleep
time (0..3 = no sleep / 1 / 5 / 30 minutes) and byte 8 the response-time
level (1..5, with the vendor's documented per-link delays), both slots
written on every change, with a byte-2 = `0x01` header quirk no other command
shares. This corrected an earlier reading that had the two slots swapped.

The GUI and CLI now drive it. The Settings tab's new "Keyboard Settings"
group has the two dropdowns (Level 1..5 with per-link delay tooltips; No
sleep / 1 / 5 / 30 minutes); each change writes the whole panel immediately,
like the vendor app, and persists to `config.json`. The new `--settings
SLEEP LEVEL` CLI command writes the same panel and records its values in the
same ledger, which the tab re-reads every time it is entered. There is no
settings-read opcode — every capture, shim and USBPcap alike, shows the
vendor app only ever *writes* the panel — so the ledger is the only source of
truth the UI can have.

### Added
- `tools/aula_l99_hacky/capture/`: `wine_ioctl_shim.c` (LD_PRELOAD shim over
  `ioctl`/`read`/`write`; full payloads in both directions; events echoed to
  the console; a VID/PID + interface whitelist with `AULA_IOCTL_DEVICES` to
  override and `*` for everything), `build_shim.sh`, `run_vendor_capture.sh`
  (presets for the two settings sweeps), `parse_shim_log.py` (`--settings`
  tabulates the panel writes, `--verify` byte-checks sessions against the
  builders, `--hex` for `--send-hex` paste).
- `protocol.py`: `build_settings_blocks()` / `build_settings_transfer()`,
  anchored byte-for-byte against a live shim capture; `build_command(..., byte2=)`
  for the `0x17` header quirk; `SLEEP_TIME_MINUTES`,
  `RESPONSE_TIME_DELAYS_MS` / `RESPONSE_TIME_LINKS`.
- `cli.py`: `--settings SLEEP LEVEL`, recording the applied values in the
  GUI's config ledger.
- `config_tab.py`: the "Keyboard Settings" group with the two dropdowns, and
  `refresh()`, which re-reads the shared ledger when the tab is entered.
- Tests: the settings-block capture anchor, transfer framing/header and range
  validation; config-tab dropdown population, labels, emitted values,
  persistence, restore-without-writing and refresh-without-emitting.

### Changed
- `re_notes/settings_write.md`: the panel layout is corrected and confirmed —
  byte 6 = sleep time, byte 8 = response time (the earlier notes had them
  swapped), both slots on every write, with the sleep and response meanings
  recorded.
- `settings.py`: `keyboard_settings()` / `set_keyboard_settings()` — the
  shared ledger for the panel, written by the GUI on each change and by the
  CLI on each `--settings` write.

## [0.10.6] - 2026-08-07

**The Music tab's four settings controls now match the vendor app's
two-column layout.** Rhythm and Background Mode were label-beside dropdowns
stacked above two label-above-control sliders, all in a single column; the
vendor reference app instead lays out Rhythm and Amplitude in a left column
and Background Mode and Background Brightness in a right column, each
control's label sitting directly above it. `MusicTab._build_ui` now builds
the two columns as separate `QVBoxLayout`s combined in a `QHBoxLayout` — the
same "column builder + row" convention `user_lighting_tab.py`'s colour
picker already uses for its palette/channel columns — rather than
introducing a `QGridLayout`, which nothing else in the GUI package uses.

### Changed
- `music_tab.py`: Rhythm/Amplitude and Background Mode/Background Brightness
  now sit in their own columns, each with its label above its control,
  inside the existing "Music Settings" group box.
- `_build_labeled_slider`'s value readout now shows a `%` suffix (`"100%"`
  rather than `"100"`), matching the vendor app's slider labels.

## [0.10.5] - 2026-08-07

**The packaged build is now installable as a proper `.deb`, so the dist is no
longer a tarball the recipient has to unpack and wire up by hand.** `make_deb.sh`
packs the Nuitka-compiled `build/` tree into an apt package with
`dpkg-deb --build` on a staged tree rather than debhelper — there is no source
to compile, only a self-contained binary to lay down. The binary goes in
`/usr/lib/aula-l99-gui` (every file in the dist is read-only: the skin assets
and layout XML are parsed at import time, never written back), a three-line
wrapper on `/usr/bin` points at it — a symlink was deliberately avoided, since
Nuitka resolves its resource paths from the binary's location and `argv[0]` of
a symlink is the *link's* path — and the launcher entry, a 256x256 icon and the
changelog/copyright go under `/usr/share`. Unlike the tarball's per-user
`install.sh`, the `.deb` owns its own fixed paths, so its `.desktop` file is
written with the real `Exec=` line rather than an `@EXEC@` placeholder.

The dependencies are `Recommends` rather than `Depends` because the app
degrades gracefully without them: it checks `PATH` and shows a targeted error
when `ffmpeg` (video sources) or `arecord` (Music tab) is missing, so apt
installs them by default without making the package uninstallable without them.
The package's `postinst` refreshes the desktop database and reloads and
re-triggers udev best-effort, so a freshly plugged keyboard gets its hidraw
access rule without a reboot.

### Added
- `make_deb.sh`: stages `build/deb-root` from the existing `package.sh` dist
  (or runs `package.sh --rebuild` first on request), derives the Debian
  architecture from `uname -m` (x86_64 → amd64, aarch64 → arm64) and the
  version from `pyproject.toml`, and builds/verifies the `.deb` — `dpkg-deb
  --info` and `-c` always, `desktop-file-validate` and `lintian` when present.
  Builds to `build/aula-l99-gui_<version>_<arch>.deb` (~44MB).
- `packaging/90-aula-l99.rules`: the udev rule now shipped inside the package,
  granting the logged-in desktop session access to the keyboard's hidraw node
  for both the wired keyboard (`0c45:800a`) and the 2.4G dongle (`05ac:024f`),
  on USB interface 3 — `MODE="0660"`, `GROUP="plugdev"`, plus `TAG+="uaccess"`
  so systemd-logind hands the session access without any group membership.

### Changed
- `make_deb.sh` copies the dist wholesale minus the tarball's own `install.sh`
  and `@EXEC@` `.desktop` template: the `.deb` provides both properly under
  `/usr/share`, and shipping the per-user installer that would overwrite them
  would be wrong. The icon is reused from the dist's `icon.png` (itself derived
  from the vendor's `DeviceDriver.ico`), and the rules file lives outside the
  dist in `packaging/` since the tarball's own per-user install would have had
  no use for it.

## [0.10.4] - 2026-08-06

**The packaged build can now be put in the desktop environment's launcher.**
Nuitka has no `.desktop` support of its own — its icon options are Windows- and
macOS-only — so the dist now carries the pieces and an installer for them.
`install.sh` (shipped inside the unpacked build) rewrites an `@EXEC@`
placeholder in the launcher template with the binary's absolute path — only
known once the tarball is unpacked — and drops the `.desktop` file and a
256x256 icon into the per-user `~/.local/share/applications` and
`~/.local/share/icons/hicolor/256x256/apps`, so no root is needed and any
desktop environment picks them up. `--uninstall` removes them again. The icon
is derived at pack time from the vendor's own `DeviceDriver.ico`, whose largest
frame is 64x64, upscaled with Lanczos by the build venv's Pillow — the only
fitting launcher art the vendor ships.

### Added
- `packaging/aula-l99-gui.desktop`: the launcher template, with `@EXEC@`
  standing in for the not-yet-known binary path. Validated with
  `desktop-file-validate` (Categories is `Settings;HardwareSettings;`, which is
  the pair the validator wants).
- `packaging/install.sh`: installs the launcher and icon per-user; the binary
  path is escaped for sed (spaces quoted in `Exec=`, `&`/`\` escaped), the
  `update-desktop-database` refresh is attempted when present, and
  `--uninstall` removes the two files.
- `package.sh`: `--include-data-files` ships the `.desktop` template into the
  dist (alongside `install.sh`, which `cp`-s in with the executable bit set);
  the pack phase renders `icon.png` from the vendor ico via the build venv's
  Pillow. All four files land in the tarball, so the recipient unpacks, runs
  `./install.sh`, and has a launcher.

### Changed
- `tools/aula_l99_gui/README.md`: the packaged-build section mentions
  `./install.sh` (and `--uninstall`) inside the unpacked build.

## [0.10.3] - 2026-08-06

**Stopping the Music stream now hands the keyboard back to its own lighting.**
The 0x78 spectrum feed lights the keyboard as well as the panel's analyser,
and the keyboard stayed in that music mode after Stop -- the all-zero frame
that clears the panel leaves the keyboard lit, and it only returned to its
stored pattern when the app quit and the host session closed. The tab now
snapshots the keyboard's lighting before the stream starts and, on stop,
restores it the same way the User Lighting tab restores its base colours
after an animation: select `EFFECT_CUSTOM`, then a persistent `0x23` colour
write.

### Changed
- `music_tab.py`: `_start_stream` snapshots the keyboard's colours (via
  `read_colors`) before the feed overrides them, and `_on_stream_finished`
  restores them on stop by selecting `EFFECT_CUSTOM` and writing the colours
  through a `KeyboardWorker` -- skipped on failure and during shutdown (the
  keyboard returns to its stored pattern when the app quits, so a shutdown
  restore would start a thread the teardown would then have to wait for). A
  quick Stop -> Start waits out any restore still in flight and cancels a
  pending one.
- `re_notes/audio_spectrum_block.md`: the keyboard-lighting question is now
  answered -- the keyboard lights up from the 0x78 feed and stays lit after
  the feed stops, which is why the GUI restores it.
- Tests: the Music tab's snapshot/restore behaviour is covered -- the snapshot
  taken at stream start, the restore's `EFFECT_CUSTOM` + `0x23` transaction
  shape, and the failure/shutdown skip paths.

## [0.10.2] - 2026-08-06

**The Music tab's four controls now apply to a capture that is already
running.** They were read once at Start and frozen into the stream worker for
its whole run, so moving the Rhythm / Background Mode dropdowns or the
Amplitude / Background Brightness sliders mid-capture only changed the saved
settings in `config.json`; the panel kept drawing the old frame header and
level scaling until the stream was stopped and restarted. The worker now holds
the four values as a single snapshot it re-reads every frame, and the tab
pushes each control change onto the live worker, so the next frame carries the
new style/mode and rescales the levels to the new Amplitude.

**The Rhythm and Background Mode dropdowns were wired to the wrong bytes.**
The original guess put the Rhythm style on byte 1 (where `0x08` collided with
the "spectrum" effect) and the Background Mode on byte 0; a hardware check
reversed it -- moving the Rhythm dropdown changed the panel analyser's
background. The swap was confirmed, so Rhythm now drives byte 0 and Background
Mode byte 1, and the control defaults follow the captured wire bytes (`0x04`
on byte 0, `0x08` on byte 1).

**The Music Rhythm list was ordered wrong at the low end.** A byte-level
hardware check (sending the background byte as `0x00` vs `0x0B`) showed that
`0x00` clears the analyser background while `0x0B` draws a colour -- so **Off
is byte 0**, not the index-11 the vendor's language-file position implied. The
shared dropdown list now starts with Off and every other entry shifts up by
one, with the byte an entry sends equal to its new index.

### Changed
- `workers.py`: `AudioSpectrumWorker` keeps its four Music controls in one
  tuple snapshot instead of four attributes; a new `set_music_settings()`
  swaps it in with a single assignment (the same cross-thread model as
  `stop()`'s `_stop` flag), and `run()` reads the snapshot fresh each frame.
- `music_tab.py`: `_save_settings` now also calls
  `set_music_settings()` on the running worker, and logs it to the debug log;
  `_start_stream` uses the same `_music_settings()` helper.
- `protocol.py`: the audio block's header offsets are renamed to the
  confirmed reading -- `AUDIO_OFF_RHYTHM` (byte 0) and
  `AUDIO_OFF_BACKGROUND_MODE` (byte 1) replace the provisional
  `AUDIO_OFF_MODE`/`AUDIO_OFF_STYLE`, and `build_audio_blocks()` takes
  `rhythm=`/`background_mode=` to match. The two dropdown defaults swap to the
  captured wire values (`AUDIO_RHYTHM_DEFAULT` = 4, `AUDIO_BACKGROUND_MODE_DEFAULT` = 8).
  `AUDIO_RHYTHM_NAMES` is reordered so Off leads the list and index = byte.
- `cli.py`: `cmd_spectrum` gains `--spectrum-rhythm`, `--spectrum-background-mode`
  and `--spectrum-background-brightness` overrides for the block's three
  header bytes, so a non-default control value can be confirmed on hardware.
- `re_notes/audio_spectrum_block.md`: the Rhythm/Background Mode byte
  placement is corrected from hypothesis to hardware-confirmed, with the
  original swap documented and the Off = byte 0 finding recorded.
- Tests: the wire assertions follow the renamed offsets, the protocol test
  asserts the corrected Rhythm -> byte 0 / Background Mode -> byte 1 mapping
  and pins Off at index 0, and the GUI's dropdown tests expect Off first.

## [0.10.1] - 2026-08-06

**The Music tab now carries the four controls of the vendor's "Music Rhythm"
tab.** The Rhythm and Background Mode dropdowns are populated from the same
15-entry list the Windows app uses (its language strings 106-120), and the
Amplitude and Background Brightness sliders drive the height of the spectrum
and the panel screen's background. The four settings were confirmed from the
vendor app's own `t_musiclayer_data` SQLite schema (`foremode`,
`fore_amplitude`, `backmode`, `backb_right`); where they land on the wire is
documented as hypothesis rather than confirmed, since the only capture is at
default settings.

### Added
- `music_tab.py`: a "Music Settings" group with Rhythm and Background Mode
  dropdowns plus Amplitude and Background Brightness sliders, persisting to
  `config.json` under `music` and restoring on the next launch.
- `protocol.py`: `AUDIO_RHYTHM_NAMES` / `AUDIO_BACKGROUND_MODE_NAMES` (the
  15-entry shared list), the four control defaults, and a background-brightness
  byte written to the first never-written tail byte of the audio block.
- `settings.py`: `music_settings()` / `set_music_settings()` accessors.
- `AudioSpectrumWorker` now takes the four settings and sends them on every
  frame, scaling levels to the Amplitude so they agree with the scale byte.
- Tests: the worker's wire output carries the configured settings (Rhythm ->
  byte 1, Background Mode -> byte 0, Amplitude -> byte 2, Brightness -> tail);
  the settings round-trip and merge; the tab's four controls exist with the
  captured defaults and restore from disk.

### Changed
- `re_notes/audio_spectrum_block.md`: documents the Music Rhythm tab's four
  controls, the entry->byte mapping, and which bytes are hypothesis.

### Notes
- The Rhythm (byte 1, `0x08`) and Amplitude (byte 2, `0x64`) placements are
  corroborated by the single capture's default values; Background Mode
  (byte 0, `0x04`) and Background Brightness (tail byte 26, `0x00`) are best
  guesses that need a non-default capture or a hardware check to confirm.

## [0.10.0] - 2026-08-06

**The GUI can now drive the panel's spectrum analyser from live audio.** A new
Music tab captures from an ALSA input device via `arecord`, computes a 17-band
spectrum with a pure-Python Goertzel FFT, and streams it to the panel over the
keyboard's audio feed (opcode `0x78`, cable only) at ~21 frames/s, with a live
17-bar preview of exactly what the analyser renders.

### Added
- `audio_spectrum.py`: `arecord -l` device parsing, a log-spaced 17-band Goertzel
  spectrum with a Hann window and dB-scaled 0..100 levels, and the `arecord`
  command builder. Pure standard-library, no numpy, so the packaged build is
  unchanged.
- `music_tab.py`: the Music tab (audio-device picker + Refresh, Start/Stop, a
  hand-painted `SpectrumPreview` bar widget, status lines), wired to the keyboard
  `DeviceSelector` since the spectrum feed is a cable path.
- `AudioSpectrumWorker` in `workers.py`: owns an `arecord` subprocess and the
  hidraw transport for the whole run, sends `build_audio_frame()` per chunk,
  nothing retried — same shape as the colour-stream and monitor workers.
- Ten new tests in `tests/test_audio_spectrum.py` covering the Goertzel maths
  (a full-scale sine lights only its band; silence is all zeroes; clipping
  clamps), device parsing, the worker's wire output (commit → `0x78` → block,
  bands 17..22 zero), and its failure path.
- The `tab_music` icon slices (the vendor sheet was already in `assets/`, it was
  just never sliced or wired up).

### Changed
- `main_window.py`: Music tab inserted between Touchscreen and Config; the stream
  pauses colour polling like a User Lighting animation but is not "busy".
- `theme.py`: `TAB_ICONS["Music"] = "tab_music"`; `slice_skin.py` now slices the
  `tab_music.png` sheet.

### Notes
- The spectrum feed is a *cable-only* path, so Start is gated on the wired
  keyboard being selected; the dongle cannot carry it.
- The tab produces exactly the 17 bands the panel renders (wire bands 0..16);
  the remaining 6 of the 23 the block carries are zero-padded by
  `build_audio_blocks`.
- The first device listing is deferred to the first event-loop iteration: the
  `arecord -l` subprocess runs on a worker thread, and starting that thread
  inside `MainWindow.__init__` aborts Qt on teardown.

## [0.9.32] - 2026-08-06

**The audio spectrum feed is confirmed on hardware — and the panel's analyser
renders only 17 of the 23 bands.** Sent frames to a wired `0C45:800A`
keyboard and watched the panel: the commit and `0x78` command come back acked,
the data block echoes verbatim with the ack bit clear, and driving one band at
a time lights the expected bar in order. The display has 17 on-screen segments,
edge to edge, mapping to wire bands 0..16; bands 17..22 have no visible effect.
The wire format is unchanged — `AUDIO_BAND_COUNT` stays 23, since that is what
the feed carries; the 17-segment display is a panel property, not a protocol
constant.

### Changed
- `re_notes/audio_spectrum_block.md`: marked confirmed on hardware, added the
  17/23 display finding.
- `tools/aula_l99_hacky/README.md` and the top-level `README.md`: the spectrum
  feed is now in the confirmed list, with the 17-of-23 caveat.
- `cli.py`'s `--spectrum` help and module docstring: note the panel renders
  only the low 17 bands.

## [0.9.31] - 2026-08-04

**An oversized upload does not fail — it succeeds at writing over something
else.** A memory-safety audit of the whole tree found no reachable
out-of-bounds or use-after-free in the Python itself, and could not: every
buffer operation here goes through `bytes`/`bytearray`/`struct`, which
bounds-check and raise. The real equivalent is one address further out. The
panel acks every packet it is given, so nothing about a transfer's success
says the bytes landed where they were meant to, and `--width`/`--height` were
unbounded ints that reached `build_image_file()` directly.

The concrete case is `--height 960`: 614,411 bytes, whose final chunk is 11
bytes long — an already-solved `CRC_INIT` entry — so every packet of it built,
sent and acked normally while overwriting 221,195 bytes of the adjacent GIF
slot. Nothing anywhere reported a problem. The `CRC_INIT` lookup had been
acting as an accidental guard against this (an unsolved final-chunk length
raises rather than sending a bad CRC), which is why it had never been hit: it
only rejects the sizes it happens not to know, and 614,411 is one it does.

The bound now lives in `build_upload()` rather than in each frontend, so
nothing can reach the wire without passing it. `SLOT_CAPACITY` is derived from
the gaps between the three known base addresses — and, for two of the three,
that derivation is now confirmed against the panel's own firmware rather than
resting on the gaps alone. Deliberately *not* used as a boundary:
`0x04200000`, which the vendor binary references and which sits between the
photo-frame and GIF bases. An ordinary 320x480 photo-frame image is 307,211
bytes and so runs from `0x041E0000` to `0x0422B04B`, straight through it.
Whatever that address is for, the vendor's own writes overlap it, and using it
as a ceiling would reject uploads the device demonstrably accepts.

**The flash map is in the firmware, not in the Windows software.** Asked
whether disassembling the vendor's Windows binary would show how much memory
the GIF area gets, the answer for the host-side software is no: `pic_scan.dll`,
`Image2Bin.exe` and `SerialPortTool.exe` contain none of the three known base
addresses, and `DeviceDriver.exe` appears to contain two only through
misaligned reads straddling `(pointer, int)` pairs in an MFC table — it does
not contain `0x041E0000` at all, which is the tell. The host software never
knows the map; it is handed addresses. The firmware updaters do:
`Windows/AULA L99/firmware/L99 ISP V1.23.exe` and the screen reset firmware
exe each carry, twice, a six-entry list of flash bases on a uniform `0x60000`
stride — `0x04060000`, `0x040C0000`, `0x04120000`, `0x04180000`, `0x041E0000`,
`0x04240000`. The last three are the background, photo-frame and GIF bases, in
order, matching exactly. So the 393,216 figure for the first two is now
arrived at two independent ways, and `SLOT_STRIDE` names it. It also settles
`0x04200000` on firmer ground than "the vendor's own writes overlap it": that
address is not on the lattice at all, so it was never a slot base to begin
with. Still unidentified, as are entries 1-3.

**It does not follow that the GIF slot is also 393,216, and it briefly and
wrongly did.** GIF is the *last* entry, so unlike the other five its extent
cannot be got by subtracting a next base; assuming the stride continued was an
inference, and it was made and enforced before being checked properly. It is
false. The vendor ships 320x480 animations of 214 frames
(`gif/AULA L99/0.gif`) and 200 frames (`gif/用户动画(1)/*.gif`); fitting 214
frames into 393,216 bytes needs 1,837 bytes per frame, a rate only the flat
solid-colour test captures ever reached (`save_to_gif_3`, 2,048). Real content
in `save_to_gif_1` took 105,131 bytes per frame, putting that asset near 22 MB.
A 393,216-byte cap would refuse the vendor's own assets and make most of its
format unusable.

Worth recording because the mistake was not obviously a mistake: "no capture
exceeds 393,216 bytes" looked like independent corroboration and is worthless.
Every capture in `wireshark_dumps/` is a two- or three-frame hand-made test —
the vendor was never once observed uploading a real animation — so the maximum
across them (315,392, `save_to_gif_1`) describes the sample, not the hardware,
and sat just under the stride by coincidence. Reading a small sample as a bound
is the same error as reading a format ceiling as a flash extent, one level up.
`VENDOR_MAX_GIF_BLOB_BYTES` therefore stands, unchanged, as the GIF slot's
stand-in.

The second surface is the one place in this project where a malformed file
meets memory-unsafe code: the Touchscreen tab hands an arbitrary user-chosen
image, GIF or video to Pillow's C decoders and to `ffmpeg`. That can't be
fixed here, only bounded and kept current, which is what the pixel cap and the
raised dependency floor do.

Several things were checked and left alone, which is worth recording so they
are not "fixed" later: `build_packet()` fails *closed* on an unknown payload
length; the `QImage(bytes, …)` in `_to_pixmap` is `.copy()`-ed before its
backing buffer dies, which is the one available real use-after-free pattern
and was already handled; every `subprocess` call is list-form; `settings.py`
type-guards its JSON.

### Security
- `tools/aula_l99_screen/protocol.py`: `SLOT_CAPACITY` and
  `check_upload_fits()`, called from `build_upload()`. Background and
  photo-frame get 393,216 bytes each — the distance to the next known base,
  and independently the stride of the firmware's own partition list, now
  named `SLOT_STRIDE`. The GIF slot is the last entry in that list, so it has
  no next base to be measured against and the stride cannot be checked there;
  its entry stays `VENDOR_MAX_GIF_BLOB_BYTES` — "the most anything is known
  to have written here", which is still the strongest statement the evidence
  supports. An address with no entry passes unchecked: inventing a bound for
  somewhere nothing is known about would be worse than saying there isn't one.
- `tools/aula_l99_screen/cli.py`: `--address` is checked against the wire
  format's 32-bit field (it previously raised `struct.error` out of
  `build_packet`, which `main()` does not catch — a traceback rather than a
  message) and must be one of the known targets unless `--force-address` is
  given. `--width`/`--height` must be positive, and within the panel's own
  unless `--force-size` is given.
- The `VENDOR_MAX_GIF_BLOB_BYTES` ceiling is a refusal in both frontends
  instead of a warning printed on the way to uploading anyway. "How much
  flash is mapped above the GIF base is unverified" is a reason not to write
  there, not a reason to write there and mention it. 200 raw-bitmap frames is
  30.8MB against the 13.2MB ceiling, so this is reachable from the GUI with a
  long dithered animation, not a theoretical case.
- `tools/aula_l99_gui/touchscreen_tab.py`: `Image.MAX_IMAGE_PIXELS` is set to
  64x the panel's own area (~9.8Mpx) rather than left at Pillow's generic
  ~89Mpx default. Over it Pillow raises `DecompressionBombError`, which is
  **not** an `OSError` — so the two `except OSError` handlers around an
  `Image.open()` named it too, having previously let it through as an
  unhandled exception out of a GUI slot.
- `tools/aula_l99_gui/pyproject.toml`: Pillow floor raised from `>=10.0` to
  `>=11.3`. This is a security floor, not an API one — nothing here needs a
  feature newer than 10.0 — so it is worth raising again over time.
- `tools/aula_l99_gui/key_layout.py`: parses the layout XML with `defusedxml`,
  matching `user_lighting_tab`. Stdlib `ElementTree` expands internal
  entities. This file ships with the package rather than being user-chosen,
  but `package.sh` installs it into a writable tree, and there was no reason
  for the GUI's two XML readers to have different footing.

### Added
- `tools/aula_l99_screen/tests/test_cli_args.py`: the upload arguments had no
  coverage at all, which is part of why this went unnoticed — they decide
  what gets written where, and the device is no help in telling you when they
  are wrong.
- Tests for the slot bounds (including the exact `--height 960` overrun and
  the `force=` escape hatch), non-finite clip values, and a short block
  reaching `parse_color_blocks`. 18 in total; the suite is 149 passing.
- Three further tests pinning what the firmware table does and does not
  license: the two measurable slots match `SLOT_STRIDE`, the GIF cap stays
  *above* it, and `VENDOR_OBSERVED_MAX_GIF_BLOB_BYTES` is never used as a
  bound. Regression tests against a wrong turn rather than against a bug —
  the table invites the inference, so the next reader should meet the
  counter-evidence before repeating it.
- `tools/aula_l99_screen/re_notes/flash_slot_table.md`: file offsets of all
  four copies of the table, the hexdumps, the parallel per-slot RAM pointer
  array at `0x0081350C`+ that follows it, the per-capture frame counts and
  write extents, the host-binary dead end, and a reproduction script. Leads
  with both the finding and the non-sequitur, and ends with the cheapest
  remaining lead: there is still no capture of the vendor uploading one of
  its own stock GIFs, which would give the real per-frame rate and the true
  maximum at once.
- `build_upload(..., force=True)`: the deliberate-experiment path. This is a
  reverse-engineering tool and writing outside a known slot is a legitimate
  thing to want to try, so the CLI exposes it via `--force-size` /
  `--force-address`. The GUI does not — overwriting unidentified flash is not
  a button a GUI should have.

### Fixed
- `tools/aula_l99_gui/touchscreen_tab.py`: `_sane_clip()` returns `CLIP_FULL`
  for any non-finite component. `min`/`max` propagate NaN rather than
  clamping it, so every bound in a function whose whole job is "forced back
  inside the source" was a no-op for one, and `float("nan")` parses cleanly
  enough that `_source_from_csv_row`'s own `except` never saw it either. It
  surfaced downstream as `cannot convert float NaN to integer` out of
  `_crop_box`, or an unparseable `crop=iw*nan:…` for a video. Infinities do
  clamp cleanly and are folded into the same rule anyway: a saved clip
  holding one is corrupt either way, and `CLIP_FULL` is already what a row
  that cannot describe its framing loads as.
- `_video_duration_seconds()` (GUI) and `_video_source_frames()` (CLI):
  `ffprobe` reports `inf` for some streams, which passed a `> 0` check and
  then divided down to `fps=0`.
- `tools/aula_l99_hacky/protocol.py`: `parse_color_blocks()` length-checks its
  blocks, as `parse_stream_blocks()` and `parse_audio_block()` already did.
  Not reachable today — both callers read via `get_feature()`, which always
  returns exactly `PACKET_SIZE` bytes because the ioctl fills a preallocated
  buffer — but it fails *silently*: the slicing returns a two-element
  "colour" for a short block rather than raising, so a caller switching to
  `read_report()` (which returns whatever arrived) would get wrong colours
  instead of an error.
- `tools/aula_l99_gui/user_lighting_tab.py`: a malformed `keycode` or
  `rgbvalue` skips its `<item>` instead of aborting the whole profile load.
  One bad attribute in a file shared across vendor models should not cost the
  user the other 83 keys — the same policy the file already applied to an
  unrecognised keycode.
- `tools/aula_l99_gui/key_layout.py`: `_parse()` failures are re-raised naming
  the file. This runs at import time, so a missing element or attribute was
  otherwise a bare `TypeError` out of `import main_window`, before there was
  a window to show anything in.
- `tools/aula_l99_gui/monitor_stats.py`: a truncated `/proc/stat` cpu line
  returns `None` like every other unreadable case, rather than `IndexError`.
- `tools/aula_l99_hacky/device.py`: `_ioctl_code()` rejects a size wider than
  the field's 14 bits, which would otherwise carry into the direction bits
  and build a different ioctl entirely. Latent — callers pass
  `PACKET_SIZE + 1` — so this documents the constraint as much as it enforces
  it.

### Changed
- `tools/aula_l99_screen/protocol.py`: `build_gif_blob()`'s palette-size bound
  is checked where the palettes are assembled, before any content is built,
  instead of while the header is being filled in. A palette index goes into a
  single byte of content in both modes, so an over-256-slot frame used to die
  first in `bytearray.append` with `byte must be in range(0, 256)` rather than
  the real explanation. Reachable only on the undithered path:
  `is_ramp_legal_color` admits 252 colours, but `is_safe_gif_color` admits
  any colour whose brightest channel is 255, which is ~195,000 of them.
- `tools/aula_l99_gui/README.md`: a note that Pillow and `ffmpeg` are worth
  keeping current, and why — the Python here can be wrong but not corrupted;
  their decoders are where that distinction stops holding.

## [0.9.30] - 2026-08-04

**The GUI can now be handed to someone who does not have Python, which was the
only real argument for rewriting it in C++.** Sizing that rewrite came to 5–8
weeks across the ~9,200 lines of the GUI and the two protocol libraries, on the
strength of three claimed wins: startup, memory, and not shipping a venv. Only
the third survived measurement. `package.sh` compiles the existing Python with
Nuitka into a self-contained tree — its own CPython, its own Qt, the skin
assets — and the result reaches its first window in ~0.37s against ~0.34s
interpreted, at ~126MB RSS against ~130MB. It is fractionally *slower* and no
smaller in memory, because Qt sets both floors and compiling the Python does
not move them. That is worth recording as the answer to the performance
question rather than leaving it to be re-asked: a C++ port would inherit the
same floors.

Two details of the build were not obvious and are the reason it is a script
rather than a documented command. `assets/gif/` is 113MB of the 115MB assets
tree and no code path opens it — saved animations go to `QStandardPaths`'
`AppDataLocation` — so the three directories that *are* read get named
individually, and a future asset directory will surface as a missing file
instead of quietly re-inflating the tarball. And `aula_l99_gui/font/` sits
outside `assets/` entirely; omitting it fails silently, because
`theme.load_font()` returns `""` by design and Qt falls back to the platform
font, so the build would look correct while losing the skin's typography.

### Added
- `package.sh`: builds `build/aula-l99-gui-<version>-<arch>.tar.gz` (~56MB
  packed, 147MB unpacked) via Nuitka `--standalone`. Verified by unpacking
  elsewhere and running under `env -i` — no absolute paths are baked in, and
  the only outside requirement left is `ffmpeg`, for video sources.
- The build creates its own `tools/.venv-build` from the declared dependencies
  rather than reusing the dev venv, which carries ~500MB of packages nothing
  imports (`onnxruntime`, `opencv-python`, `numpy`) that Nuitka's
  import-following could otherwise drag in. It installs `PySide6_Essentials`
  rather than `PySide6`, since only QtCore, QtGui and QtWidgets are used.
- Python 3.13 is pinned when `uv` is available: Nuitka 4.1.3 still calls 3.14
  experimental. 3.14 was tested and both builds run identically, so the
  fallback path warns rather than refuses.

### Changed
- `README.md`, `tools/aula_l99_gui/README.md`: a packaged build is documented
  alongside the source checkout, including the measured figures above so the
  tradeoff is stated rather than implied.
- `.gitignore`: `.venv-build/` added — the existing `.venv/` rule does not
  match that name.

## [0.9.29] - 2026-08-04

**A fresh install following the documented steps could not start the GUI.**
`user_lighting_tab` has imported `defusedxml` at module scope since saved
profiles became XML, but the module was declared nowhere — not in
`aula_l99_gui/pyproject.toml`, not in the `pip install` line of either
README. Every existing checkout has it sitting in its venv, which is the only
reason this went unnoticed; a new one following the instructions would import
`main_window`, reach the User Lighting tab and die on `ModuleNotFoundError`
before showing a window. Documenting the requirement without also declaring
it would only have moved the error, so both are fixed here. Checking the
claim it replaced turned up a second inaccuracy in the root README: the
touchscreen CLI was never stdlib-only either.

### Fixed
- `tools/aula_l99_gui/pyproject.toml`: `defusedxml` added to
  `dependencies`. This affected `uv` users specifically, since `uv run
  --project aula_l99_gui` builds its environment from this file alone and
  would produce one the GUI cannot start in.
- `tools/aula_l99_gui/README.md`: the install line is
  `pip install PySide6 pillow defusedxml`, with a note that the import is at
  module scope and therefore not optional.

### Added
- `README.md`: a Requirements section — the Python floor (3.10+ for the GUI,
  3.9+ for the keyboard CLI), a table of the four third-party modules against
  what each is actually needed by, and a single `pip install` line. `pytest`
  is listed as test-suite-only rather than left to be discovered.
- `README.md`: `ffmpeg`/`ffprobe` recorded as a `PATH` requirement for video
  sources, kept out of the pip list because it is an external binary. It
  applies to both the GUI's Touchscreen tab and the CLI's video path.

### Changed
- `README.md`: "The GUI needs `PySide6` and `pillow`; the CLIs are
  stdlib-only" was wrong in both halves and is replaced. `aula_l99_screen`
  imports Pillow in five places across `cli.py` and `protocol.py`. The import
  is lazy, so the accurate line is narrower than "needs Pillow": device
  discovery, `--describe` and uploading a pre-built `.bin` need nothing at
  all, while `--upload`, `--upload-gif` and `--convert` each exit with an
  install hint instead of a traceback. `aula_l99_hacky` is the one component
  that is genuinely stdlib-only — hidraw is driven through `fcntl`/`os`.

## [0.9.28] - 2026-08-04

**The preview's crop box decides what reaches the panel, so a source no
longer has to be the panel's shape to be sent well.** Every source was
stretched whole onto 320x480, which is fine for something already 2:3 and
disfiguring for anything else — a 16:9 still had no framing to choose, only
a distortion to accept. Each source now carries its own clip region, dragged
directly on the preview: drag inside the box to move it, an edge or corner
to resize it, and only what's inside is sent. The box is free-form rather
than locked to 2:3; a crop that isn't the panel's shape still stretches to
fit, exactly as an unclipped source of the wrong shape already did, so the
constraint is visible in the box's proportions instead of being enforced
against the user. The clip is a property of the file, so a GIF or video gets
one box applied to all of its frames, and it is written into the saved
animation's config alongside the path.

### Added
- `tools/aula_l99_gui/touchscreen_tab.py`: `SourceImage`, the build list's
  entry type — a path plus `clip_x`/`clip_y`/`clip_w`/`clip_h`. The clip is
  held as fractions of the source rather than pixels, so one representation
  describes a `.png`, a `.gif` and an `.mp4` without any of their dimensions
  having to be known first: ffmpeg's `crop` filter takes `iw`/`ih`
  expressions, and Pillow's `crop()` is one multiply away. It also means a
  clip survives its source being re-exported at another resolution. The
  default is the whole image, which is what every earlier save reloads as.
- `tools/aula_l99_gui/touchscreen_tab.py`: `_sane_clip()` and `_crop_box()`.
  The first forces a clip back inside the source — the only things that can
  produce an escaping one are a drag and a hand-edited config, so both are
  clamped rather than rejected. The second converts to a pixel box for
  Pillow, returning `None` for a full-frame clip so every caller skips the
  crop entirely, and widening a sub-pixel box to at least one pixel: rounding
  it to nothing hands Pillow a zero-width image that then fails to resize.
- `tools/aula_l99_gui/touchscreen_tab.py`: clip-box interaction on
  `PreviewLabel` — hit-testing for the four edges, four corners and the box
  interior, hover cursors for each, and `clip_changed`/`clip_committed`
  signals. The drag maths runs in fractions of the source throughout, so it
  holds at whatever scale the preview happens to be drawn at. `clip_changed`
  fires continuously and only moves the box and the readout; `clip_committed`
  fires once on release for the work too expensive to redo per mouse-move,
  namely re-reading the file to restyle the source strip's thumbnail.
- `tools/aula_l99_gui/touchscreen_tab.py`: a `crop W x H` readout and a
  "Reset Crop" button under the preview, quoting the crop in the source's own
  pixels since that is the resolution it is actually taken at. Both are kept
  narrow enough not to widen the column past the preview itself, which is
  what fixes that group's width — the full detail is in the readout's
  tooltip.
- `tools/aula_l99_gui/touchscreen_tab.py`: `_load_source_frame()`, the first
  frame of a source at its own size and unclipped. Split out of
  `_load_source_thumbnail()` because the preview needs the whole source to
  aim the box against, where the strip wants the cropped result.
- `tools/aula_l99_gui/tests/test_touchscreen_tab.py`: clip clamping, pixel
  mapping, the sub-pixel collapse, and config round-tripping including a row
  written before clipping existed and a row whose clip columns are garbage.

### Changed
- `tools/aula_l99_gui/touchscreen_tab.py`: the preview fits the source at its
  own aspect inside the panel-shaped frame and paints the box over it, dimmed
  outside and with handles on the edges and corners. 0.9.27 stretched it to
  fill the frame, which was the honest thing to show while the upload
  stretched the whole source — but the framing is the box's job now, and a
  box can only be aimed against a picture whose real shape and full extent
  are both visible. The frame itself still tracks the panel's 320x480.
- `tools/aula_l99_gui/touchscreen_tab.py`: `_load_image()`,
  `_frames_from_gif()` and `_extract_video_frames()` take a clip and apply it
  before the resize to 320x480, via the shared `_crop_to_panel()` for stills
  and GIF frames and a `crop=iw*…:ih*…` filter for video. The video filter
  chain puts `fps` first, so the crop and scale only run on the frames being
  kept.
- `tools/aula_l99_gui/touchscreen_tab.py`: `.mp4` sources no longer
  letterbox. `_extract_video_frames()` scaled with
  `force_original_aspect_ratio=decrease` and padded the remainder, which was
  reasonable while there was no way to choose the framing — it would now
  quietly add bars around a region the user had deliberately picked, and
  video was the one source type whose result didn't match the preview.
  Stills and GIFs have always stretched; video now does too.
- `tools/aula_l99_gui/touchscreen_tab.py`: the source strip's thumbnails show
  each source cropped, so a tile whose box has been narrowed looks narrowed.
  Committing a drag re-icons that one tile rather than calling
  `_refresh_source_strip()`, which clears the list, drops the selection and
  would take the preview down with it on every drag.
- `tools/aula_l99_gui/touchscreen_tab.py`: `_save_animation_config()` appends
  four clip columns to each source row of the animation's `.csv`.
  `_source_from_csv_row()` reads a row that is missing them, or whose values
  don't parse, as an unclipped source — a save that can't describe its
  framing is still perfectly usable as a source list, and refusing it would
  lose the paths too. Saves written before this release load unchanged.
- `tools/aula_l99_gui/touchscreen_tab.py`: the sources handed to the
  conversion thread are copies. That thread writes them to the config long
  after the GUI thread is free to carry on editing clips.

## [0.9.27] - 2026-08-03

**The Touchscreen tab is laid out around the preview now, and the preview is
the shape of the screen it is previewing.** It used to be a fixed 200x300
tucked under the source strip, with "Send to Device" and "Animation
Settings" stacked below it across the full width. The preview now sits in its
own group on the left, running from the source strip down to the progress
bar, with both control groups in a column to its right; the progress bar
still spans the bottom. Its width follows its height at the panel's own
320x480, so the frame is the panel's shape at any window size, and the image
fills it edge to edge rather than sitting in the middle of a taller box with
the styled background showing as grey bands above and below it.

### Added
- `tools/aula_l99_gui/touchscreen_tab.py`: `PreviewLabel`, a `QLabel` sized
  by its layout instead of its contents. It keeps the unscaled pixmap and
  rescales from it on each resize, so repeatedly growing and shrinking the
  window doesn't compound scaling losses. Qt offers height-for-width but not
  the reverse, so the width is set from `resizeEvent()`; that settles in one
  extra layout pass, since the widget's width never feeds back into its own
  height. The vertical size policy is `Ignored` deliberately — a policy that
  honoured the pixmap's size hint would let the rescale feed a new hint back
  into the layout and oscillate.
- `tools/aula_l99_gui/touchscreen_tab.py`: `PREVIEW_MIN_HEIGHT`,
  `PREVIEW_MAX_WIDTH`/`PREVIEW_MAX_HEIGHT` (taken from `PANEL_WIDTH`/
  `PANEL_HEIGHT`, so they can't drift from the real panel) and
  `PREVIEW_SOURCE_SIZE`, which loads the preview at 2x the panel so it stays
  sharp on a tall window. The preview never grows past 1:1 with the panel;
  beyond that the extra height becomes padding under it rather than a taller
  image, so the column still reaches the progress bar.

### Changed
- `tools/aula_l99_gui/touchscreen_tab.py`: `_build_ui()` puts the preview and
  the control groups in a row between the source strip and the progress bar,
  with that row carrying the column's stretch. The preview moved out of
  "Source Images" into its own `_build_preview_group()`.
- `tools/aula_l99_gui/touchscreen_tab.py`: "Send to Device" stacks its three
  buttons vertically with the packet-gap spinner on its own row beneath them
  — side by side they no longer fit the narrower column.
- `tools/aula_l99_gui/touchscreen_tab.py`: the preview scales with
  `IgnoreAspectRatio`. The frame is already the panel's aspect, and the
  upload stretches to the panel too (`_load_image()` and `_frames_from_gif()`
  both `resize()` straight to 320x480 without preserving aspect), so the
  preview now shows what will actually be sent. `.mp4` sources remain the
  exception: `_extract_video_frames()` letterboxes via ffmpeg, so for video
  the preview stretches where the upload pads.

## [0.9.26] - 2026-08-03

**A Customized Animation can now be far larger than anything the vendor app
could ever have sent, and says so.** 0.9.25 capped the frame count at the
vendor's `gif_maxframes="200"` (since confirmed against the Windows app),
which bounds the count but not the size: raw-bitmap mode — this project's
own addition, for dithered content whose RLE encoding would overflow the
16-bit content-length field — emits a fixed `width*height` bytes per frame
where the vendor's encoder structurally tops out at 65535. So 200 dithered
frames come to 30.8 MB against the 13.2 MB ceiling implied by the vendor's
own two limits, 2.3x more. Nothing above `GIF_FLASH_BASE` appears in any
capture, so how much flash is actually mapped there is unknown; the GUI's
debug log and the CLI now report crossing that line before uploading.
Deliberately a warning and not a refusal — the upload may well be fine, but
it is outside the range anything is known to have written.

### Added
- `tools/aula_l99_screen/protocol.py`: `VENDOR_MAX_GIF_BLOB_BYTES` — the
  largest blob the vendor's own encoder could produce, derived rather than
  captured as `MAX_GIF_FRAMES * (20 + 528 + 0xFFFF)` = 13,216,600 bytes.
  `GIF_TOC_ENTRY_SIZE` (20), which the TOC builder now uses in place of the
  two literals sitting next to it.
- `tools/aula_l99_screen/tests/test_protocol.py`: a vendor-shaped maximum
  upload lands exactly *on* the ceiling rather than over it, so the warning
  cannot fire on a legitimate upload, while 200 raw-bitmap frames do exceed
  it.

### Changed
- `tools/aula_l99_gui/touchscreen_tab.py`, `tools/aula_l99_screen/cli.py`:
  both report an over-ceiling blob before starting the transfer, naming the
  size, the ceiling, and why dithered frames encode so much larger.

## [0.9.25] - 2026-08-03

**A Customized Animation built from a long source failed outright, after
spending minutes getting there.** The GIF container's table-of-contents
carries its frame count in a single byte, so `build_gif_blob()` raised
`ValueError: byte must be in range(0, 256)` for any source of 256 frames or
more. Nothing capped the frame count on the way in, so a 4883-frame GIF was
decoded in full, resized frame by frame, and written out as an 82 MB local
backup copy before the encode reached that field and gave up. Sources are now
sampled down to the vendor's own `gif_maxframes="200"` *before* any frame is
decoded, and the encoder rejects an over-long frame list up front with an
explanation instead of a bytearray range error.

The same build was also far slower than it needed to be, on every path it
touched. Measured end to end on that 4883-frame source: it now completes in
64s at 404 MB peak RSS, where before it failed after roughly twice that time
and 2.7 GB.

| stage | before | after |
|---|---|---|
| decode + sample | 56.3s / 2686 MB | 46.4s / 189 MB |
| local `.gif` backup | ~15.6s | 0.5s |
| `build_gif_blob` | ~48s | 16.1s |
| `build_upload` | ~11s | 1.2s |
| result | **ValueError** | 30.8 MB blob, 15290 packets |

Non-dithered uploads are byte-for-byte what they were. Dithered ones are not:
the pixel pattern comes from Pillow's dithering now (see below).

### Added
- `tools/aula_l99_screen/protocol.py`: `MAX_GIF_FRAMES` (200, the vendor's
  limit from `layouts/rgb-keyboard.xml`) and `GIF_FRAME_COUNT_MAX` (255, what
  the TOC field can physically express). `RAMP_COLORS`, the full 252-entry
  product of the three per-channel ramps. `_as_rgb_bytes()`, `_rgb_tuples()`,
  `_distinct_colors()`, `_pillow_ramp_palette()`, `_dither_rgb_pillow()`,
  `_dither_rgb_bytes()` and `_gif_token_count()`.
- `tools/aula_l99_gui/touchscreen_tab.py`: `_evenly_spaced_indices()` and
  `_per_source_frame_budget()` — which frames to keep, and how the allowance
  is split when several multi-frame sources are queued.
- `tools/aula_l99_gui/tests/test_touchscreen_tab.py`: frame-budget tests —
  sampling spans the whole source rather than truncating to its opening,
  spacing is even, the allowance splits between multi-frame sources and
  ignores stills, and a sampled source always fits the format.
- `tools/aula_l99_screen/tests/test_protocol.py`: the frame-count ceiling is
  accepted and one past it is rejected; an empty frame list is rejected; the
  shipped blob carries a real payload CRC; `crc16_packet()` matches a
  bit-by-bit reference; bytes and tuple frames build identical blobs and
  identical error text; both dither paths are ramp-legal and leave
  ramp-legal regions untouched.

### Changed
- `tools/aula_l99_gui/touchscreen_tab.py`: `_frames_from_gif()` and
  `_extract_video_frames()` take a frame budget and decide what to keep
  before decoding anything — for video, ffprobe is used to lower the sampling
  rate so the budget spreads across the whole clip rather than truncating it.
  The Touchscreen debug log now says how many of the source's frames were
  used.
- `tools/aula_l99_screen/protocol.py`: `dither_frame_floyd_steinberg()` uses
  Pillow's C Floyd–Steinberg against a palette built from `RAMP_COLORS`,
  falling back to the pure-Python implementation when Pillow is absent — the
  module still imports and its tests still run with no Pillow installed.
  Measured 182ms → 7.1ms on a noisy 320x480 frame and 190ms → 1.9ms on
  photo-like content. The output is a different pixel pattern, always
  ramp-legal, and scored marginally closer to the source on every image
  tried; regions already on the ramp come through untouched, which is what
  the CRC-length tuning pass depends on.
- `tools/aula_l99_screen/protocol.py`: `crc16_packet()` is table-driven,
  reusing `crc16_modbus()`'s `_CRC16_TABLE` (same reflected polynomial, only
  the initial value differs). `build_gif_blob()`'s length-probing pass skips
  the payload CRC it would only throw away, and rebuilds with it when that
  pass turns out to be the blob being returned.
- `tools/aula_l99_screen/protocol.py`: frames may be flat RGB888 `bytes` as
  well as `list[(r, g, b)]` — 460800 bytes against 12.3 MB for one 320x480
  frame, which at 200 frames is 92 MB against 2.5 GB. Dithering happens one
  frame at a time rather than building a second full list, a frame's run list
  is dropped once it is known to be raw-bitmap mode, and the colour gate
  checks each frame's distinct-colour set instead of every pixel.
- `tools/aula_l99_gui/touchscreen_tab.py`: `_save_frames_as_gif()` maps every
  frame to one shared palette sampled across the animation (78ms → 5ms per
  frame, same file size); `_pixels_from_image()` returns `image.tobytes()`;
  `_extract_video_frames()` slices ffmpeg's rgb24 output directly;
  `_ensure_safe_colors()` scans distinct colours; `_build_gif_packets()`
  releases the frames and the blob once the next stage has what it needs.
- `tools/aula_l99_screen/cli.py`: `_gif_source_frames()` applies the same
  sampling and reports it; `_pixels_from_image()` returns
  `image.tobytes("raw", "RGB")`, replacing the
  `get_flattened_data()`/`getdata()` pair.

## [0.9.24] - 2026-08-02

**The GUI now completes detection and connection via the 2.4G dongle.**
Previously the Device tab treated a dongle-only setup as unsupported ("the
dongle's packet format has never been captured", Test Connection disabled).
With the dongle handshake confirmed on real hardware (0.9.23), the GUI now
recognizes the dongle as valid hardware: the Device tab shows the status line
instead, Test Connection works over the dongle using the same
session-init/session-query handshake, and the lighting/colour/clock features
remain disabled with the status line explaining they are cable-only. The
title-bar connection badge (left of the minimise button) now follows the
connection: the 2.4G radio-wave icon while the keyboard is attached through
the dongle, the USB-plug icon on the cable.

### Added
- `tools/aula_l99_gui/device_tab.py`: `DONGLE_DETECTED_MESSAGE` replaces the
  stale `DONGLE_UNSUPPORTED_MESSAGE`; `DeviceSelector.current_device()` (the
  picker already exposed `current_path()`), used by the connection test to
  distinguish dongle from cable; `DeviceSelector.changed` now also carries the
  resolved device's connection kind ("cable"/"dongle"/"screen").
- `tools/aula_l99_gui/theme.py`: `DONGLE_MODE_ICON` (`24g_mode.png`) and a
  `connection_icon(kind)` helper choosing between it and `USB_MODE_ICON`.
- `tools/aula_l99_gui/tests/test_workers.py`: `KeyboardWorker` path tests — the
  dongle handshake acks and sends 33-byte interrupt writes, tolerates a
  different session-init version byte, and fails on a mismatched reply; a cable
  regression test guards the refactor.
- `tools/aula_l99_gui/tests/test_device_tab.py`: `_connection_kind` and
  `connection_icon` tests, pinning the dongle badge to `24g_mode.png`.

### Changed
- `tools/aula_l99_gui/workers.py`: `KeyboardWorker` takes a `dongle` flag and
  switches transport accordingly — interrupt reports (`write`/`read_report`,
  replies compared with `dongle_replies_match()`) vs the cable feature reports
  (`set_feature`/`get_feature`, `_is_acked`).
- `tools/aula_l99_gui/device_tab.py`: `_on_handshake()` builds
  `build_dongle_handshake()` for the dongle and `build_cable_handshake()`
  otherwise; Test Connection now enables on any recognized keyboard (cable or
  dongle) rather than only the cable.
- `tools/aula_l99_gui/main_window.py`: the monitor-stream auto-resume only
  triggers when the cable keyboard is usable (`enabled`), not merely found —
  it never attempts the cable-only stream over the dongle. `_update_usb_icon()`
  switches the title-bar badge to the 2.4G icon when the keyboard is attached
  via the dongle.
- `tools/aula_l99_gui/README.md`: Device tab section updated to say the dongle
  is recognized and Test Connection works on either connection, with the
  cable-only features noted.

## [0.9.23] - 2026-08-02

**The 2.4G dongle path is now confirmed on real hardware.** Previously it was
untested prior art inherited from the AULA F75 MAX; plugging the L99's own
dongle (`05AC:024F`, interface 3) in and running the probes showed the
handshake works unchanged and an RTC-set returns the prior-art ack. The one
discrepancy — byte 11 of the session-init reply, `0x29` here vs `0x08` on the
F75 — is a stable per-device firmware/build version, not link state: identical
across sessions and before/after the keyboard pairs. The tool's old exact-match
check therefore flagged every dongle run as a warning; it now compares with
that byte (and the checksum byte that necessarily follows it) excluded, while
still validating the reply's checksum.

### Added
- `tools/aula_l99_hacky/protocol.py`: `dongle_replies_match()` and
  `SESSION_INIT_VERSION_BYTE`, with the dongle-path docstring updated from
  "NOT CONFIRMED" to confirmed on the L99.
- `tools/aula_l99_hacky/tests/test_protocol.py`: tests pinning `SESSION_INIT_IN`
  to the real dongle's bytes and the version-byte tolerance of
  `dongle_replies_match()` (version byte and its checksum may differ; anything
  else must not, and a corrupt checksum is rejected).

### Changed
- `tools/aula_l99_hacky/protocol.py`: `SESSION_INIT_IN` corrected to the L99
  dongle's own reply (byte 11 `0x08` → `0x29`, checksum `0x54` → `0x75`).
- `tools/aula_l99_hacky/cli.py`: `_run_dongle()` uses `dongle_replies_match()`,
  so `--handshake`/`--rtc` on the dongle no longer print a spurious
  "reply did not match the value from prior art" warning; module docstring and
  the cable-only guard message now say the dongle implements handshake + RTC-set.
- Both READMEs: the dongle path is listed as confirmed (handshake + RTC-set),
  with the session-init version byte documented and the still-untested dongle
  colour/effect/settings commands listed as open work.

## [0.9.22] - 2026-08-02

**`compile.sh`'s whole-tree syntax check no longer trips over the GUI's own
venv.** `compileall` walked into `tools/aula_l99_gui/.venv`, where PySide6
ships non-Python files (Jinja templates) with `.py` suffixes that are not
valid Python, so the check failed on the venv rather than the project.

### Fixed
- `compile.sh` now excludes the venv from the syntax check
  (`-x '(__pycache__|\.venv)'`).

## [0.9.21] - 2026-08-02

**The monitor toggle's state now survives restarts, in a config file any
component can read.** The previous run's "Send CPU/GPU Load" state is saved to
`~/.config/aula_l99/config.json` (or `$XDG_CONFIG_HOME/aula_l99/config.json`)
and restored on the next launch: the checkbox comes back checked and the stream
auto-resumes the first time the keyboard shows up. Because the file is plain
JSON with no Qt dependency, a future headless daemon can start in exactly the
same running/not-running state by reading the same file.

### Added
- `tools/aula_l99_gui/settings.py`: shared JSON settings — `monitor_running()`
  / `set_monitor_running(bool)`, with atomic temp-file writes and graceful
  fallback to defaults for missing, unreadable or malformed files.
- `tools/aula_l99_gui/main_window.py`: persists every monitor-state change
  (a user toggle or a self-ended stream alike) and, once per launch, restores
  the saved state when the keyboard is present — deferred until the device is
  found so a resume can't fire a "No device selected" warning.
- `tools/aula_l99_gui/tests/test_settings.py`: settings tests (round-trip,
  atomic writes, malformed/unreadable config, plain-JSON format).

### Notes
- A graceful quit does not persist "off": KeyboardTab's shutdown stops the
  stream but deliberately skips the state change, so closing the app with the
  stream running leaves it running for the next launch.

### Fixed
- Startup crash when the saved state was "running": the loading overlay was
  created after the first device refresh could already emit `busy_changed` via
  the auto-resumed monitor stream, so `_on_any_busy_changed` hit
  `_loading_overlay` before it existed (`AttributeError`). The overlay is now
  created before any wiring or refresh.

## [0.9.20] - 2026-08-02

**The GUI can now drive the touchscreen's system-monitor readout itself: a
Config-tab toggle streams the host's CPU/GPU load to the panel every 5s, the
way the vendor app streams its stats at ~1 Hz. The load source is a new
dependency-free Linux sampler (`/proc/stat` deltas for CPU; `nvidia-smi` or
the drm `gpu_busy_percent` sysfs node for GPU), and the stream is coordinated
with colour polling exactly like a User Lighting animation: it holds the
keyboard's hidraw handle for its whole run, so polling and one-shot RTC writes
stand off while it is active, but it is not "busy" — no loading overlay, and
closing the app just stops it.**

### Added
- `tools/aula_l99_gui/workers.py`: `MonitorStreamWorker` — sends
  `build_rtc_transfer` every `period` seconds on one open transport until
  `stop()`, reporting each send's load via a `sent(cpu, gpu)` signal. The
  inter-send sleep is sliced so `stop()`/shutdown return within ~50ms even on
  the 5s period, and a missed ack is counted but not retried (the next send
  is 5s away anyway).
- `tools/aula_l99_gui/monitor_stats.py`: `MonitorSampler` — dependency-free
  CPU/GPU load source. CPU is the busy share of `/proc/stat`'s aggregate `cpu`
  line between samples; GPU is `nvidia-smi` when on PATH, else the first
  `/sys/class/drm/card*/device/gpu_busy_percent` node, else 0.
- `tools/aula_l99_gui/keyboard_tab.py`: monitor-stream lifecycle
  (`set_monitoring`, `_start/_stop_monitor_stream`, `monitoring_changed`,
  `monitor_loaded`) and a `shutdown` stop; `_run_transactions` refuses a
  one-shot RTC write while the stream is active.
- `tools/aula_l99_gui/config_tab.py`: "System Monitor" group — a "Send
  CPU/GPU Load" checkbox toggle (the same themed control the other boolean
  settings use) and a live readout of the last sent values. The toggle stays
  clickable while checked so the stream can always be stopped.
- `tools/aula_l99_gui/main_window.py`: wires the toggle to KeyboardTab, pauses
  colour polling while monitoring (with the same aggregate busy the User
  Lighting animation uses), and disables the Config tab's other controls for
  the duration.
- `tools/aula_l99_gui/tests/test_monitor_stats.py`: sampler unit tests with
  faked `/proc/stat` and GPU sources.

### Notes
- The first 5s send reports a CPU load of 0 (no prior `/proc/stat` delta yet);
  the panel shows real values from the second tick.
- `re_notes/system_monitor_block.md`'s "The GUI does not populate these yet"
  note is now partially outdated — the GUI sends load, but not temperatures or
  weather, which still need their own sources (`hwmon`/`lm-sensors`, and a
  weather API decision).

## [0.9.19] - 2026-08-02

**A controlled real-hardware session on the touchscreen settled the "view"
byte and corrected an earlier packet-loss theory. Byte 1 ("view") is a 1-based
screen index (`GetCurSel() + 1`): view 0 is ignored by the panel (single shots
and fifty streamed sends all changed nothing), while views 1, 2, 3 and 5 all
land identically on the same real-time readout frame and never switch the
panel's screen. A retest with the panel held on that frame showed seven single
shots in a row all landing — so single `--rtc` sends are not lossy. The
earlier "five sends changed nothing" result was a screen-state confound: the
values only appear while the panel is showing the real-time frame, and the
view byte neither summons it nor selects a screen.**

### Added
- `tools/aula_l99_hacky/cli.py`: `--rtc-stream SECS` repeats the RTC session on
  one open transport at ~1 Hz for the given duration, mirroring the vendor
  app, for a live readout that keeps refreshing. A single send already updates
  the panel while it is on the real-time frame.

### Changed
- `tools/aula_l99_hacky/cli.py`: `--view` must now be >= 1; the panel ignores
  view 0 (verified on hardware 2026-08-02), so it is rejected rather than
  silently doing nothing. Help text for `--view`, the `--rtc-stream` help, and
  the module docstring record the confirmed routing behaviour.
- `tools/aula_l99_hacky/protocol.py`: `build_rtc_blocks()` docstring updated
  with the view-0-rejected / view>=1-lands finding; the earlier single-send
  packet-loss claim is removed.
- `tools/aula_l99_hacky/re_notes/system_monitor_block.md`: the "Byte 1 is not
  the constant we assumed" section now records the hardware results; the
  "single send often never reaches the panel" section is replaced by a
  retest section that disproves it (seven/seven single shots landed on the
  fixed real-time frame) and attributes the earlier result to the panel not
  showing that frame; a duplicated paragraph was also removed.

### Notes
- The protocol builder still accepts any 0..255 view byte; the >= 1 constraint
  is a panel behaviour, enforced only at the CLI. Whether the panel owns any
  layout that a view above 5 selects remains untested.

## [0.9.18] - 2026-08-02

**A real-hardware test closed the one open question the system-monitor block
had left: negative temperatures. `--air-temp -1` puts `0xFF` on the wire —
exactly what the vendor app's `_wtoi`-then-low-byte-store produces — and the
panel reads the byte as unsigned, displaying "55" (the low two digits of 255)
instead of -1. The two's-complement encoding was correct; the firmware just
has no way to render a negative, so the CLI now refuses to send one rather
than silently pushing a 250-something wrap onto the panel's readout.**

### Changed
- `tools/aula_l99_hacky/cli.py`: the five temperature flags (`--cpu-temp`,
  `--gpu-temp`, `--air-temp`, `--day-high`, `--night-low`) must now be >= 0; a
  negative value exits with an error explaining that the panel reads the byte
  as unsigned (verified on hardware 2026-08-02: `--air-temp -1` -> `0xFF` ->
  the panel shows "55"). Loads, humidity and condition are unaffected.
- `tools/aula_l99_hacky/re_notes/system_monitor_block.md`: the "Negative
  values" item moved out of "Still untested" into a confirmed finding, with
  the exact panel behaviour recorded.

### Notes
- `protocol.MonitorData` and the builders still accept negative values and
  still encode them two's complement — that behaviour is tested and faithful
  to the vendor app, and `--send-hex` exists for anyone who genuinely wants
  `0xFF` on the wire. The guard sits at the user-facing CLI, not the protocol.

## [0.9.17] - 2026-08-01

**Improved the User Lighting colour-read flow so the overlay no longer depends on a single, sometimes partial read. The helper now short-circuits quickly, validates that it received a full 84-key table, and falls back to the last known full table when the hardware reply is incomplete.**

### Changed
- `tools/aula_l99_gui/workers.py`: `read_colors()` now accepts a fallback table and preserves the last known full table when the latest read is partial.
- `tools/aula_l99_gui/user_lighting_tab.py`: both the "Read Current Colours" action and the single-key apply flow now reuse the fallback table instead of accepting an incomplete result.
- `tools/aula_l99_gui/tests/test_user_lighting_tab.py`: added regression coverage for partial-read fallback behavior.

## [0.9.16] - 2026-08-01

**Daemonised the GUI so it can live in the system tray/app indicator instead
of exiting whenever the window closes. Tray mode now supports Show/Hide/Quit
actions and an optional `--start-hidden` launch path, while the quit action
performs a clean shutdown of background workers before leaving the process.**

### Added
- `tools/aula_l99_gui/main.py`: `--tray` to enable a system tray/app indicator
  icon, `--start-hidden` to launch hidden into tray-only mode, and
  `QApplication.setQuitOnLastWindowClosed(False)` so the process stays alive
  without visible windows.
- `tools/aula_l99_gui/main_window.py`: tray icon with Show/Hide/Quit menu actions,
  close-on-hide behavior when tray mode is enabled, and explicit
  `QCoreApplication.quit()` when quitting from the tray.
- `tools/aula_l99_gui/main_window.py`: tray cleanup that hides the icon before
  exit and ensures background thread shutdown completes cleanly.

## [0.9.15] - 2026-08-01

**The User Lighting tab's Lighting Modes list now animates, and it takes two
different mechanisms to do it because the hardware only offers one: a
whole-keyboard mode is a built-in effect selection *and nothing else* -- the
per-key colour upload that used to ride along with it repainted all 84 keys
the instant the effect started, which is exactly the "it changes colour but
never moves" symptom -- while a single key has no built-in effect to select at
all, so its animation is computed here and streamed over `OP_COLOR_STREAM` at
~17 frames/s. Confirmed animating on hardware both ways.**

### Added
- `aula_l99_gui/stream_effects.py`: the mode table plus six pure animators
  (`breathing`, `colour_cycle`, `rainbow_wave`, `currents`, `revolving`,
  `starlight`) and `build_frame()`, which returns the full 84-key table with
  only the chosen keys animated. `KEY_POSITIONS` normalises the layout XML's
  key rects so the position-dependent effects have geometry to read.
- `workers.ColorStreamWorker`, the animation counterpart to `KeyboardWorker`:
  the transport stays open for the whole run, each frame comes from a
  `frame_fn(elapsed)` callable rather than a list fixed up front, and nothing
  is retried -- a frame that misses its ack is stale 59ms later, so resending
  it would only push the next one back. `STREAM_GAP_SECONDS` (3ms) because a
  frame is 12 packets and `PACKET_GAP_SECONDS` would take twice the frame
  period on its own.
- "Stop Effect" on the User Lighting tab, and `UserLightingTab.shutdown()` for
  the same reason `KeyboardTab` has one: a QThread still running when the
  window tears down aborts the process.
- `theme.SIDE_PANEL_WIDTH` and a `QLabel#SectionTitle` rule, for a section
  heading inside a group box that wants the group-box title's accent without a
  nested frame's margins.
- `compile.sh`: byte-compiles everything under `tools/`. Most of this code only
  runs with a keyboard plugged in, so a typo in a rarely-taken branch would
  otherwise wait for the hardware to be in front of someone.

### Changed
- "Apply to All Keys" honours the armed mode instead of ignoring it, and
  clears this tab's cached colour table when it does -- the firmware owns the
  colours from that point, and claiming otherwise would let "Save Current"
  write a stale table.
- "Apply to Selected Key" keeps its read-modify-write first stage, and stage 2
  now branches: an animated mode starts the stream with the read table as its
  base, a static one still writes it.
- `Lighting` tab: the effect list moved into a full-height column of its own
  (it was under the keyboard image, in a row worth about a third of the
  window, so 21 effects scrolled), at the same fixed width as the User
  Lighting tab's list panes.
- `MainWindow` treats a running animation as a reason to pause colour polling
  but not as "busy" -- it runs for minutes, so raising the loading overlay or
  refusing to close the window over it would both be wrong.
- Global QSS font size 12px -> 14px.

### Fixed
- Selecting a lighting mode had no effect on "Apply to All Keys", which always
  sent `EFFECT_CUSTOM` plus a colour upload.
- `build_selected_key_transactions()` paired an effect selection with a single
  stream frame. One frame is not an animation, and that frame's 84 colours
  landed on top of the effect that had just been selected. Removed rather than
  repaired: nothing about it was salvageable.

### Notes
- The host-side animators are what these names look like *on this side*. They
  are not reproductions of the firmware's own effects -- nothing can read those
  out -- so the same mode on the whole keyboard and on one key will not match
  beyond the name.
- "Starlight" has no effect id that works here, so it is host-animated even for
  a whole-keyboard apply. That is also why it is the one mode where the
  whole-keyboard path streams 84 keys rather than selecting anything.
- Whether the stream overrides a *running* built-in effect is still untested
  (0.9.12 flagged it). The single-key path sidesteps the question: its colour
  read runs first, and `OP_COLOR_QUERY` is already known to knock the keyboard
  out of a running effect.
- Speed and brightness come from the protocol defaults; this tab has no
  sliders for them the way the Lighting tab does.
- The animation's colour and mode are snapshotted when it starts, since the
  frame function runs on the stream thread. Changing either mid-animation does
  nothing until the next apply, which restarts the stream.
- The rewritten `aula_l99_gui/tests/test_user_lighting_tab.py` has not been
  executed -- only the hardware behaviour was checked.

## [0.9.14] - 2026-08-01

**The GUI now ships and uses the vendor's own Open Sans instead of inheriting
whatever sans the platform hands it -- and setting it takes two calls, not one:
Qt stylesheet font properties override `QApplication.setFont`, so a family set
only through `setFont` is silently discarded for every widget the stylesheet
touches, which is all of them.**

### Added
- `theme.FONT_DIR` / `theme.FONT_REGULAR` pointing at
  `tools/aula_l99_gui/font/OpenSans-Regular.ttf`, the vendor TTFs that were
  already sitting in the tree unused.
- `theme.load_font()`, registering the TTF with
  `QFontDatabase.addApplicationFont` and returning the family name read back
  out of the file rather than a hardcoded `"Open Sans"`.

### Changed
- `theme.stylesheet()` takes an optional `font_family` and emits a
  `font-family` line in the global `QWidget` rule only when it is non-empty.
- `main()` loads the font before constructing any widget, then sets both the
  application font and the stylesheet. `QFont(family, -1)` leaves the point
  size unset so sizing stays with the existing QSS `font-size: 12px`.

### Notes
- A missing or rejected TTF returns `""` and the app falls back to the platform
  font with no `font-family` in the stylesheet -- an empty family there would
  be worse than not setting one.
- Only the Regular face is registered, so `font-weight: bold` still renders as
  Qt-synthesised bold. `Light`, `Semibold` and `ExtraBold` sit next to it
  unloaded if the synthetic weight ever looks wrong.
- Verified offscreen: 25 labels in a real `MainWindow` resolve to Open Sans at
  12px, bold still bold, and the missing-file path exits cleanly on Noto Sans.

## [0.9.13] - 2026-08-01

**The panel's spectrum analyser turned out to be another host-side feed on the
channel we already speak: the PC captures its own audio over WASAPI loopback,
runs the FFT itself, and sends the keyboard 23 numbers at ~21 frames/s. All
137 frames in the capture round-trip byte-for-byte. The one packet that looks
like a command is a data block -- the device's own ack behaviour says so --
and reading it the other way is what would send someone hunting for a
block-count field that is really a bass level.**

### Added
- `protocol.OP_AUDIO` (`0x78`) with `build_audio_blocks()`,
  `parse_audio_block()` and `build_audio_frame()`, decoded from
  `wireshark_dumps/save_to_gif_17.pcapng`.
- `AUDIO_BAND_COUNT` (23) and the offset/default constants for the block's
  three header bytes, plus `AUDIO_FRAME_SECONDS` (0.047, the vendor app's
  measured frame period) and `AUDIO_LEVEL_QUANTUM`.
- `--spectrum LEVELS`, with `--spectrum-scale` and `--spectrum-hold`. Levels
  are given explicitly rather than collected from a local audio device, for
  the same reason `--rtc` takes numbers: driving one band at a time is what
  makes the bar-to-band mapping confirmable on hardware.
- `re_notes/audio_spectrum_block.md`: transaction shape, block layout, the
  block-versus-command argument, the WASAPI cross-check, the quantisation
  finding, and what the capture leaves untested.
- Ten new tests, 16 cases with parametrisation. Four pin real captured frames
  byte-for-byte, chosen so the band direction is pinned and not just the
  framing: the opening frame is loud only in the low bands, and a late one is
  silent below band 8.

### Changed
- `_run_sequence()` in the CLI split into itself plus `_run_transactions()`,
  which takes an already-open transport. `--spectrum-hold` must not reopen the
  device between frames -- that would be far slower than the vendor's 21/s and
  would race the GUI's poll thread.

### Notes
- Not confirmed on hardware, unlike the system-monitor fields it sits next to.
  Everything here is one capture plus a cross-check against
  `DeviceDriver.exe`'s imports and GUIDs.
- The block carries no `AA 55` trailer, making it the only outbound block in
  the protocol without one. That is absence, not displacement: bytes 26..63
  are zero in every frame. It is an obvious thing to "fix", so a test guards it.
- Bytes 0..2 are constants only in the sense that one capture at one settings
  state cannot show them varying. Byte 1 (`0x08`) collides with
  `EFFECT_NAMES[0x08] == "spectrum"`, and byte 2 (`0x64`) is equally readable
  as the full-scale denominator or as the Music Rhythm tab's Amplitude slider,
  which is also a 0..100 control that would default to 100. Searching
  `DeviceDriver.exe` for a byte store of those immediates found nothing, which
  weakly favours the settings reading.
- Every level the vendor ever sent is exactly `floor(n * 8 / 5)`, so the feed's
  real resolution is ~63 steps and the 0..100 range is a scaling of it.
- How the stream is enabled is still unknown -- the capture starts mid-stream,
  with a spectrum block already readable back before the first `SET_REPORT`.
  An RTC write interleaves into the loop without disturbing it, so this feed
  and the clock do not need sequencing against each other.
- Nothing is wired to this in the GUI. A real visualiser needs an audio source
  and an FFT on the Linux side; the protocol work only covers where to send
  the result.

## [0.9.12] - 2026-08-01

**A capture of the vendor app animating the keyboard from the host turned up a
second, previously unknown colour-write path -- opcode `0x20`, streamed at ~17
frames/s -- and it does not look like anything else on this channel: no
session framing, a different key order, no terminator block. All 244 full
frames in the capture now round-trip byte-for-byte through the new builders,
but the capture only ever lit one key at a time, so the format is confirmed
and the device's behaviour past one lit key is not.**

### Added
- `protocol.OP_COLOR_STREAM` (`0x20`) with `build_stream_blocks()`,
  `parse_stream_blocks()` and `build_stream_frame()`, decoded from
  `wireshark_dumps/save_to_gif_18.pcapng`.
- `STREAM_KEY_ORDER`, the 84 key ids in the packed order this opcode wants:
  the same set as `KEY_IDS`, sorted into visual reading order. That was
  checked rather than eyeballed -- the capture's order reproduces exactly by
  sorting the vendor layout XML's key rects by `(rect_top, rect_left)`. It is
  hardcoded rather than derived, to keep `aula_l99_hacky` free of the GUI's
  layout XML.
- `STREAM_BLOCK_COUNT`, `STREAM_SLOT_COUNT`, `STREAM_KEY_COUNT` and
  `STREAM_FRAME_SECONDS` (0.0587, the vendor app's measured frame period).
- `re_notes/color_stream.md`: transaction shape, block layout, the key-order
  derivation, the timing figures, and what the capture leaves untested.
- Eight tests anchored on one real captured frame, guarding the three things
  that differ from `OP_COLOR_SET` and would each be a plausible "fix":
  the absent trailer, the packed order, and unlit keys still occupying a slot.

### Fixed
- **`build_color_transfer()`'s docstring claimed `0x23` was the only
  colour-write path seen in any capture.** It no longer is. `0x23` is now
  described as the persistent path, with the stream named as the one to use
  for animation.
- The module docstring presented begin/commit/end framing and the matrix block
  layout as properties of the cable channel. They are properties of individual
  opcodes: `0x20` has neither, and its commit comes *after* its data blocks
  where the `0xF5` poll loop's comes before. Corrected in place, since reading
  that section as a channel-wide rule is what would send someone looking for a
  `begin` that is not there.

### Notes
- Volatility is inferred, not tested. 245 writes in 16 seconds is not
  something flash would survive, which is what makes this the right path for a
  live preview where `OP_COLOR_SET` (which survives a replug) is not -- but
  confirming it needs one experiment: stream a frame, replug, look.
- No `OP_EFFECT` appears anywhere in the capture, so the stream did not need
  `EFFECT_CUSTOM` selected first the way the `0x23` path does. Whether it
  overrides a running built-in effect, or is ignored while one runs, is
  untested and worth checking against the known interaction where colour-query
  polling silently reverts a running effect.
- Within a frame the vendor app left ~2.8ms between data blocks, against the
  ~36.7ms it uses between packets everywhere else. Same app, same machine, so
  that 36.7ms is host-side, not a device requirement. `PACKET_GAP_SECONDS` is
  unchanged; this is a second independent reason to think it is loose.
- Nothing is wired to this yet. Driving it needs a loop rather than a one-shot
  transaction, which is a different shape from every existing CLI flag, and
  the GUI's live preview is still on the polling path.
- The capture also carried four `0x28` writes with non-zero monitor data,
  which decode cleanly against the offsets 0.9.11 established -- an
  independent second confirmation of that block, from a capture taken for an
  unrelated reason.

## [0.9.11] - 2026-08-01

**A new capture located the touchscreen's CPU/GPU and weather readout, and it
was never a touchscreen protocol at all: it rides in nine bytes of the
keyboard's own clock packet, which we had been sending zeroed the whole time.
`aula_l99_hacky` can now set them, and every field is confirmed on
hardware -- but the same find contradicted the dongle packet already in the
file, and that conflict is unresolvable without a dongle to test.**

### Added
- `--rtc` gained the system-monitor fields the panel displays: `--cpu-load`,
  `--cpu-temp`, `--gpu-load`, `--gpu-temp`, `--air-temp`, `--day-high`,
  `--night-low`, `--condition`, `--humidity`, plus `--view`. Anything omitted
  is sent as zero, which is exactly what the vendor app sends when it has
  nothing to report, so a bare `--rtc` is still a plain clock write.
- `protocol.MonitorData`, a frozen nine-field value type validating on
  construction, and `parse_condition()` accepting either a name
  (`cloudy`/`clear`/`light-snow`/`thunder`/`rain`/`heavy-snow`) or a number.
  `--list-conditions` prints the table, mirroring `--list-effects`.
- Named offset constants for the whole `0x28` block, replacing the bare
  indices both RTC builders were written with.
- `re_notes/system_monitor_block.md`: the full decode -- transaction shape,
  field table, where the vendor app sources each value
  (`OpenHardwareMonitorServer.exe` via `data.ini` for hardware, a weather API
  for the rest), and the condition-code mapping.
- First tests for this package, `tools/aula_l99_hacky/tests/`, following the
  `conftest.py` path-insert pattern `aula_l99_screen/tests/` already uses. The
  one that carries the weight reproduces the captured block byte-for-byte from
  the nine values, pinning every offset to the vendor app's real output rather
  than to a reading of its disassembly.

### Fixed
- **`settings_write.md` had concluded the monitor feed was a separate,
  uncaptured protocol on the panel's CDC-ACM port.** Wrong, and wrong in an
  instructive way: the panel *is* a separate USB device, but that says nothing
  about which device the host sends the data to. The keyboard receives it on
  the channel we already speak and forwards it. The old section is marked
  superseded rather than deleted, with the bad inference named.
- Byte 1 of the RTC block was hardcoded `0x01` as a constant. The vendor app
  computes it as the selected screen view's index plus one -- 1 only because
  the first view was selected in every capture. Now the `view` parameter.

### Changed
- `build_rtc_blocks()`, `build_rtc_transfer()` and `build_dongle_rtc_packet()`
  take an optional `MonitorData` and `view`, defaulting to the all-zero,
  view-1 block. Verified byte-identical to the previous output, so the GUI's
  "Set Clock to Now" is untouched -- it still writes a clock and nothing else.
- `build_dongle_rtc_packet()` now switches layout depending on whether monitor
  data was supplied, which is damage control rather than design. The vendor's
  own dongle code path places these fields at +4 from the cable offsets, but
  the F75 MAX prior art this packet was built from implies +3, and its `AA 55`
  trailer sits exactly where the +4 reading puts the first monitor byte. No
  splice of the two is a packet either source supports, so a clock-only write
  keeps the prior-art bytes untouched and a monitor write uses the vendor
  layout. The `+4` reading is the better bet -- it is this device's own code,
  not another keyboard's -- but no L99 dongle has ever been tested.

### Notes
- The nine field assignments started as inference from a single capture
  cross-checked against `DeviceDriver.exe`, then were confirmed by writing a
  distinctive value to each and reading the panel. Explicit CLI values rather
  than live `psutil`/`hwmon` readings is what made that check possible, and is
  why the tool takes numbers instead of collecting them.
- Still unconfirmed: what a `--view` above 1 does, and whether the panel reads
  a negative temperature as signed (`--air-temp -5` sends `0xFB` because that
  is what the vendor app would send, not because the result was observed).
- The GUI does not populate these fields yet. Doing so needs a stats source
  and, given that colour-query polling already disturbs running effects, a
  monitor write sequenced behind the poll thread the way 0.9.8's
  `_pending_write` queue handles RTC writes.

## [0.9.10] - 2026-08-01

**"Set Clock to Now" and the colour-poll interval moved to the Config tab,
leaving the Keyboard tab as purely the live per-key colour view -- the
controls moved, but the work behind them deliberately stayed put, because
the tab they left is the one that owns the poll thread an RTC write has to
be sequenced behind.**

### Changed
- Config tab now hosts a "Keyboard Clock" group ("Set Clock to Now" plus the
  progress bar for it) and the "Colour Polling" interval, above the existing
  debug log -- both are settings rather than content, which is what the tab
  is for. It takes the keyboard's `DeviceSelector` for the first time, to
  gate the button on a keyboard actually being present.
- Keyboard tab is now just the overlay: its RTC and poll group boxes,
  progress bar, and the `_action_buttons`/`_sync_actions` pair that had
  nothing left to enable are gone.
- The RTC write and the poll timer still live in `KeyboardTab`, reached via
  new `set_clock_now()`/`set_poll_interval()`. Running the write from the
  Config tab instead would have meant a second, unsequenced opener of the
  same hidraw handle alongside the poll thread -- exactly the race 0.9.8's
  `_pending_write` queue fixed. Config is pure UI: it forwards
  `set_clock_requested`/`poll_interval_changed` and renders progress from a
  new `KeyboardTab.write_progress(value, maximum)` signal, since the write
  it starts belongs to another tab and so never shows up in its own
  `is_busy`. Its button gates on MainWindow's existing all-tabs busy
  aggregate for the same reason.

## [0.9.9] - 2026-08-01

**User Lighting tab gained a saved-lighting file library, reading and
writing the vendor's own `customlight` XML format -- and the half-finished
version of it that was sitting in the working tree turned out to be keyed on
the wrong number entirely: the vendor's files identify keys by HID usage
code, not by the `light_index`/`key_id` the protocol speaks.**

### Added
- User Lighting tab: a "Saved Lighting" panel down the left side, listing
  `*.xml` under `<AppDataLocation>/User_Lighting` (same
  `QStandardPaths`-based convention the Touchscreen tab's
  `Customized_Animation` library already uses). Selecting a file *only*
  loads it -- it paints the overlay with the file's colours and arms "Apply
  to Keyboard", but writes nothing, so browsing the list can't disturb what
  the keyboard is currently showing. "Save Current" prompts for a name
  (defaulting to the next free `UserLightingN`) and confirms before
  overwriting.
- `_load_lighting_xml()` / `_save_lighting_xml()`: the vendor
  `customlight` format, round-tripped against the shipped
  `Windows/UserLighting1.xml.xml` sample. Files we write open in the vendor
  app; files it writes load here.
- `key_layout.py` gained `HID_BY_KEY_ID`/`KEY_ID_BY_HID`, parsed from the
  same layout XML's `code` attribute, plus an import-time assert that the
  mapping is still one-to-one.
- What "Save Current" saves is the last full 84-key table this tab knows
  about, from whichever of an apply, a "Read Current Colours" or a loaded
  file happened most recently -- new `_key_colors` state, kept in step by
  all three paths. With none of them having happened yet, the only colour
  the tab can honestly claim is the one in the picker, so it saves that
  uniformly.

### Fixed
- **Saved-lighting files were being keyed on the wrong number**: the
  work-in-progress code read and wrote `keycode` as though it were
  `protocol.KEY_IDS`. It isn't -- the vendor file's `keycode="58"` is the
  HID usage code (0x3A, F1), while the protocol's key id for that key comes
  from the layout XML's `light_index`. Confirmed one-to-one across all 84
  keys, in both directions, against the vendor sample file. Left as-was,
  every load and save would have silently scrambled the key mapping.
- `AttributeError: 'UserLightingTab' object has no attribute
  '_on_save_current'` on startup -- a button wired to a handler that was
  never written, which took the whole GUI down before the main window
  appeared.
- `_refresh_file_list` was defined twice (the second shadowing the first),
  `QStandardPaths` was used without being imported, and
  `defusedxml.ElementTree` was used to *build* XML -- it only re-exports the
  parsing half of `ElementTree`, so `ET.Element`/`SubElement`/`ElementTree`
  don't exist on it. Parsing (the half with an attack surface) stays on
  `defusedxml`; building uses the stdlib module.

### Changed
- The `EFFECT_CUSTOM`-then-colour-transfer pair that every per-key write
  needs is now one `_build_custom_transactions()` helper, rather than being
  spelled out at each call site.

## [0.9.8] - 2026-07-31

**GUI: the keyboard layout image gained real uses across three tabs -- a
static preview on the Device tab, a live per-key colour-polling overlay on
the Keyboard tab, and a clickable per-key colour picker plus read-back
diagnostic on User Lighting -- and two real bugs turned up along the way: a
write/poll device-access race, and a `QThread`-still-running crash on exit.**

### Added
- `key_layout.py`: parses the vendor's `assets/layouts/rgb-keyboard.xml`
  once at import into `KEY_RECTS: dict[key_id, KeyRect]` (pixel rect + name
  per physical key, against the 800x300 base image). Confirmed by direct
  comparison, not assumed: the XML's `light_index` is byte-identical to
  `protocol.KEY_IDS`, just decimal vs hex -- asserted at import as a
  regression guard.
- `keyboard_overlay.py`'s `KeyboardOverlay`: a clickable per-key overlay
  widget on the layout image. Swatches paint *behind* the pixmap, not on top
  of it -- the per-key art has transparent cutouts, so a colour behind it
  reads as that key lighting up rather than a rectangle stamped over the
  artwork. A selected key gets an outline; clicking an already-selected key
  deselects it (toggle, no separate "clear" control needed).
- `workers.py`'s `read_colors()`: the GUI-side read path for per-key colour
  -- mirrors `aula_l99_hacky/cli.py`'s `cmd_read_color` (query commands +
  `COLOR_BLOCK_COUNT` raw feature-report reads + `parse_color_blocks`) minus
  its printing/retry loop, meant to run inside a `CallableResultWorker` off
  the GUI thread.
- Device tab: the keyboard layout image moved to the top of the tab, above
  a stretch that pushes the Keyboard/Touchscreen selectors and the
  Connection group down to the very bottom.
- Keyboard tab: the same layout image, now a live `KeyboardOverlay` polling
  `read_colors()` on a `QTimer` -- default 100ms, adjustable via a "Colour
  Polling" group's `QSpinBox` (1-5000ms, wired straight to
  `QTimer.setInterval` so it retunes live). Hidden until a keyboard's
  detected; RTC "Set Clock to Now" and the progress bar moved below it.
- User Lighting tab: the same overlay (no group-box title -- plain, matching
  the other two tabs), driving two new actions alongside the existing
  "Apply to All Keys": "Apply to Selected Key" (click a key on the overlay,
  pick a colour, Apply -- read-modify-write via two chained workers, since
  `build_color_transfer` replaces the *entire* 84-key table and would blank
  every unmentioned key) and "Read Current Colours" (paints the overlay with
  each key's actual on-device colour, purely diagnostic, never polled --
  button-triggered only). Aborts with an error rather than writing if a
  readback comes back incomplete; disabled while Colorful is checked; any
  write auto-clears stale readback swatches.
- `theme.py` gained `KEYBOARD_LAYOUT_IMAGE`/`LAYOUT_XML` path constants,
  consolidating what `device_tab.py` had defined locally.

### Fixed
- **Device-access race between colour polling and writes**: a colour-poll
  read's full cycle (2 query transactions + 9 block reads, each gapped
  10ms) runs ~130-160ms -- longer than the 100ms default poll interval, so
  a background poll was very often still holding the keyboard's hidraw
  handle open when a write (Set Clock, Run Effect) was clicked.
  `_run_transactions` didn't check for this at all, so writes were racing
  an in-flight read for the same device and losing. Fixed by queuing the
  write behind any in-flight poll (`_pending_write`) instead of racing it,
  flushed by `_on_poll_thread_stopped` the moment the read actually
  finishes.
- **Colour polling silently broke built-in effects on real hardware**:
  confirmed on hardware that a Run Effect write on the Lighting tab acked
  every transaction cleanly (`begin`/`effect`/`commit`/`end` all "ok") yet
  the keyboard's lighting didn't actually change, whenever background
  colour-polling was also running on that tab -- not a timing race (a
  500ms post-write cooldown before resuming polling didn't fix it either),
  but `OP_COLOR_QUERY` itself appears to revert the keyboard out of a
  just-applied built-in effect even when strictly sequenced after the
  write, never overlapping it. Colour polling removed entirely from the
  Lighting tab (reverted to a static overlay image, matching Device tab) --
  it only ever belonged on Keyboard tab (which never writes lighting data)
  and User Lighting tab (which only ever writes *custom* per-key colours,
  never a built-in effect).
- **`QThread: Destroyed while thread '' is still running` crash on exit**:
  `MainWindow.closeEvent()` already refused to close while any tab was
  mid-*write*, but never accounted for the Keyboard tab's background poll
  thread, which can easily still be mid-read at the moment the window
  closes. New `KeyboardTab.shutdown()` stops the poll timer and, if a read
  is in flight, blocks (`QThread.quit()` + `.wait()`) until it actually
  finishes before `closeEvent` accepts the close -- verified headlessly
  that this waits out a genuinely in-flight thread rather than a fixed
  guess, and doesn't deadlock doing it.

### Changed
- Colour polling now pauses whenever *any* tab is busy, not just its own --
  new `KeyboardTab.set_external_busy()`, driven from `MainWindow`'s existing
  all-tabs busy aggregate (previously only used to drive the loading
  spinner). Another tab's transaction can be holding the same hidraw handle
  open even though this tab itself is idle.

### Known gaps
- Live physical-keypress highlighting (light up a key's overlay rect when
  it's actually pressed) was considered and deliberately descoped: it needs
  reading the keyboard's standard HID input-report interface, which is a
  different, not-yet-identified interface from the vendor control interface
  everything else here targets, and finding it needs hardware probing this
  round didn't do.

## [0.9.6] - 2026-07-31

**Touchscreen upload's fixed 5ms inter-packet delay made tunable from the
GUI, then its default dropped to 0ms after the user confirmed a transfer at
0ms works reliably on real hardware -- the delay was a defensive default,
not a firmware requirement. Separately, `aula_l99_hacky` gained a
`--read-color` command, reading each key's actual current colour back off
the keyboard -- the read opcode existed as a named constant but had never
been implemented.**

### Added
- "Packet gap (ms)" `QDoubleSpinBox` in the Touchscreen tab's "Send to
  Device" group (`touchscreen_tab.py`, range 0.0-50.0, 0.5 step), read in
  `_start_upload` and passed straight through to `ScreenUploadWorker`'s
  existing `gap` parameter (`workers.py`), which already looped
  `time.sleep(self._gap)` after every packet but had no GUI control -- the
  value was hardcoded at the call site.
- `aula_l99_hacky`'s `--read-color` (`cli.py`'s `cmd_read_color`), reading
  every physical key's current colour back off the keyboard. `OP_COLOR_QUERY`
  (`0xF5`) had been in `protocol.py` since early on as a named opcode with a
  comment noting reading was never implemented; the missing piece was the
  wire sequence, which isn't the begin/commit/end session the write path
  uses. Recovered it by decoding `tmp/l99dump1.pcapng` (a previously-unparsed
  raw USBPcap capture) byte-for-byte: the vendor app's steady-state poll is
  just `commit -> query -> 9 raw data blocks in`, repeated, with an unrelated
  begin/effect/commit/end session elsewhere in the same capture running
  independently without interrupting it. `protocol.py` gained
  `build_color_query_commands()` and `parse_color_blocks()` (the inverse of
  `build_color_blocks()`, minus the write path's terminator block -- a query
  reply's ninth block is just an ordinary, always-empty row rather than an
  `AA 55` sentinel). Confirmed end-to-end against real hardware: all 84 keys
  read back correctly.

### Changed
- `DEFAULT_PACKET_GAP_MS` (`touchscreen_tab.py`) and the CLI's `--gap`
  default (`aula_l99_screen/cli.py`) both lowered from their prior
  0.005s/5ms default to `0.0`. Investigated after the user asked whether
  the transfer could be sped up: neither `protocol.py`'s reverse-engineering
  notes nor any code comment tied the delay to an actual firmware
  requirement -- the real per-packet cost is the sequential
  write-then-block-on-ack loop in `SerialTransport`
  (`aula_l99_screen/device.py`), not this sleep. Confirmed on real hardware
  at 0ms before lowering the default; the spinbox remains available to dial
  back up if a future transfer on different hardware turns out to need it.

## [0.9.5] - 2026-07-31

**GUI: Touchscreen tab's "Animation Settings" delay/dither controls
combined onto one row, a preview panel added below the Source Images list,
and `.mp4` sources now get a real extracted-frame thumbnail instead of a
flat grey tile.**

### Added
- A preview panel (`self.source_preview`, reusing the existing but
  previously-orphaned `QLabel#ImagePreview` styling from the removed
  single-image upload section) below the "Source Images" strip, showing a
  larger thumbnail of whichever source item is currently selected --
  `source_strip.currentItemChanged` drives `_on_source_image_selected`,
  which reuses `_load_source_thumbnail` at a bigger `PREVIEW_ICON_SIZE`
  (200x300, matching the panel's 2:3 aspect) instead of duplicating the
  loading logic. Falls back to "(no image selected)" placeholder text with
  no selection.
- `_video_thumbnail_frame`: shells out to `ffmpeg -vframes 1 -f image2pipe
  -vcodec png -` to grab an `.mp4`'s first frame as a real thumbnail, for
  both the Source Images strip and the new preview panel -- previously any
  `.mp4` just showed the generic grey placeholder tile, indistinguishable
  from a missing/corrupt file. Best-effort only (returns `None` on any
  failure -- no ffmpeg, decode error) so a bad video can't crash the UI;
  falls back to the grey tile same as before when extraction fails.

### Changed
- "Delay (centiseconds)" and "Dither" moved onto one shared row in the
  Animation Settings group instead of two stacked rows.

## [0.9.4] - 2026-07-31

**New `run.sh` at the repo root, launching the GUI without needing to
remember its `tools/`-relative module invocation.**

### Added
- `run.sh`: resolves `tools/` relative to the script's own location (so it
  works regardless of the caller's cwd, unlike the bare
  `python3 -m aula_l99_gui.main` documented in `aula_l99_gui/README.md`,
  which fails with `ModuleNotFoundError` unless run from `tools/` first).
  Prefers `uv run --project aula_l99_gui` when `uv` is installed (the
  README's recommended path -- handles the venv/deps automatically), falls
  back to a manually-created `tools/.venv/bin/python3` if present, and
  falls back again to plain `python3` otherwise. `exec`s the final command
  so no wrapper shell process lingers, and forwards any args through.

## [0.9.3] - 2026-07-31

**GUI: Touchscreen tab's GIF/animation workflow rebuilt around a persistent
`Customized_Animation` library (browse/create/edit/delete saved animations,
unified across single-image and multi-frame sends), and every tab's
separate debug log consolidated into a new Config tab.**

### Added
- Touchscreen tab: every GIF upload now saves a local, human-viewable copy
  under the OS app-data directory (`QStandardPaths.AppDataLocation`) in a
  `Customized_Animation` folder -- a re-encoded `.gif` (via Pillow, not the
  proprietary device blob) plus a sibling `.csv` recording the output
  filename and each source input file (full path) with its delay, serial-
  numbered by scanning the directory for the highest existing stem + 1.
- "Saved Animations" column (left of the tab, widened to 320px) lists every
  saved csv as a thumbnail, built by reading each csv's first line rather
  than scanning for `.gif` files directly. "New" reserves the next serial
  number as an empty placeholder (shown as a grey tile) and selects it;
  "Delete" removes both the csv and whichever companion file exists
  (`.gif` or `.png`), after confirmation.
- "Source Images": a universal, multi-select "Choose Image…" picker
  (png/jpg/jpeg/gif/mp4) replacing the old three-radio-button GIF source
  section (Multiple image files / Animated GIF file / Video (MP4)) --
  clicking it repeatedly appends to one ordered list, shown as a horizontal
  thumbnail strip (right-click an item to remove it). Selecting a saved
  animation loads its recorded sources into this same live, editable list,
  so browsing history doubles as loading a starting point to keep editing.
- "Send to Device" button group: Background/Photo Frame (enabled only for
  exactly one png/jpeg in the source list) and Customized Animation
  (enabled for one or more source images of any type, sequentially
  processed per file type -- still image, every frame of a `.gif`, or
  ffmpeg-sampled frames of an `.mp4`). All three save a local csv/output
  copy same as before; if a Saved Animations entry is currently selected,
  the save updates that entry in place instead of always creating a new
  numbered one.
- New `Config` tab (`tab_config.png`, sliced via `slice_skin.py`) appended
  last in the rail, holding one consolidated "Debug Log". New
  `debug_log.py`'s `DebugLog` is a shared `QObject` (`message`/`cleared`
  signals) passed into Keyboard/Lighting/User Lighting/Touchscreen at
  construction; each tab's status/progress lines are tagged with their
  source tab (e.g. `"[Keyboard] Key 3: ok"`) since all four now interleave
  in one widget.

### Changed
- `main.py` now sets `QCoreApplication.setOrganizationName`/
  `setApplicationName("AULA_L99")` -- required for
  `QStandardPaths.AppDataLocation` to resolve to a stable path instead of
  falling back to the interpreter's own name.

### Removed
- The standalone "Upload Image" section (its own target dropdown, its own
  image picker, its own "Upload" button, `self._image_path`) -- superseded
  by "Send to Device", which reads from the same shared source list as
  animation uploads instead of keeping a separate one.
- Each of Keyboard/Lighting/User Lighting/Touchscreen's own isolated
  `self.log` widget -- moved into the Config tab (see Added).

### Fixed
- Removing each tab's debug log left `QVBoxLayout` with no trailing
  stretch, stranding the fixed-height progress bar at the very bottom of
  the tab with a large empty gap above it -- its idle grey groove (no
  orange fill, no label) read as a stray decorative line rather than a
  progress bar. Added `addStretch(1)` after the progress bar in all four
  affected tabs so it sits directly below the last control group again.

## [0.9.2] - 2026-07-31

**GUI: GIF conversion (frame decode + dithering) moved off the GUI thread,
a loading spinner now shows whenever any tab is busy, and GIF upload
gained an MP4 video source.**

### Added
- `workers.py`'s `CallableResultWorker`: runs an arbitrary no-arg callable
  on a background thread and reports its return value or exception message
  back via `finished`. GIF upload's frame decode/resize and
  `protocol.py`'s dithering + CRC computation were being done inline in the
  button's click handler -- profiled at ~3s for just a 10-frame dithered
  GIF (see 0.8.6/0.8.5), long enough to freeze the window. `touchscreen_tab.py`
  now runs that whole pipeline (`_build_gif_packets`) through this worker,
  with its own `_convert_worker`/`_convert_thread` pair separate from the
  upload phase's; `_collect_gif_frame_pixels`/`_ensure_safe_colors` raise
  instead of calling `QMessageBox` directly, since Qt widgets aren't
  thread-safe and this now runs off the GUI thread.
- A `busy_changed` signal and `_set_busy()` helper on all five tabs (Device,
  Keyboard, Lighting, User Lighting, Touchscreen), replacing every direct
  `self._busy = ...` assignment. `MainWindow` connects all five to one
  handler that shows a `loading.gif` spinner (via `QMovie`), floated
  centred over the whole window -- not part of any layout, parented
  straight to `MainWindow` and re-raised after `setCentralWidget` so it
  can't end up buried under the tab content -- whenever any tab reports
  busy.
- GIF upload gained a "Video (MP4)" source alongside folder/files/animated
  GIF. `_extract_video_frames` shells out to a system `ffmpeg` (no new pip
  dependency for this -- PyAV/opencv-python were both heavier than felt
  justified) and samples at `fps = 100/delay`, so the extracted frame
  count follows the same "Delay (centiseconds)" spinbox every other source
  already uses rather than pulling in every frame of a 24-60fps source.
  Raw `rgb24` output is reshaped via byte-strided slicing + `zip` (a
  C-level reshape, not a per-pixel Python loop).

### Fixed
- The loading spinner itself could stall/stutter during GIF conversion even
  though that work already ran on a background `QThread`. Root cause: a
  tight pure-Python per-pixel loop with no natural GIL-release point
  (`dither_frame_floyd_steinberg`, 320x480 pixels/frame) can still starve
  the main thread of enough GIL time to service `QMovie`'s frame-advance
  timer smoothly -- CPython's GIL serializes actual bytecode execution
  between threads regardless of which OS thread a QThread runs on. Added a
  `time.sleep(0)` yield once per row (not per pixel -- that would
  meaningfully slow the algorithm down) in `aula_l99_screen/protocol.py`;
  a no-op for single-threaded CLI use, but gives the main thread frequent,
  reliable chances to reacquire the GIL during GUI conversion.

### Changed
- "Dither" now defaults to checked, and its label dropped the "(confirmed
  working on real hardware)" qualifier -- confirmed enough at this point
  (see 0.8.6 onward) not to need repeating on every use.

## [0.9.1] - 2026-07-30

**GUI: Lighting split into Lighting (built-in effects) and a new User
Lighting tab (per-key color), the effect picker became a full-height list
instead of a dropdown, and the Device tab now polls on its own instead of
waiting for a manual Refresh.**

### Added
- New `User Lighting` tab (`user_lighting_tab.py`/`UserLightingTab`, using
  `tab_userlight.png`), holding the color wheel/RGB/preset-swatch picker and
  "Apply to All Keys" -- pulled out of the Lighting tab so picking a static
  per-key color and picking/running a built-in effect aren't bundled under
  one icon. Entirely self-contained: its Colorful checkbox and color state
  affect only its own Apply action. The Lighting tab keeps its own separate
  copy of the same picker (wheel/RGB/presets/Colorful) for whatever color
  Run Effect sends -- the two were briefly wired together via a shared
  color source and a cross-tab signal, but that made "the controls on one
  tab affect the other" the norm rather than the exception, so each tab
  went back to owning its own state independently.
- `color_wheel.py`'s `ColorWheel`: click/drag color picker rendered from the
  vendor's `img_circlepalette.png`. Picks by sampling the actual pixel under
  the cursor rather than computing RGB from the clicked angle -- checked
  empirically that the art's hue isn't evenly spread by angle (red-to-yellow
  sweeps ~120 degrees, yellow-to-green only ~30), so a formula would drift
  visibly out of sync with what's drawn.
- "Apply to All Keys" now selects `EFFECT_CUSTOM` (0x80) before the per-key
  colour upload, matching `protocol.py`'s own note that the vendor app
  always pairs custom mode with a colour write (otherwise the keyboard can
  still be mid-built-in-effect and ignore it) -- unless Colorful is
  checked, in which case Apply just selects the confirmed 0x06 "colourful"
  effect instead, since that effect ignores a custom color anyway.
- Device tab polls its own selectors every 5 seconds (`DeviceTab`'s
  `POLL_INTERVAL_MS` timer in `device_tab.py`) so a plug/unplug shows up
  without hitting Refresh, plus an immediate refresh the moment the tab
  becomes current -- so switching to it doesn't wait out the rest of a tick.

### Changed
- Lighting tab's effect picker is a `QListWidget` (one row per effect, sized
  by `sizeHintForRow` to fit every row with no scrollbar) instead of a
  `QComboBox`, laid out on the left with Brightness/Speed/Color/Run Effect
  on the right. Rows show just the effect name -- the `0x..` id and
  confirmed/untested tag were dropped as clutter once the id/tag no longer
  had to fit inside one dropdown line. Double-clicking a row runs it
  immediately (`itemDoubleClicked` wired to the same handler as Run Effect).
- Speed/Brightness are labeled sliders (value shown below each) instead of
  spin boxes, reusing the vendor's slider groove/chunk art plus a newly
  sliced `img_thumb.png` handle (4 states via `slice_skin.py`).
- The "Effect"/"Color"/"Clock" group-box titles were removed -- each was the
  only section in its tab, so the title just repeated context the tab icon
  already gave. "Connection" (Device tab) and "Upload Image"/"Upload GIF"
  (Touchscreen tab) keep their titles since those tabs hold multiple
  sections that still need distinguishing.
- `QListWidget` lost its border and background (now transparent), matching
  the group-box/tab-rail treatment from 0.9.0.
- The per-tab "Using /dev/hidrawN (cable)"-style status line -- mirrored
  from the Device tab's selectors into every control tab -- is gone.
  Replaced by a tooltip on the title bar's USB-mode icon, combining both
  the keyboard and touchscreen status strings, since one shared icon now
  speaks for both devices instead of four duplicate labels.

## [0.9.0] - 2026-07-30

**GUI: split into a four-tab layout (Device, Keyboard, Lighting,
Touchscreen) behind a custom frameless title bar skinned to match the
vendor app, and stripped out the leftover default-Qt chrome (borders,
card backgrounds) the vendor skin never called for.**

### Added
- New `Keyboard` tab (`keyboard_tab.py`/`KeyboardTab`), holding just the RTC
  "Set Clock to Now" action -- split out of the old `keyboard_tab.py` (now
  `lighting_tab.py`) so color/effect and the clock aren't bundled under one
  icon. Rail order is now Device, Keyboard, Lighting, Touchscreen.
- Device tab: a `Connection` group with "Test Connection" (the handshake
  action, moved here from the keyboard tab since it's a property of the
  connection itself, not a lighting/RTC action) and an
  `img_keyboard_layout.png` preview that appears once a cable keyboard is
  detected.
- `TitleBar` in `main_window.py`: a frameless custom title bar (vendor
  logo, current-tab "`<Tab> Mode`" label, centred "AULA L99" wordmark,
  minimize/close) standing in for the OS one, since Qt can't skin native
  window chrome. Dragged via `QWindow.startSystemMove()` rather than
  hand-rolled `move()`-on-drag -- the latter is a silent no-op under
  Wayland, which (unlike X11) doesn't let a client reposition its own
  top-level window.
- USB-mode icon (`usb_mode.png`) in the title bar, left of minimize, shown
  whenever a known AULA L99 VID:PID is seen on either the keyboard or
  touchscreen selector -- including the dongle, which is recognized but
  unsupported for actions. Threaded through as a third `found` bool on
  `DeviceSelector.changed`, alongside the existing status/enabled pair.
- `main_sysbtn_close.png`/`main_sysbtn_min.png` sliced into the usual
  4-state (`normal`/`hover`/`pressed`/`disabled`) strips via
  `slice_skin.py`, plus the `tab_light` (Lighting) and re-added
  `tab_customkey` (Keyboard) tab-rail icons.

### Changed
- `keyboard_tab.py` (color/effect controls) renamed to `lighting_tab.py`/
  `LightingTab`, and `screen_tab.py`/`ScreenTab` renamed to
  `touchscreen_tab.py`/`TouchscreenTab` -- file, class, and `MainWindow`
  attribute names now all match the tab they back rather than the
  pre-split names.
- Tab-rail icons are drawn centred by hand in `SidebarTabBar.paintEvent`
  rather than via `CE_TabBarTabLabel`, which never centred them (it lays
  icon+text out left-aligned, plus a west-facing rotation).
- Group boxes and the tab-rail buttons lost their border and background
  (previously a translucent dark card / `rgba` fill) -- both fully
  transparent now, so the starfield shows straight through instead of a
  boxy vendor-Qt look.
- Window is frameless and fixed-size (1200x800) instead of resizable --
  a frameless window has no native resize grips, and hand-rolling
  edge-drag resize wasn't worth it for a tool with no real reason to be
  resized; matches the vendor app's own non-resizable window.

## [0.8.11] - 2026-07-30

**GUI: the tab bar moved from across the top to an icon-only rail down the
left-hand side.** Three 40x40 buttons carrying the vendor tab artwork and
nothing else, with the current one picked out in orange.

### Added
- `SidebarTabBar` in `main_window.py`: a `QTabBar` for a `West`-positioned
  `QTabWidget` that keeps its contents upright. Qt rotates a west tab's
  label 90 degrees along with its shape, which stands the vendor icons on
  their side, so the shape is drawn west-facing but the label is drawn as
  if the tab faced north.
- `theme.SIDEBAR_TAB_SIZE`, the rail button size, derived as twice
  `TAB_ICON_SIZE` rather than hardcoded so the proportion survives a
  change to the icon size.

### Changed
- The tab buttons are icon-only. With no text on them the tab titles moved
  out of `tabText()` into `MainWindow._tab_titles`, which is both the key
  for the per-tab icon lookup and the source of each button's tooltip --
  the only thing naming an unlabelled button for the user.
- The current tab is marked with an orange left edge instead of 0.8.9's
  bottom underline, which reads wrong on a vertical rail.
- Button geometry is applied in `tabSizeHint`, not as a stylesheet
  `min-width`/`padding`. Qt evaluates those in a West tab bar's rotated
  frame, where a "width" becomes the button's vertical extent -- doing it
  in the stylesheet gave 155px-tall rows with the icons hanging off the
  left edge.

## [0.8.9] - 2026-07-30

**GUI: skinned with the vendor's own artwork, extracted from the Windows
package.** `main_bkg.png` behind the window plus a stylesheet driven by
the vendor's button/checkbox/radio/combo/scrollbar sprite art, so the tool
looks like the thing it replaces instead of stock Qt.

### Added
- `tools/aula_l99_gui/assets/`: the vendor's `skins/theme1` tree (plus
  `device/`, `gif/`) lifted out of `Windows/AULA L99`.
- `tools/aula_l99_gui/theme.py`: the Qt stylesheet and the background
  painter. `background_pixmap()` cover-scales `main_bkg.png` with
  `KeepAspectRatioByExpanding` and anchors it to the bottom -- the image
  is 16:9 and the window is not, and the blue grid in the lower third is
  the only part with any detail, so anchoring low keeps it on screen.
  Verified to return an exactly window-sized pixmap from 1x1 up to
  2560x1440, and a null pixmap if the image is missing.
- `tools/aula_l99_gui/slice_skin.py`: splits the vendor sprite sheets into
  the per-state PNGs under `assets/skins/theme1/slices/` (45 of them, all
  committed). Qt stylesheets can only reference a whole file, never a
  sub-rectangle, so each state the QSS names has to exist on its own. The
  script clears the output directory first, so swapping or dropping a
  sheet can't leave orphaned slices nothing references behind.
- Tab icons on the (still top-mounted) tab bar, from the vendor's own
  `tab_home`/`tab_customkey`/`tab_tft` strips, swapped between the plain
  and orange frames on tab change -- QIcon has no "selected tab" state Qt
  applies by itself. The current tab is marked with an orange underline.

### Changed
- Frame order in the sprite sheets was determined empirically rather than
  guessed: every 4-frame strip is `[normal, hover, pressed, disabled]`
  with hover `#EF6C00` and pressed `#CF4D00`; the 8-frame check/radio
  strips interleave an unchecked and a checked set, with frames 4 and 6
  duplicating the art of 2 and 1 (documented in `slice_skin.py`'s
  `CHECK_FRAMES`).
- Buttons and combo boxes use `border-image` with fixed side slices, so
  the rounded pill caps and the combo's built-in drop-down arrow stay
  undistorted while the middle stretches to the layout's width.
- Group boxes are translucent cards so the starfield reads through them,
  but the log, frame list, spin boxes and image preview are fully opaque
  -- the background image is brightest exactly where those sit, and any
  translucency there cost real legibility.
- `screen_tab.py`'s image preview is a styled `QLabel#ImagePreview` panel
  instead of a bare `QFrame.Shape.Box`.

## [0.8.8] - 2026-07-30

**GUI: device selection moved out of the two control tabs and into a
`Device` tab of its own.** Both tabs carried a near-identical `Device`
group box -- combo, Refresh button, status line -- backed by duplicated
`refresh_devices`/`_current_device_path`/`_set_actions_enabled` methods
that differed only in which enumerate/describe/find functions they called.
That's now one shared widget, and all device concerns live in one place.

### Changed
- New `tools/aula_l99_gui/device_tab.py`: a `DeviceSelector` group box
  (combo + Refresh + status line) parameterised by list/describe/resolve
  callables, and a `DeviceTab` hosting one for the keyboard and one for
  the touchscreen. The per-device auto-detect logic lifted out of both
  tabs lives in `_resolve_keyboard`/`_resolve_screen`, including the
  `find_l99()`/`find_screen()` not-found paths and the dongle check
  (`DONGLE_UNSUPPORTED_MESSAGE` moved here from `keyboard_tab.py`).
  `device_utils.py` is reused unchanged for enumeration and formatting.
- `keyboard_tab.py`/`screen_tab.py` take their `DeviceSelector` by
  constructor injection and learn about the current device only through
  its `changed(status, enabled)` signal. Each keeps a read-only status
  label at the top of the tab mirroring the selector's, so a tab whose
  buttons are greyed out still says which node it would act on and why it
  can't -- the picker itself is no longer duplicated.
- `main_window.py` hosts three tabs (`Device` first) and calls
  `refresh_all()` *after* constructing both control tabs, since they'd
  otherwise miss the initial `changed` emission and start blank and
  disabled.

### Fixed
- Action buttons could be re-armed mid-operation: `Refresh` was never
  added to `_action_buttons`, so clicking it during a transfer ran
  `_set_actions_enabled(True)` while a worker was still running. The
  replacement `_sync_actions()` enables buttons only when
  `_device_ready and not _busy`, which matters more now that Refresh
  lives on a separate, always-clickable tab. The `QThread` lifetime
  handling itself is untouched.

## [0.8.7] - 2026-07-30

**"Save to GIF": 0.8.6's raw-bitmap self-padding fix confirmed working on
real hardware by the user.** Closes out the two biggest open "unvalidated
on real hardware" caveats from this whole dithering/raw-bitmap-mode arc:
a from-scratch raw-bitmap-mode frame (not an edit to an existing capture)
renders correctly, and trailing filler bytes appended past the decoder's
declared `width*height` read window are correctly ignored rather than
tripping the content validator or anything else.

### Changed
- Updated docstrings/help text across `protocol.py` (`build_gif_blob`,
  `dither_frame_floyd_steinberg`), `cli.py` (`--dither` help, module
  docstring), and `screen_tab.py` (dither checkbox label, warning message)
  from "unvalidated"/"experimental" to "confirmed working on real
  hardware" for: dithering itself, from-scratch raw-bitmap-mode encoding,
  and the raw-bitmap filler-padding mechanism.

### Known gaps
- Still open, not addressed by this round: the exact device-side dithering
  algorithm remains unknown (this encoder uses its own approximation, not
  a reproduction -- see 0.8.2), the 528-byte prefix's exact purpose, the G
  ramp's off-by-one, and `mode_flag`'s exact overrun mechanics. None of
  these affect the now-confirmed working behavior above.

## [0.8.6] - 2026-07-30

**"Save to GIF": fixed a regression from 0.8.5 -- raw-bitmap mode's own fix
introduced a new failure ("every frame is using raw-bitmap mode, no
run-based content to pad") that the user hit on "very small" GIFs. Root
cause: any single full-panel frame with detail/color everywhere (no flat
region) forces raw-bitmap mode, which was entirely excluded from the
CRC-length-tuning padding trick -- leaving nothing to pad with.**

### Fixed
- Raw-bitmap frames now pad themselves with harmless trailing filler bytes
  when the CRC-length-tuning pass needs to nudge the total upload length
  onto an already-solved `CRC_INIT` entry -- the raw-bitmap decoder is
  confirmed to always read exactly `width*height` bytes and ignore
  anything after, so appended filler is invisible to the renderer, the
  same principle as the existing RLE run-splitting trick, just applied
  differently. Unlike RLE padding (2 bytes/piece, capped by a run's
  length), filler costs exactly 1 byte each with no capacity limit, so it
  always succeeds whenever at least one frame is raw-bitmap mode --
  fixing the exact case that broke, since that's precisely when the old
  RLE-only mechanism had nothing eligible left to use.
- `build_all()` gained a `raw_pad=(frame_index, filler_byte_count)`
  parameter, applied alongside the existing `split_at` mechanism. The
  CRC-tuning pass now prefers a raw-bitmap donor whenever one exists, and
  only falls back to the original RLE run-splitting logic (unchanged,
  including its even-delta and run-capacity constraints) when every frame
  is RLE-mode -- the one case where a raw-bitmap donor isn't available.

### Added
- Tests: a direct regression test reproducing the reported bug (single
  full-panel gradient frame, dithered, no donor frame -- previously raised
  `ValueError`, now succeeds), a test confirming the padded blob's length
  actually lands on a valid chunk-size remainder (not just that it didn't
  raise), and a test confirming a raw-bitmap frame is preferred as the
  padding donor over an available RLE frame with a large run.

### Known gaps
- **New hardware-untested assumption, additive to 0.8.5's**: whether
  anything past the raw-bitmap decoder's confirmed `width*height`-byte
  read window is inspected by some other, still poorly-understood
  mechanism (e.g. the never-fully-decoded content validator) is unknown.
  Recommend a hardware smoke test of a raw-bitmap frame with actual
  appended filler bytes, alongside the still-outstanding raw-bitmap-mode
  smoke test from 0.8.5.

## [0.8.5] - 2026-07-30

**"Save to GIF": fixed a real hardware bug the user hit -- GIFs over ~100KB
uploaded and partially rendered (correct content up top, scrambled green
noise below). Root cause: a silent 16-bit content-length field overflow,
already flagged but never fixed; the real fix is automatic raw-bitmap-mode
encoding for oversized frames, not just a guard rail.**

### Fixed
- `build_gif_blob`'s per-frame header has a 16-bit content-length field
  (`header[12:14]`) that silently wrapped for RLE content over 65,535
  bytes. Dithering makes this easy to hit -- RLE costs 2 bytes per run,
  and dithered pixels alternate constantly, so busy dithered regions
  produce far more RLE bytes than flat safe-color content ever did. This
  matches a directly analogous hardware test already on record (forcing a
  frame's real content past its declared length produced the exact same
  symptom: correct rendering up to the wrong/short boundary, garbled
  content after).
- Any frame whose RLE content would exceed 65,535 bytes is now
  automatically encoded as raw-bitmap mode (`mode_flag = 0x0002`) instead:
  one palette-index byte per pixel, always exactly `width*height` bytes.
  Confirmed by a real hardware capture (`save_to_gif_13`) that the
  raw-bitmap decoder ignores the declared content-length field entirely
  and always reads exactly `width*height` bytes based on the frame's own
  width/height fields -- sidestepping the overflow regardless of size.
  This is a correctness fix, not an opt-in feature: it only activates when
  RLE content would otherwise have produced guaranteed-corrupt output, so
  anything that already worked (safe-color and lightly-dithered content)
  is unaffected and keeps using RLE exactly as before.

### Added
- `GIF_MODE_RLE`/`GIF_MODE_RAW_BITMAP` named constants and
  `_gif_raw_bitmap_content()`. `_gif_largest_run()` gained an `eligible`
  parameter so the CRC-length-tuning padding pass never targets a
  raw-bitmap-mode frame (its content is fixed-size -- there are no tokens
  to pad). A final safety-net check verifies no frame's actual content
  exceeds the 16-bit field after all padding, raising a clear error
  instead of ever silently producing wraparound-corrupted output again.
- Tests: forcing raw-bitmap mode via an all-single-pixel-run image,
  round-tripping raw-bitmap content back to the original pixels via the
  palette, confirming small/existing content still uses RLE unchanged,
  and confirming `_gif_largest_run`'s eligible-filtering works both in
  isolation and through the full `build_gif_blob` path with mixed-mode
  frames.

### Known gaps
- **New, less-tested territory beyond the general "unvalidated on real
  hardware" caveat**: every prior raw-bitmap hardware test was a small
  edit to an already-working captured frame, never a frame built from
  scratch by this encoder. A real hardware smoke test of a large/colorful
  image that actually forces this path is recommended -- ideally a small
  forced-raw-bitmap test image before retrying the user's original
  failing GIF.
- The raw-bitmap-mode-specific "content validator" (row transition/run-
  structure check, never fully decoded) was only ever exercised via edits
  to existing captures, not scratch-built content -- natural dithering
  produced a coherent gradient in every real capture examined, which is
  the kind of content that passed, but this genuinely hasn't been tested
  for this encoder's own output.

## [0.8.4] - 2026-07-30

**"Save to GIF": sped up dithering and CRC computation -- a 10-frame,
full-panel `dither=True` GIF went from 6.3s to 3.1s (~51% faster), after
profiling showed the previous release's dithering was slow enough to
notice in practice.**

### Changed
- `nearest_ramp_value()`'s linear scan (comparing a diffused float against
  each ramp rung via `abs()`) was ~44% of total conversion time by itself.
  Replaced with `RAMP_R_LUT`/`RAMP_G_LUT`/`RAMP_B_LUT`, precomputed 256-entry
  tables built from `nearest_ramp_value()` at import time, turning the hot
  per-pixel quantize step into an O(1) lookup. `nearest_ramp_value()` itself
  is unchanged and still used to build the tables.
- `crc16_modbus()` rewritten table-driven instead of bit-by-bit (~12% of
  total conversion time); verified byte-for-byte equivalent against the old
  formulation on 20 random inputs before replacing it -- same polynomial,
  same output, just faster.

### Investigated but not adopted
- The user asked whether numpy (installed on their system) would help.
  Benchmarked directly rather than assumed: a naive numpy port of the same
  per-pixel-sequential algorithm was **5x slower** (1.6s vs 0.3s/frame) --
  numpy's per-element access overhead loses to plain Python list/tuple
  indexing for this kind of tight, unavoidably sequential loop. A fully
  vectorized numpy rewrite *is* possible (~0.06s/frame, ~5x faster than
  today) but requires switching from Floyd-Steinberg error diffusion to
  ordered/Bayer dithering, trading the current noise-like look for a fixed
  repeating pattern -- decided against, to keep today's dithering algorithm
  and dependency footprint unchanged. Revisit if raw speed ever matters
  more than the visual trade-off.

### Known gaps
- Floyd-Steinberg is a sequential process where each pixel's error depends
  on the ones before it, so this release's lookup-table quantization
  produces a *different* (not byte-identical) dithered pattern than 0.8.3's
  exact-float linear search -- a single rounding-boundary difference
  cascades through the whole diffusion chain. Still always ramp-legal and
  visually equivalent; noted in `dither_frame_floyd_steinberg()`'s
  docstring so a future refactor producing "different but equally valid"
  output again isn't a surprise.
- Still unvalidated on real hardware, unchanged from 0.8.3.

## [0.8.3] - 2026-07-30

**"Save to GIF": added opt-in Floyd-Steinberg dithering, lifting the encoder's
safe-colors-only restriction -- the first practical payoff of the ramp
characterization and pic_scan.dll disassembly work from 0.7.2-0.8.2.**

### Added
- `protocol.py`: `RAMP_R`/`RAMP_G`/`RAMP_B` (the fixed dither ramp, now real
  constants instead of only comment-block prose), `nearest_ramp_value()`,
  `is_ramp_legal_color()` (a strict superset of `is_safe_gif_color()` --
  every safe color is also ramp-legal), and `dither_frame_floyd_steinberg()`
  -- classic raster-order Floyd-Steinberg, per-channel independent,
  quantizing onto the known ramp. This is our own approximation, not a
  reproduction of AULA's still-undiscovered device-side algorithm -- since
  0.8.2 confirmed that algorithm isn't in `pic_scan.dll` at all, and the
  display chip has no dithering of its own, the panel just deterministically
  shows whatever ramp-legal value it's given, so any error-diffusion pattern
  that lands on ramp rungs should look correct on hardware.
- `build_gif_blob(..., dither: bool = False)`: opt-in, purely additive.
  When true, dithers each frame before the existing color gate (now
  `is_ramp_legal_color` instead of `is_safe_gif_color`); when false
  (default), behavior is byte-for-byte unchanged from before this release.
- `--dither` CLI flag (`cli.py`) and a "Dither (experimental)" checkbox
  (`screen_tab.py`), both defaulting off. The GUI's existing pre-upload
  safe-color check is skipped when the checkbox is checked (it would
  otherwise reject almost any image before dithering ever runs).
- `tools/aula_l99_screen/tests/`: the repo's first automated test suite
  (pytest), covering ramp math, dithered-output legality, and a
  before/after regression check that `dither=False` is unchanged.

### Known gaps
- **Unvalidated on real hardware** -- explicitly stated in the CLI help
  text, GUI checkbox label, and `build_gif_blob()`'s docstring. A real
  panel smoke test (upload a small dithered image, confirm it renders
  as a reasonable approximation rather than triggering the fallback
  animation) is recommended before trusting this path.
- Fully-dithered images with no flat/solid region anywhere can starve the
  pre-existing CRC_INIT-length-tuning pass of a long enough run to pad
  onto a valid chunk length, raising the (pre-existing, unrelated) "no
  large enough solid/uniform run" error -- noted in `build_gif_blob()`'s
  docstring; keeping at least one sizable flat region (e.g. a solid
  border) avoids it.
- The device's own dithering algorithm is still not known -- this releases
  a workable approximation, not a reproduction.

## [0.8.2] - 2026-07-30

**"Save to GIF": traced the last untraced GIF-relevant export in
`pic_scan.dll` -- confirmed the dithering decision is not anywhere in
this DLL at all, not just not in `Gif_to_data_LT7689`.**

### Verified
- **`Gif_to_data`** (the non-`_LT7689` sibling export) is functionally
  identical to `Gif_to_data_LT7689` for pixel processing: same direct
  calls (`Scan_aRGB8565`/`Scan_aRGB8888`/`SaveMode16`/`SaveMode24`/flash
  writers), same register-indirect calls resolving to the same `QImage`/
  `QString` accessor set. The one difference is a single extra call into
  a previously-unnoticed unexported helper.
- That helper (VA `0x6a9c17f0`) reads a file in 2KB chunks and computes a
  running checksum via two 256-byte lookup tables. Dumped both tables
  directly from the PE image's `.rdata` section and diffed them
  byte-for-byte against a from-scratch table for the reflected polynomial
  `0xA001` -- the same polynomial this repo's own `crc16_packet()` already
  uses for the wire protocol -- exact match, confirmed standard
  **CRC-16/ARC**. This is a file-integrity checksum (almost certainly
  verifying a freshly-written flash-blob file), unrelated to pixel
  dithering.

### Changed
- **Every exported GIF-relevant function in `pic_scan.dll`, and
  everything reachable from any of them, has now been examined.** Both
  top-level GIF export entry points (`Gif_to_data` and
  `Gif_to_data_LT7689`) are ruled out, closing off the DLL entirely as a
  location for the dithering decision.
- The one remaining candidate is code in the qt-tool app's own `.exe`
  itself (not yet disassembled at all) -- e.g. a
  `QImage::convertToFormat()` call with an explicit dithering flag,
  executed by the app before ever calling into `pic_scan.dll`, which
  would be invisible no matter how thoroughly this DLL is traced.

### Known gaps
- The actual dithering decision algorithm is still not located --
  `pic_scan.dll` is now fully exhausted as a search space; the qt-tool
  `.exe` itself is the only remaining lead for continuing this
  particular thread.
- Same longstanding open items otherwise: the 528-byte prefix's exact
  purpose, the exact diffusion coefficients/direction, the G ramp's
  off-by-one, `mode_flag`'s exact overrun mechanics, `save_to_gif_2`'s
  inefficiency.

## [0.8.1] - 2026-07-30

**"Save to GIF": resumed the 0.7.7 static-analysis pivot and closed it
out -- traced two previously-unexamined `pic_scan.dll` exports
(`SaveMode16`/`SaveMode24`), confirmed the entire `Gif_to_data_LT7689`
call graph is now exhaustively free of dithering logic, and checked in a
persisted RE artifact so this doesn't have to be re-derived again.**

### Verified
- **`SaveMode16`** (VA `0x6a9c24f0`, never examined in 0.7.7) dispatches
  on a mode parameter: modes `{2,5}` pack ARGB4444, modes `{1,4}` pack
  RGB565, and all other modes take a "default" path that also just does
  RGB565 truncation -- all three are **plain bit-truncation, no
  dithering** (one mode has an unrelated special case remapping opaque
  pure-black to `0x0021` so `0x0000` stays a usable transparency
  sentinel). Modes `{3,4,5}` then call onward into exactly the chain
  traced in 0.7.7 -- `Scan_ColorTB_Data` -> `Scan_ColorTB_from_image_data`
  -> `Image_u16Data_to_colorTBu8Data` -> `ColorTB_u8Data_to_zipU8Data` --
  which **closes the GIF pipeline end-to-end for the first time**:
  `Gif_to_data_LT7689` calls `SaveMode16` directly, resolving 0.7.7's
  open question of how its four traced functions are actually reached.
- **`SaveMode24`** (VA `0x6a9c3290`, also unexamined) confirmed as the
  trivial 24bpp sibling -- lossless 8-bit passthrough, no quantization
  possible at that depth, not a dithering candidate.
- **`Scan_ColorTB_Data`** (VA `0x6a9c2420`, 208 bytes) fully traced: pure
  per-chunk orchestration, looping up to 255 times over
  `Scan_ColorTB_from_image_data`. Clarifies that the well-known
  "chained in <=256px pieces" cap most likely originates in **this**
  chunk-count limit, not the RLE token format's separately-identical
  256-run cap in `ColorTB_u8Data_to_zipU8Data`.
- **`Scan_ColorTB_from_image_data`** (VA `0x6a9c14d0`, 192 bytes) fully
  traced: confirmed **exact-match palette dedup** on already-16-bit
  RGB565 words via linear search, zero per-channel math of any kind.
- **`ColorTB_u8Data_to_zipU8Data`** and **`Scan_aRGB8888`** (Checkpoints
  A/B for this round) fully traced and confirmed as previously
  characterized: pure RLE encoder (with a per-row raw-copy overflow
  fallback) and a plain 32-bit raw-copy sibling of `Scan_aRGB8565`,
  respectively. No dithering in either.
- All ~55 register-indirect calls inside `Gif_to_data_LT7689` traced back
  to their register loads: every one resolves to `QImage`
  width/height/pixel/destructor, `QString`/`QCoreApplication` string and
  event-loop housekeeping, or memory alloc/free/refcount boilerplate.

### Changed
- **`Gif_to_data_LT7689`'s entire reachable call graph -- direct and
  indirect -- is now exhaustively traced**, not "partially traced,
  banked" as in 0.7.7. Every step in the confirmed chain (raw pixel scan
  -> RGB565 truncation -> palette dedup -> exact-match quantize -> RLE)
  is a stateless, per-pixel-independent operation: no ramp constant
  appears as an immediate anywhere, and no per-channel accumulator is
  carried across loop iterations.
- Since the wire-capture evidence (0.6.1-0.6.9) already proved dithered
  patterns exist in the bytes actually transmitted, the dithering must
  happen somewhere in the PC-side pipeline before upload -- just
  demonstrably not anywhere `Gif_to_data_LT7689` reaches. Two untested
  leads remain for a future round: the sibling export `Gif_to_data`
  (non-`_LT7689`, never actually traced despite a similar call-target
  profile), and code in the qt-tool app itself, outside `pic_scan.dll`
  entirely (e.g. a `QImage::convertToFormat()` call with an explicit
  dithering flag).

### Added
- `tools/aula_l99_screen/re_notes/pic_scan_dll.md`: the disassembly
  transcript 0.7.7 was missing -- exact `objdump`/export-table commands,
  the full ordinal/RVA/VA/name export table, relevant IAT import
  resolutions, and per-function findings for every function traced this
  round and in 0.7.7. Exists so the next round doesn't have to re-derive
  RVAs and re-slice the disassembly from scratch.

### Known gaps
- The actual dithering decision algorithm is still not located -- this
  round *ruled out* the previously-most-likely location rather than
  finding it. `Gif_to_data` (non-`_LT7689`) and the qt-tool app's own
  code outside `pic_scan.dll` are the two remaining candidates.
- Same longstanding open items otherwise: the 528-byte prefix's exact
  purpose (though `ColorTB_u8Data_to_zipU8Data` and `Scan_ColorTB_Data`
  both independently touch a `0x204`/516-byte-strided region this round,
  reinforcing but not proving the existing palette-table suspicion), the
  exact diffusion coefficients/direction, the G ramp's off-by-one,
  `mode_flag`'s exact overrun mechanics, `save_to_gif_2`'s inefficiency.

## [0.8.0] - 2026-07-30

**New tool: `aula_l99_gui`, a PySide6 GUI wrapping both `aula_l99_hacky`
(keyboard) and `aula_l99_screen` (touchscreen) so their core features can be
driven without CLI flags.** First GUI in the repo; imports both tools'
`protocol.py`/`device.py` directly rather than shelling out to their CLIs.

### Added
- `tools/aula_l99_gui/`: a two-tab app (`main_window.py`, `keyboard_tab.py`,
  `screen_tab.py`) covering a curated subset of each CLI, not full parity.
  Keyboard tab: device list/refresh, handshake test, per-key color, built-in
  effects (dropdown tagged confirmed/untested from `EFFECT_CONFIRMED`) with
  speed/brightness, and RTC set -- cable path only, same as the CLI. Screen
  tab: single-image upload to `photo-frame`/`background`, and GIF upload
  from a folder, multiple files, or an animated `.gif`, with a pre-upload
  safe-color check (`is_safe_gif_color`) that lists offending colors instead
  of sending something the from-scratch encoder can't build.
- `workers.py`: background `QThread` workers reimplementing each CLI's
  device-I/O loop (`aula_l99_hacky/cli.py`'s `_run_cable`/`_run_sequence`,
  `aula_l99_screen/cli.py`'s `cmd_upload` packet loop) against the public
  `protocol.py`/`device.py` API, emitting Qt signals for live progress
  instead of printing -- keeps the UI responsive during a handshake or
  upload.
- `tools/aula_l99_gui/README.md`: install/run instructions and a feature
  summary.

### Fixed
- A `QThread` teardown crash ("QThread: Destroyed while thread ... is still
  running", then a segfault) hit on first real hardware use, right after a
  successful screen upload. Root cause: the "operation finished" UI update
  was gated on the *worker's* `finished` signal, which fires before the
  underlying `QThread` has actually stopped -- reassigning or nulling
  `self._worker`/`self._thread` at that point could drop Python's last
  reference to a `QThread` that was still alive. A first fix attempt (adding
  `deleteLater()` alongside the manual nulling) traded that bug for a
  double-free race between Qt's deferred deletion and Python's
  refcount-triggered one. Final fix: gate re-enabling the UI (and thus
  allowing a new worker/thread to be created) on `QThread.finished`, not
  `Worker.finished`, and never explicitly null the references -- the next
  run's reassignment (or normal object teardown) drops them safely once
  `deleteLater()` has already made the underlying C++ object releasable.
  Verified with an offline threaded regression test simulating rapid
  consecutive uploads that reproduced both crash variants before the fix and
  passed cleanly after.
- `main_window.py` now blocks closing the window while a keyboard
  transaction or screen upload is in flight (`closeEvent` checks each tab's
  `is_busy`), since interrupting a screen upload partway through can freeze
  the panel.

### Known gaps
- Curated feature set only: no raw-hex-send, `--convert`/`--describe`,
  `--address` override, `--ignore-nak`, or video-file GIF frame extraction
  -- use the CLIs directly for those.
- GIF upload always applies one uniform delay to every frame regardless of
  source, rather than reading a source `.gif`'s own embedded per-frame
  delays -- sidesteps the delay-uniformity constraint from 0.7.6 entirely
  rather than surfacing it.
- Not tested against the dongle path (disabled in the UI, same as the CLI).

## [0.7.7] - 2026-07-30

**"Save to GIF": identified the underlying display chip and confirmed the
compression/dithering format is AULA's own bespoke engineering, then
disassembled key functions in `pic_scan.dll` (the vendor's own encoder)
to trace the real pipeline -- a real methodology shift (static binary
analysis instead of hardware experiments), banked partway through.**

### Verified
- **Chip identified**: `pic_scan.dll` exports two GIF encoder functions,
  `Gif_to_data` and `Gif_to_data_LT7689` -- the panel is built on
  Levetop's **LT7689**, a Cortex-M4 serial UART TFT graphics controller.
  Its public datasheet and application notes were checked in detail and
  document only a generic serial playback command (`Display GIF`, opcode
  `0x88` -- "start playing file N," not a format spec) and a companion
  tool (`LT_IMAGE_TOOL.exe`) whose own output format is confirmed to be
  plain, uncompressed 16bpp/24bpp RGB with no palette and no RLE.
  Confirms our entire RLE/8-slot-dithering/528-byte-prefix scheme is
  AULA's own bespoke compression layer, not a documented chip-vendor
  format -- it exists nowhere except inside this DLL and our own
  reverse-engineering.
- Recovered full demangled C++ export names from `pic_scan.dll` (not
  fully stripped) and disassembled the GIF-relevant ones (32-bit x86,
  `objdump -d -M intel`, RVAs resolved via the PE export table, image
  base `0x6a9c0000`):
  - `Scan_aRGB8565`: confirmed to be **plain bit-truncation** ARGB->RGB565
    (`R>>3`-style masking, no rounding, no dithering whatsoever). Almost
    certainly the simple photo-frame/background converter, not the GIF
    path -- consistent with that format's already-confirmed simplicity.
  - `Scan_ColorTB_Data`: divides a frame's pixels into up to 255 chunks,
    each a 0x204-byte (516-byte) substructure -- matching the same
    "0x204 bytes per iteration" stride independently inferred from
    `Image_u16Data_to_colorTBu8Data`'s loop structure.
  - `Scan_ColorTB_from_image_data`: builds each chunk's local palette via
    **exact-match, first-appearance-order deduplication** -- directly
    matching our own reverse-engineered "palette in first-appearance
    order" model.
  - `Image_u16Data_to_colorTBu8Data`: converts pixels to palette indices
    via a **simple linear search** (up to 256 entries) for an EXACT
    match against the chunk's table. If no exact match is found, no
    output byte is written at all -- no fallback, no on-the-fly
    quantization.
  - The zero-initialized table `Scan_ColorTB_from_image_data` builds
    (516 bytes / 258 u16 entries, at struct offsets `0x430`-`0x634`) is
    structurally very close to our long-mysterious 528-byte prefix
    (same role: fixed-size, mostly-zero, holds RGB565 palette entries).
    Not proven byte-for-byte identical (off by a small, plausibly
    explainable amount), but strong circumstantial support for what that
    region fundamentally is.

### Changed
- The critical implication of point 4 above: since an unmatched pixel is
  silently skipped (not quantized in place), whatever decides *which*
  colors need dithering and rewrites source pixels into the correct
  alternating ramp-representable sequence must run **before** any of
  these four functions -- it isn't in any of the GIF-related exports
  checked. Most likely inlined inside `Gif_to_data_LT7689` (a large
  orchestrator function handling file I/O and memory allocation, only
  partially traced) or in a private, unexported helper with no symbol
  name to search for.

### Known gaps
- The actual dithering decision algorithm (which ramp levels, what
  spatial/duty-cycle pattern) was NOT located. Finding it would mean
  methodically stepping through `Gif_to_data_LT7689`'s full call graph
  rather than checking named exports -- a genuinely larger effort than
  this round, banked here rather than pursued further for now.
- The 528-byte-prefix/table correspondence is suggestive, not proven
  exact.
- Same longstanding open items otherwise: the exact dithering diffusion
  algorithm, `mode_flag`'s exact overrun mechanics, `save_to_gif_2`'s
  inefficiency.

## [0.7.6] - 2026-07-30

**"Save to GIF": `--upload` now accepts a single animated `.gif` or a
video file directly, auto-generating frames -- and this immediately
surfaced a real, previously-untested constraint: all frames in one
upload must share the SAME delay value, not just any valid value.**

### Added
- `cli.py`'s `--upload` now accepts, for `--target gif`: one or more
  images (unchanged), a single animated `.gif` (all frames used, each
  keeping its own embedded delay by default), or a single video file
  (`.mp4`/`.mov`/`.avi`/`.mkv`/`.webm`/`.m4v`, frames extracted via
  ffmpeg, requiring `--fps` and/or `--max-frames` -- no silent default
  frame count). New `--fps` and `--max-frames` flags. `--gif-delay`, when
  explicitly given, now overrides every frame's delay uniformly
  (including a source GIF's own embedded delays or a video's computed
  one); its default changed from `50` to `None` so this override
  distinction is possible.
- `protocol.build_gif_blob()`'s `delay` parameter now accepts a list (one
  value per frame) as well as a single int, matching the TOC's actual
  per-entry field structure.

### Verified
- End-to-end real-CLI test (not a script bypassing it): a synthetic
  2-frame GIF (solid red 300ms, solid blue 700ms) run through
  `python3 -m aula_l99_screen.cli --upload test_anim.gif --target gif`
  extracted both frames correctly (delays 30/70 centiseconds, matching
  the 300ms/700ms source via the established ms/10 conversion) and
  uploaded -- but the panel showed the FALLBACK animation, not the
  intended content.
- Isolated the cause directly: the identical red/blue content re-uploaded
  with a uniform `delay=50` for both frames rendered correctly. The same
  content again with a uniform `delay=30` (still not 50, but the same
  value for every frame) ALSO rendered correctly. Only the non-uniform
  `[30, 70]` case fell back. Confirms the constraint is about delay
  values matching ACROSS frames within one upload, not about hitting any
  particular value -- something never tested before, since every capture
  and every hand-built test prior to this always used the same delay
  (usually 50) for every frame.
- The video-extraction path was verified mechanically (both `--fps` and
  `--max-frames`-derives-fps modes correctly produce the right frame
  count and per-frame delay), though not yet tested end-to-end on
  hardware, since a real/synthetic video's colors failed the existing
  safe-color check first (see Known gaps).

### Changed
- The delay field join a growing pattern: several TOC/sub-header fields
  turn out to have real validation behind them beyond just "what does
  this field mean" (the 528-byte prefix's 8-byte tolerance, the
  transition/run-structure content check, and now delay uniformity).
- This directly affects the new `.gif`-import feature's practical
  usefulness: many real animated GIFs vary per-frame delay (e.g. holding
  the last frame longer), and using each frame's own embedded delay by
  default -- the behavior just added -- will silently produce a
  non-working upload whenever those delays differ. Not yet fixed or
  guarded against; see Known gaps.

### Known gaps
- `cli.py` does not yet warn or error when a source GIF's extracted
  per-frame delays are non-uniform -- it will currently build and upload
  a blob that's confirmed to fail on real hardware. Needs a decision:
  hard error, automatic normalization (e.g. use the first/max/most-common
  delay for all frames) with a clear warning, or something else.
- Whether the constraint is "all frames exactly equal" or something
  looser (e.g. "monotonic," "within some tolerance") is untested -- only
  one non-uniform pair (30 vs. 70) and two uniform cases (30, 50) have
  been tried.
- Real compressed video (even a flat single-color source through
  ffmpeg's default YUV handling) reliably fails the existing safe-color
  check by 1-2 units (e.g. red renders as `(253,0,0)` instead of
  `(255,0,0)`) -- an inherent property of how ffmpeg/most video codecs
  represent color, not a bug in the new extraction code. Practically
  limits video input to synthetic/exact-color sources under the current
  encoder scope.
- Same longstanding open items otherwise: the 528-byte prefix's true
  purpose, the exact dithering diffusion algorithm, `save_to_gif_2`'s
  inefficiency.

## [0.7.5] - 2026-07-30

**"Save to GIF": `mode_flag` confirmed as a real, functional RLE-vs-raw-
bitmap decoder switch -- forcing a mismatch produces garbled, structured
content, not the usual fallback animation.** First direct hardware test
of `mode_flag`'s role, in both directions, on `save_to_gif_13`.

### Verified
- Frame 0 (solid red, real `mode_flag=0x0100`/RLE, content untouched)
  flipped to `mode_flag=0x0002`/raw-bitmap: all 79 packets acked. The
  panel rendered a complex, clearly non-fallback
  bands including a light-gray-like region, a red/black staticky "noise"
  band, and clean red regions, repeating a few times vertically. This is
  NOT the fallback animation and is NOT simply garbage -- the visible
  structure (colors and rough layout resembling frame 1's real 3-stripe
  content) is consistent with the raw-bitmap decoder reading a full
  width*height=153600-byte window starting right after frame 0's 528-byte
  prefix regardless of frame 0's own much smaller declared size, likely
  running past frame 0's real boundary into frame 1's actual header and
  content bytes in flash -- though the exact byte-level correspondence
  wasn't rigorously confirmed, only the qualitative shape of the result.
- Frame 1 (the real raw-bitmap 3-stripe frame, `mode_flag=0x0002`,
  content untouched) flipped to `mode_flag=0x0100`/RLE: all 79 packets
  acked. The panel showed a garbled, staggered scanline pattern confined
  to roughly the top 25% of the screen, with the remaining ~75%
  unchanged solid red -- a partial, incomplete render, not the fallback
  either.
- Neither direction triggered the panel's usual cached fallback
  animation -- notably different from every other content-validation
  failure in this whole investigation (the transition/run-structure
  violations, the 528-byte-prefix threshold violations), which always
  fell back to the same generic animation. Both restores this round
  acked and took immediately, confirmed back to the original
  solid-red/3-stripe alternation.

### Changed
- Confirms `mode_flag` is a genuine, functional field selecting between
  two different decoders, not a passive/descriptive tag -- forcing a
  mismatch doesn't get validated-and-rejected the way most content edits
  in this investigation have been; it just gets decoded wrong, producing
  visibly structured (not random) garbage. This suggests whatever
  structural validation exists (the transition/run-structure check, the
  528-byte-prefix count threshold) is checked WITHIN each decoder's own
  path, not by a separate universal content check applied regardless of
  mode -- a mismatched mode_flag bypasses the checks that would normally
  catch a malformed frame in its own format, because the bytes are being
  fed to the wrong decoder entirely rather than being malformed input to
  the right one.

### Known gaps
- The exact byte-level mechanics of the raw-bitmap overrun (whether it
  really reads into frame 1's real flash bytes, the precise mapping of
  visible bands to specific byte ranges) aren't confirmed -- only the
  qualitative "garbled but structured, resembling neighboring frame
  content" result.
- Why the RLE-misinterpretation case fills only ~25% of the screen before
  stopping isn't explained precisely (plausible: interpreting bytes as
  length/flag pairs instead of raw indices roughly halves how many
  content bytes correspond to one pixel of coverage, so the declared
  content-length in bytes runs out before covering all 153600 pixels --
  not verified with an exact token-count calculation against the photo).
- Only tested on save_to_gif_13's two frames; whether this generalizes to
  other content is untested.
- Same open items otherwise: the 528-byte prefix's true purpose, the
  exact dithering diffusion algorithm, `save_to_gif_2`'s inefficiency.

## [0.7.4] - 2026-07-30

**"Save to GIF": linear interpolation between bracket rungs is a good
approximation of the per-channel duty cycle, but not an exact formula --
consistent with error diffusion, not a precise closed-form computation.**
Offline re-analysis of `save_to_gif_14.pcapng` (no new hardware), now
possible because 0.7.2/0.7.3 nailed down the exact ramp.

### Verified
- For every column/channel needing two-rung dithering (960 data points
  across the 320-column rainbow), computed the naive "linear
  interpolation between the two bracketing ramp rungs" predicted duty
  cycle and compared it to the actual observed duty cycle (from real
  pixel counts). Mean absolute deviation: 3.4 percentage points. Mean
  *signed* deviation: 0.002 -- effectively zero, meaning there's no
  systematic bias toward either rung; deviations are roughly balanced
  (357 columns observed-high, 212 observed-low, 391 close enough to call
  exact).
- The worst individual mismatches (up to 26 percentage points) cluster
  near ramp segments close to 0 (e.g. the `{0,40}` G bracket), not
  uniformly across the whole range.

### Changed
- Confirms linear interpolation is the right first-order model for
  *what* duty cycle each dithered channel is aiming for, but the actual
  per-column result isn't a precise closed-form computation -- it has
  real, non-negligible variance (well above simple integer-rounding noise
  at 480 samples, which would be under 0.3 percentage points). This is
  more consistent with an error-diffusion-style algorithm, which
  approximates the correct long-run ratio well but doesn't hit it exactly
  in a finite sample, than with an exact ordered-dither formula.

### Known gaps
- The actual diffusion algorithm (coefficients, propagation direction,
  whether it resets per column/row or runs continuously across the whole
  raster) is still not decoded -- this round confirms the *character* of
  the deviation (unbiased, real variance, concentrated near certain
  bracket segments) without identifying the mechanism.
- Same open items otherwise: the G ramp's off-by-one, the 528-byte
  prefix's true purpose, `mode_flag`'s general meaning, `save_to_gif_2`'s
  inefficiency.

## [0.7.3] - 2026-07-30

**"Save to GIF": the dither ramp extends all the way to each channel's
native maximum -- closing 0.7.2's open question about higher rungs.**
`save_to_gif_15.pcapng` -- the same hue sweep as `save_to_gif_14`, but at
95% brightness instead of 70% (targets up to 242, much closer to the
255 ceiling) -- was captured specifically to probe for rungs above the
ones seen before.

### Verified
- Two new top rungs appear that 0.7.2's dimmer test never triggered: R/B
  index 31 (= 255) and G index 63 (= 255). Combined with the previously
  known rungs, the full ramps are now: R and B, 6 levels -- `{0, 6, 12,
  19, 25, 31}` (8-bit: 0, 49, 99, 156, 206, 255); G, 7 levels -- `{0, 10,
  21, 32, 42, 53, 63}` (8-bit: 0, 40, 85, 130, 170, 215, 255).
- The R/B ramp is an *exact* even 6-way split of the full 0-31 native
  range (`round(i*31/5)` for i=0..5 reproduces `{0,6,12,19,25,31}`
  precisely). The G ramp is very close to but not quite an exact even
  7-way split of 0-63 -- it differs from the naive rounding of `i*63/6`
  by exactly 1 at a single point (53 vs. an evenly-rounded 52); every
  other level matches exactly. Reported honestly as "very close, not
  exact" rather than forcing a clean formula that doesn't quite fit.
- Weighted-average color per column again matches the intended target
  hue closely across all 320 columns at this brighter setting: mean error
  ~3.8/255, max ~10.5/255 -- consistent with 0.7.2's dimmer test, now
  confirmed at a second, much brighter setting.
- Both frames again `mode_flag=0x0002` raw-bitmap, byte-identical to each
  other, content exactly 153600 bytes -- same structural confirmations as
  every prior raw-bitmap capture.

### Changed
- The dither ramp is now fully characterized end-to-end: it spans each
  channel's ENTIRE native range (0 to 31 for 5-bit R/B, 0 to 63 for 6-bit
  G), not capped below the maximum as 0.7.2 left open. The apparent "cap"
  in that round was purely because neither test image's targets were
  bright enough to need the top rung -- not a real property of the ramp.

### Known gaps
- The G ramp's single off-by-one deviation from a naive even split is
  unexplained -- worth keeping in mind if it recurs or resolves with more
  data.
- Same open items as 0.7.2 otherwise: the exact snap-vs-dither selection
  rule and duty-cycle algorithm, the per-row variation's mechanism, the
  528-byte prefix's true purpose, `mode_flag`'s general meaning,
  `save_to_gif_2`'s inefficiency.

## [0.7.2] - 2026-07-30

**"Save to GIF": found the dithering ramp -- a FIXED, shared set of RGB565
quantization levels, reused verbatim across totally different images.**
`save_to_gif_14.pcapng` -- a dimmed rainbow (full hue sweep, ~70%
brightness, so every one of 320 columns needs dithering) -- gives by far
the richest dithering dataset yet, and it resolves the open question of
whether dither-pair colors are computed per-image or drawn from something
fixed.

### Verified
- Both frames (identical source images, as designed) are `mode_flag=0x0002`
  raw-bitmap, byte-for-byte identical to each other -- consistent with
  every prior finding (deterministic, content-driven encoding; raw bitmap
  for busy/richly-dithered content).
- Weighted-average color per column (using actual per-pixel flag
  frequencies and the real palette) matches the intended target hue
  closely across all 320 columns: mean error ~4/255, max ~11.5/255. This
  is the broadest confirmation yet that the dithering genuinely
  reconstructs the intended color on average, not just for the 1-2 colors
  tested before.
- The palette (46 entries) decomposes, in RGB565's native per-channel
  index terms, into two small FIXED sets: R and B indices are only ever
  one of {0, 6, 12, 19, 25} (of 0-31 possible); G indices are only ever
  one of {0, 10, 21, 32, 42, 53} (of 0-63 possible) -- a 5-level ramp for
  the 5-bit channels and a 6-level ramp for the 6-bit channel, each
  roughly evenly spaced from 0 up to their top rung (206/255 for R and B,
  215/255 for G).
- Cross-checked directly against `save_to_gif_13`'s completely different
  image (light gray + dark red stripes): every one of its dithered
  palette entries' per-channel indices falls within this SAME ramp. The
  one exception (R index 31, i.e. 255) is the clean, undithered reference
  red -- not part of the dither ramp at all, consistent with 255 already
  being a direct-slot "safe" value needing no dithering.
- Confirmed rows are NOT identical within a column (row 0 != row 240 !=
  row 479 for the same target color) -- the per-row variation seen in
  `save_to_gif_13`'s light-gray stripe is pervasive across this whole
  image, not a minor addendum to an otherwise-static pattern.

### Changed
- Refines the model significantly: dithering doesn't compute a bespoke
  pair of nearby colors per target -- it snaps each channel independently
  to the nearest rung(s) of this SAME fixed 5-level/6-level ramp,
  dithering between two adjacent rungs when the target falls between them
  and just using a single rung directly (no dithering for that channel)
  when it's already close enough. Different pixels use anywhere from 2 to
  4 distinct palette entries depending on how many of the 3 channels
  actually need bracketing for that specific target -- not always the
  full 8-corner combinatorial scheme seen for `save_to_gif_13`'s one
  richly-dithered color.
- This is very likely a genuine, image-independent hardware/firmware
  lookup table, not something computed fresh per upload -- the same exact
  rung values appearing byte-for-byte in two unrelated captures is strong
  evidence against per-image computation.

### Known gaps
- Whether the ramp has MORE/higher rungs than observed (n=25/53 might just
  be the highest rung our two test images ever needed, since neither
  reached the very top of the brightness range) is untested -- would need
  a brighter test image (targets approaching 255) to check for rungs above
  the ones seen so far.
- The exact rule for choosing single-rung-snap vs. two-rung-dither per
  channel, and the exact duty-cycle-selection algorithm between two rungs,
  is still not decoded -- only the SET of available rungs is now known.
- The per-row variation's exact mechanism (still hypothesized as error
  diffusion, not confirmed) has much richer data to work with now but
  hasn't been re-analyzed against this larger dataset yet.
- Same longstanding open items otherwise: the 528-byte prefix's true
  purpose, `mode_flag`'s general meaning, `save_to_gif_2`'s inefficiency.

## [0.7.1] - 2026-07-30

**"Save to GIF": `--target gif` is now a real CLI feature, confirmed
working end-to-end on hardware.** Wires up 0.7.0's proof-of-concept
encoder into `protocol.py`/`cli.py` properly, rather than leaving it a
standalone script.

### Added
- `protocol.build_gif_blob(frames_pixels, width, height, delay=50)`: the
  from-scratch encoder from 0.7.0, generalized -- takes any number of
  frames, validates every pixel's color up front and raises a `ValueError`
  listing every offending color and its pixel count if any need dithering,
  and raises a clear `ValueError` (naming the largest run found and the
  capacity needed) if no frame has a large enough solid/uniform region for
  the `CRC_INIT`-length-matching trick to work. Re-verified byte-for-byte
  identical to 0.7.0's hand-built, hardware-confirmed blob.
- `cli.py`: `--upload` now takes one or more image paths (`nargs="+"`).
  `--target gif` builds a multi-frame GIF from them (one image per frame);
  every other target still requires exactly one image, erroring clearly
  otherwise. New `--gif-delay` flag (default 50, matching every capture).

### Verified
- Real end-to-end test: two fresh PNGs (solid blue, a 16x16 red/white
  checkerboard) written via PIL, uploaded with the actual
  `python3 -m aula_l99_screen.cli --upload frame0.png frame1.png --target
  gif` command -- not a script bypassing the CLI. All 12 packets acked,
  and the user confirmed the panel showed the intended animation.
- The full pipeline (image loading through `cli.py`'s new
  `_encode_gif_frame_pixels()`, then `protocol.build_gif_blob()`) produces
  a blob byte-for-byte identical to 0.7.0's manually-verified one.

### Fixed
- `Image.getdata()` is deprecated in Pillow >=12 (removal slated for
  Pillow 14, 2027-10-15); `cli.py` now prefers `get_flattened_data()` when
  available, falling back for older Pillow versions.

### Known gaps
- Same scope limits as 0.7.0: RLE-mode, non-dithered ("safe") colors only.
  Photos, the raw-bitmap format, and dithering are still out of reach for
  an encoder.
- Not stress-tested with more than 2 frames, larger palettes, or images
  without a large solid region (the error path is implemented and unit
  tested, but not exercised against a real user image that hits it).

## [0.7.0] - 2026-07-30

**"Save to GIF": the first fully from-scratch GIF -- not derived from any
capture -- rendered correctly on hardware.** Every success before this
round was a small edit to already-valid captured content; this is the
first proof the RLE model is complete enough to actually build new
working uploads, not just decode and mutate existing ones.

### Verified
- Hand-built a 2-frame, 320x480 blob purely from the confirmed model: a
  TOC of 20-byte entries, each frame a 528-byte fixed prefix (copying the
  two still-unexplained-but-always-constant magic byte pairs verbatim,
  writing width/height/size32/content-length/mode_flag/palette from
  scratch) followed by continuous-raster-order RLE content (palette
  built in first-appearance order, runs chained in <=256px pieces,
  restricted to "safe" colors -- max(R,G,B) in {0,255} -- so no dithering
  needs to be solved). Content: frame 0 solid blue, frame 1 a 16x16 red/
  white checkerboard -- new content, never captured or mutated from one.
- Solved the practical `CRC_INIT` obstacle without any new brute-force:
  since a solid run can be split into any number of chained same-flag
  tokens without changing the rendered image (each split costs exactly 2
  bytes), the blob's total length was tuned by padding frame 0's single
  run into more pieces until the wire packetization's final chunk landed
  on an already-solved length (1080 bytes, from `save_to_gif_12`) with no
  new CRC_INIT value needed and no external padding bytes.
- Self-verified before upload: TOC `crc16_modbus` matches, both frames'
  RLE content sums to exactly 153600 pixels, packetizes to 12 packets with
  no exceptions.
- Uploaded to the panel: all 12 packets acked, and the panel showed
  exactly the intended animation -- solid blue alternating with the red/
  white checkerboard -- confirmed by the user, not the fallback.

### Changed
- This is the strongest evidence yet that the GIF format's RLE encoding,
  TOC/sub-header layout, and packetization are genuinely fully understood
  for the "safe colors, no dithering" case -- not just consistent with
  every capture examined, but sufficient to construct new, independently
  verified working uploads.
- Scope: this specific success is for `mode_flag=0x0100` RLE-encoded
  content only, using colors that don't need dithering. Photos, the
  raw-bitmap format, and any color requiring dithering are still out of
  scope for an encoder -- the palette/dithering assignment algorithm
  (0.6.6-0.6.9, 0.6.18) isn't solved well enough to build correct
  dithered content from scratch yet.

### Known gaps
- Not yet wired into `cli.py` as a real `--target gif` option -- this was
  a standalone proof-of-concept script, not integrated tooling.
- The `CRC_INIT`-length-matching trick (splitting a solid run to hit an
  already-known final-chunk length) only works when some frame has a
  large enough solid/uniform region to split -- a general encoder needs a
  fallback or a clear error for images that don't have one.
- No multi-frame (>2), non-solid-reference-frame, or larger/more complex
  from-scratch content has been tried yet.
- Same longstanding open items otherwise: the 528-byte prefix's true
  purpose, the dithering algorithm, `mode_flag`'s general meaning, the
  delay field's unit, `save_to_gif_2`'s inefficiency.

## [0.6.19] - 2026-07-30

**"Save to GIF": "the unidentified sub-header byte [13]" was stale
bookkeeping, not a real gap.** No hardware needed -- this was a
documentation audit, prompted by the user asking to investigate it
directly.

### Changed
- Traced "sub-header byte [13]" back through the changelog history. Both
  bytes that could plausibly be meant are already fully solved elsewhere:
  the TOC-entry's own byte 13 is the frame count, resolved explicitly back
  in the `save_to_gif_3.pcapng` round ("TOC frame-count ambiguity
  resolved"); the per-frame sub-header's byte 13 is simply the high byte
  of the `[12:14]` content-length `u16` field, solved from the start and
  re-verified repeatedly this session (including for `save_to_gif_13`'s
  overflowing case). Neither is an open mystery. The item had been
  mechanically carried forward in the "Known gaps" / "Still open" lists
  across roughly a dozen rounds without anyone re-checking whether it was
  still true.
- Removed from `protocol.py`'s and `README.md`'s open-items lists, with a
  short correction note explaining why, so it doesn't get silently
  reintroduced.

### Known gaps
- None closed by hardware this round -- this was purely a documentation
  correction. Real open items are otherwise unchanged: the 528-byte
  prefix's contents/purpose (though its 8-byte tolerance is now known),
  the dithering algorithm, `mode_flag`, the delay field's unit,
  `save_to_gif_2`'s inefficiency.

## [0.6.18] - 2026-07-30

**"Save to GIF": the 8-byte tolerance is not specific to frame 0 or the
RLE format -- it's identical in frame 1's raw-bitmap mode too.**

### Verified
- Repeated the 0.6.17 bisection on `save_to_gif_13`'s frame 1 (the
  154128-byte raw-bitmap frame, padding starting at offset 38 instead of
  frame 0's offset 18): 8 non-zero bytes passes, 9 fails. Exactly the same
  boundary as frame 0 (1728 bytes, RLE mode).

### Changed
- With the same exact threshold holding across two frames of very
  different size (1728 vs. 154128 bytes) and different content encoding
  (RLE tokens vs. raw indexed bitmap), "8" looks like a genuine constant
  of the format or firmware -- not an artifact of frame size, position
  within the blob, or encoding mode. Still no candidate mechanism for why
  8 specifically (alignment, a small fixed buffer, a coarse checksum
  granularity, etc. are all just guesses at this point).

### Known gaps
- No candidate explanation for why 8 is the specific number.
- Same open items otherwise: sub-header byte [13], dithering algorithm,
  `mode_flag`, delay field's unit, `save_to_gif_2` inefficiency.

## [0.6.17] - 2026-07-30

**"Save to GIF": the 528-byte prefix's tolerance boundary is exactly 8
bytes, and it's a pure count threshold, not a specific critical byte.**
Tight bisection of 0.6.16's 5-10 byte range, plus a confirming isolation
test.

### Verified
- Bisected the padding-region tolerance from 0.6.16 down to an exact
  boundary: 7 bytes non-zero passes, 8 bytes passes, 9 bytes fails, 10
  bytes fails (0.6.16). **Exactly 8 bytes tolerated, the 9th breaks it.**
- Isolated the 9th byte specifically: flipping ONLY offset 26 (frame 0's
  padding, the byte that turns a passing 8-byte edit into a failing
  9-byte one when added) from 0 to 1, with offsets 18-25 left untouched,
  rendered correctly -- not the fallback. So offset 26 is not itself a
  meaningfully-checked field; the failure at 9 bytes was purely about
  *how many* bytes were touched in total, not *which* byte.

### Changed
- Confirms the 0.6.16 "magnitude threshold" reading over the "hidden
  structured field" alternative: if there were a real field starting
  around offset 26, flipping it alone should have broken something. It
  didn't. The padding region genuinely tolerates a small, fixed number of
  changed bytes (8) regardless of which bytes they are, and rejects more
  than that -- a count-based check, not a positional one.

### Known gaps
- Whether the count that matters is "bytes changed from the original
  all-zero state" or something more specific (e.g. "bytes with a specific
  bit pattern") is untested -- all tests here used non-zero-from-zero
  changes only.
- Whether 8 is specific to this frame/region or a broader constant
  (e.g. shared with some other part of the format) is unknown.
- Whether this generalizes to frame 1 (raw-bitmap mode) is untested.
- Same open items otherwise: sub-header byte [13], dithering algorithm,
  `mode_flag`, delay field's unit, `save_to_gif_2` inefficiency.

## [0.6.16] - 2026-07-30

**"Save to GIF": the 528-byte prefix's zero padding is NOT inert -- it's
validated, and the tolerance boundary sits between 5 and 10 bytes.** First
active test of this previously totally opaque region, on `save_to_gif_13`'s
simplest frame (frame 0, solid red, RLE mode).

### Verified
- Frame 0's zero-padding region (bytes 18-527 of its 528-byte prefix, all
  zero in the original capture) was overwritten with non-zero patterns of
  increasing size, `crc16_modbus` recomputed correctly each time, all 79
  packets acked every time:
  - 200 bytes non-zero: fallback.
  - 20 bytes: fallback.
  - 10 bytes: fallback.
  - 5 bytes: **real content, not fallback.**
  - 1 byte (offset 18 flipped 0->1): **real content, not fallback.**
- This rules out "must be strictly all-zero, zero tolerance" (1 and 5
  non-zero bytes were both accepted) AND rules out "genuinely unused,
  ignored padding" (10+ non-zero bytes reliably triggers the fallback).
  Something checks this region, and it has real tolerance, not an
  exact-match requirement.
- Restores this round needed a retry twice (same known flaky-redraw
  behavior as every prior round); every upload itself acked cleanly.

### Changed
- The prefix's zero region behaves differently in character from the
  content region's transition/run-structure tolerance (0.6.11-0.6.15):
  content-region within-region edits passed at ANY size tested (up to
  3200 bytes), while here even a fairly arbitrary 10-byte pattern already
  fails. This looks more like a literal magnitude/length threshold
  specific to this region than a structural check -- though it's also
  possible the boundary (somewhere in bytes 23-28, i.e. offset 18+5 to
  18+10) marks the start of a real, still-unidentified structured field
  that happens to read as zero in every simple capture seen so far, rather
  than a tolerance-based check on otherwise-free padding.

### Known gaps
- The exact byte where the boundary sits (between offset 23 and 28) is
  not pinned down -- worth a tighter bisection.
- Whether the boundary is a true magnitude threshold or the edge of a
  real structured field is unresolved; testing with a structured pattern
  (e.g. a plausible checksum, a copy of a known-good value) instead of an
  arbitrary byte sequence at ~7-8 bytes might help distinguish.
- Whether this generalizes to frame 1 (raw-bitmap mode) or is specific to
  frame 0's RLE mode is untested.
- Same open items otherwise: sub-header byte [13], dithering algorithm,
  `mode_flag`, delay field's unit, `save_to_gif_2` inefficiency.

## [0.6.15] - 2026-07-30

**"Save to GIF": a 3-pixel-wide boundary shift also passes, further
confirming the transition/run-structure reading over "only exactly
1-pixel adjacent swaps work."**

### Verified
- A symmetric 3-pixel-wide block swap centered on the gray/dark-red
  boundary (columns 103-105 swapped with 106-108 on row 0 -- moving the
  transition point by 3 columns as a single clean shift, not scattered
  anomalies) rendered correctly, not the fallback. All 79 packets acked.
- Restore acked cleanly and took immediately, no retry needed this time.

### Changed
- Extends the boundary tolerance beyond exactly-adjacent 1-pixel swaps:
  a small symmetric shift of the transition point is also accepted. 14
  hardware data points now fit the transition/run-structure reading
  without exception: edits that move an existing transition by a small
  amount, or that stay entirely within one region regardless of size,
  pass; edits that create a brand-new isolated anomaly with mismatched
  neighbors on both sides fail, regardless of how few bytes are touched.

### Known gaps
- How far a boundary shift can move before it starts failing (3 columns
  passes; unknown upper bound) is untested.
- Same open items as 0.6.14 otherwise (528-byte prefix, sub-header byte
  [13], dithering algorithm, `mode_flag`, delay field's unit, `save_to_gif_2`
  inefficiency).

## [0.6.14] - 2026-07-30

**"Save to GIF": both stripe boundaries tolerate adjacent-pixel swaps,
pointing at a transition/run-structure check rather than raw region
membership; the TOC delay field is confirmed, not just plausible.**

### Verified
- A swap 5 columns into the gray stripe's interior (column 100) with the
  dark-red boundary pixel (column 106) -- crossing regions but NOT
  adjacent -- fell back, same as every other non-adjacent cross-region
  test so far.
- A swap of the OTHER stripe boundary -- columns 211 (last dark-red pixel)
  and 212 (first red pixel), adjacent -- rendered correctly, not the
  fallback. Second independent boundary-swap success, ruling out
  "something specific to the gray/dark-red transition" as the explanation
  for 0.6.13's result.
- The TOC-level delay field (`[16:18]`, previously "50 in every capture,
  plausibly a delay, unit unconfirmed") is now genuinely confirmed: the
  user explicitly set the frame speed to 50 in the Windows app when
  generating `save_to_gif_13.pcapng`, and the wire value is literally 50.
  Not a coincidental shared default -- a real, user-controlled field.

### Changed
- The full boundary-swap picture (2 adjacent cross-region successes at
  both stripe transitions, 1 non-adjacent cross-region failure just past
  one of them, 6 earlier non-adjacent cross-region failures, 3 within-region
  successes at various sizes) now fits a single clean account: what fails
  is creating a brand-new isolated anomaly -- a foreign-colored pixel with
  mismatched neighbors on both sides, which is what every non-adjacent
  cross-region edit does. An adjacent swap across a boundary just shifts
  an ALREADY-EXISTING transition by one pixel rather than creating a new
  one, and a within-region edit of any size never introduces a foreign
  value at all. Reading this as a check on each row's transition/run
  structure (not raw per-column palette membership) now explains all 13
  hardware data points from this investigation without exception.
- Unit for the delay field still not pinned down (likely centiseconds by
  GIF convention, i.e. 50 = 0.5s), since every capture used the same
  speed setting so far -- would need a capture with a different value to
  confirm the scale factor.

### Known gaps
- The transition/run-structure reading is now well-supported (13/13 data
  points) but still not a decoded algorithm -- what exactly counts as an
  acceptable transition, and whether there's a limit on transitions per
  row in general (independent of these experiments), is unknown.
- Same open items otherwise: the 528-byte prefix, sub-header byte [13],
  the dithering algorithm, `mode_flag`, delay field's unit,
  `save_to_gif_2`'s inefficiency.

## [0.6.13] - 2026-07-30

**"Save to GIF": a swap exactly AT the stripe boundary passed, contradicting
the strict per-region reading from 0.6.11/0.6.12.** Complicates, rather than
confirms, last round's "clean" conclusion -- genuinely open again.

### Verified
- Swapped columns 105 (last light-gray pixel) and 106 (first dark-red
  pixel) on row 0 -- a single-pixel-pair edit straddling the visual stripe
  boundary exactly, moving a gray-family flag into the dark-red column and
  vice versa. By every prior cross-region result (0.6.10, 0.6.11: 6/6
  failures at various interior positions and sizes), this should fail.
  Instead: all 79 packets acked and the panel rendered the normal content
  (3-stripe frame alternating with the solid-red reference frame), not the
  fallback.
- Restoring the original blob after this test needed one retry (the usual
  flaky-redraw behavior, not a new issue) -- confirmed back to normal
  after the retry, including the expected solid-red/3-stripe alternation.

### Changed
- The strict "every pixel's flag must belong to its column's stripe, no
  exceptions" reading from 0.6.11/0.6.12 is too strong: it predicted this
  boundary swap should fail, and it didn't. Whatever the real invariant is,
  it tolerates -- or doesn't apply the same way to -- edits exactly at a
  stripe transition, unlike edits deep inside a stripe's interior (which
  have failed 100% of the time, from 1 pixel to 1600 pixels/side). A
  transition-count or run-structure explanation (the boundary swap adds a
  small extra wiggle at an already-existing transition, vs. interior
  edits which create a brand-new isolated anomaly with two new
  transitions where none existed) is a plausible refinement, not yet
  tested against a case designed to separate it from the simpler
  "boundary pixels are special" reading.
- Human-verification note for future rounds: distinguishing "correct
  content with a 1-2px change" from "correct content, no change" by eye is
  unreliable given the GIF alternates between this frame and a full solid-
  red reference frame -- the flicker makes fine pixel-level confirmation
  impractical. The reliable signal these experiments actually depend on is
  coarser and unaffected by this: fallback animation (visibly different
  content) vs. real content (whichever frame, modified or not) is easy to
  tell apart on sight, and that's the distinction every pass/fail
  conclusion in this investigation is actually built on.

### Known gaps
- Whether "boundary-adjacent" edits pass in general, or whether this
  specific position was special, is untested -- worth trying a swap a few
  columns off the boundary (e.g. column 100 <-> 106) to see if there's a
  tolerance zone near transitions or a hard line right at column 105/106.
  Also worth an OFF-boundary interior swap between two stripes' extreme
  edges without crossing (e.g. column 104 <-> 105, both still gray) as a
  control.
- Same open items as 0.6.12 otherwise.

## [0.6.12] - 2026-07-30

**"Save to GIF": a large within-region swap renders correctly, closing
0.6.11's biggest open gap.** The per-region flag-membership hypothesis now
holds across the full size range tested, from 2 bytes to 3200.

### Verified
- Two 40x40 blocks, both entirely within `save_to_gif_13`'s light-gray
  stripe (columns 10-49 and 60-99, same size as 0.6.10's failed
  cross-stripe 40x40 swap), were swapped with each other. All 79 packets
  acked, and the panel rendered the normal, correct 3-stripe animation --
  confirmed by a user photo showing a clean light-gray / dark-red / red
  layout with no fallback. This is the same edit size that failed every
  time it crossed a stripe boundary (0.6.10, 0.6.11), now succeeding
  because both sides stayed within the gray stripe's own flag set.
- Restoring the original blob needed one retry before the panel visibly
  redrew (same flaky-redraw behavior as every prior round; the retry
  fixed it immediately, and every upload itself acked cleanly both times).

### Changed
- Confirms the per-region flag-membership reading from 0.6.11 is not
  merely a small-edit-size artifact: within-region edits now pass at 2
  bytes changed (0.6.10, 0.6.11) AND at 3200 bytes changed (this round),
  while cross-region edits fail at every tested size from 2 to 3200 bytes
  (0.6.10, 0.6.11). Edit size appears to genuinely not matter once the
  region-membership constraint is satisfied.

### Known gaps
- Still untested: whether the boundary is truly per contiguous stripe or
  something finer/coarser (e.g. per exact column) that happens to align
  with the 3 stripes here.
- The underlying mechanism is still a hypothesis pattern-matched across 9
  data points (3 within-region successes at sizes 2/2/3200 bytes, 6
  cross-region failures at sizes 2-3200 bytes), not a decoded algorithm.
- Same open items as 0.6.11 otherwise (528-byte prefix, sub-header byte
  [13], dithering algorithm, `mode_flag`, `save_to_gif_2` inefficiency).

## [0.6.11] - 2026-07-30

**"Save to GIF": the content validator isn't a magnitude threshold -- it's
per-region flag membership.** Bisection of 0.6.10's pass/fail boundary
overturns that round's leading hypothesis and replaces it with a cleaner,
fully-explanatory one.

### Verified
- Cross-stripe block swaps (same gray<->red swap type as 0.6.10, between
  `save_to_gif_13`'s light-gray and red stripes) at decreasing sizes: 8x8
  (128 total differing positions), 4x4 (32), 2x2 (8), and 1x1 (2) --
  **every single one fell back**, all the way down to a single pixel pair.
- A 1x1 cross-stripe swap (2 total differing positions -- the exact same
  byte count as 0.6.10's successful within-stripe swap) still fell back.
  This directly refutes 0.6.10's "scale/magnitude threshold" hypothesis:
  byte count alone cannot be the deciding factor, since 2 bytes changed
  produced opposite outcomes depending on *what* was swapped.
- A same-region swap in the DARK-RED stripe (columns 106-107, values 2 and
  3 -- both native to that stripe, the same kind of edit as 0.6.10's
  successful gray-stripe swap but in a different region and a different
  flag pair) rendered correctly, not the fallback. Second independent
  confirmation that within-region swaps pass.
- All restores this round acked cleanly every time; one needed a retry
  before the panel visibly redrew (same known flaky-redraw behavior as
  0.6.10, not a new issue).

### Changed
- Retracts the "scale/magnitude-based validation" hypothesis from 0.6.10.
  The real pattern across all data so far: edits that keep every pixel
  within its own stripe's already-established flag set (gray stripe:
  {0,1,5,6,7,8,9,10}; dark-red stripe: {2,3}; red stripe: {4}) pass,
  regardless of how many pixels are touched (a within-region swap of 2
  bytes passes the same as, presumably, a larger one would). Edits that
  put a flag value into a column range where it doesn't already belong --
  even a single pixel -- fail, regardless of how few bytes are touched.
  This is a per-region (likely per-column-range) flag-membership
  constraint, not a diff-size threshold.

### Known gaps
- Not yet tested: a within-region swap larger than 2 bytes (would confirm
  region-membership is sufficient on its own, independent of size, rather
  than "small AND region-correct").
- Not yet tested: whether the boundary is truly per contiguous stripe, or
  something coarser/finer (e.g. per exact column, or per some other
  partition that happens to align with the 3 stripes here).
- The underlying mechanism is still a hypothesis, not a decoded algorithm
  -- consistent with 6 cross-region failures and 2 within-region successes
  so far, not yet stress-tested against a case designed to break it.
- Same open items as 0.6.10 otherwise (528-byte prefix, sub-header byte
  [13], dithering algorithm, `mode_flag`, `save_to_gif_2` inefficiency).

## [0.6.10] - 2026-07-30

**"Save to GIF": first hardware-confirmed edit of the raw-bitmap format --
a single-pixel swap rendered correctly, a block swap didn't.** Directly
follows 0.6.9's two failed edits; narrows down what the panel's content
validator actually cares about.

### Verified
- A single adjacent-pixel swap (row 0, columns 2 and 3, values 0 and 1
  exchanged -- the smallest possible edit) was uploaded with `crc16_modbus`
  recomputed correctly. All 79 packets acked, and the panel rendered the
  normal 3-stripe animation **with the intended pixel visibly changed** --
  confirmed by the user. This is the first genuine hardware proof that the
  raw-bitmap byte-layout reading (0.6.7) is not just the best fit for the
  static evidence, but the panel's actual internal representation: editing
  one byte at a known position produced exactly the predicted one-pixel
  visual change.
- A second experiment -- swapping two whole 40x40 blocks between the
  gray and red stripes (same size, so a pure permutation: every flag's
  total pixel count across the frame is exactly unchanged, unlike 0.6.9's
  overwrite) -- still fell back. Same acked/checksum-correct-but-rejected
  pattern as every larger edit so far.
- Restoring the original blob after the block-swap experiment needed two
  retries before the panel actually redrew the pristine content (the first
  retry's re-upload acked cleanly but the panel kept showing the swapped
  render). This matches the flaky-restore behavior already documented in
  the 0.5.x era exactly, just needing one more retry than that case did.

### Changed
- Rules out "preserves the frame's aggregate flag histogram" as the
  validator's criterion: the failed block swap preserves it exactly, same
  as the successful pixel swap, so histogram preservation alone can't be
  what separates the two outcomes.
- The successful/failed pair (2 bytes changed -> fine; 1600 bytes changed,
  same permutation type -> fallback) points toward a scale- or
  magnitude-based check -- how much of the frame differs from some
  reference, not what statistical properties the difference has -- though
  the exact threshold and mechanism are still unknown.

### Known gaps
- Where the pass/fail boundary sits between "2 bytes changed" and "1600
  bytes changed" is unmapped -- worth bisecting in a future round.
- The validator's real mechanism is still unidentified; this only narrows
  the hypothesis space.
- Same open items as 0.6.9 otherwise.

## [0.6.9] - 2026-07-30

**"Save to GIF": first hardware test of the raw-bitmap model failed to the
fallback animation -- inconclusive, not a refutation.** The panel is
connected, so the 0.6.7 raw-bitmap reading got its first real hardware
check: a 40x40-pixel block in `save_to_gif_13`'s light-gray stripe was
overwritten with an existing, valid palette flag (4, the frame's own clean
red), `crc16_modbus` was recomputed correctly over the modified payload and
written into both TOC entries, and the modified blob was packetized with
`build_upload()` (same length as the real capture, so no new `CRC_INIT`
entry was needed) and uploaded.

### Verified
- All 79 packets acked -- the wire transfer and TOC-level `crc16_modbus`
  were structurally valid.
- The panel showed the fallback animation instead of the edited stripe.
  Re-uploading the original, unmodified blob (same procedure) restored the
  correct 3-stripe animation; user confirmed. The panel was not damaged.
- The full 528-byte prefix was re-checked byte-by-byte (not just the first
  80 bytes as before) for both frames: no hidden nonzero region exists
  anywhere in it beyond the already-decoded header fields. There is no
  room for an undiscovered per-frame content checksum -- frame 1's raw
  bitmap content runs from byte 528 to the frame's exact end (size32),
  with nothing trailing it either.

### Changed
- Nothing about the raw-bitmap structural reading is retracted: the static
  evidence for it (content length exactly 320x480, all bytes confined to
  the palette range, clean row-by-row stripe structure, measured
  per-channel duty cycles in the right range) is unaffected by this
  result, since ruled out is only a hidden checksum, not the byte-per-pixel
  layout itself.
- This result matches the established pattern from the 0.5.x-era RLE
  experiments: an ack'd, TOC-checksum-correct upload can still fail the
  panel's own undocumented content validation and fall back, for reasons
  never fully reverse-engineered even after many RLE-mode attempts back
  then. That opacity apparently isn't specific to the RLE format --  it
  now shows up in the raw-bitmap format too.

### Known gaps
- What the panel's content validator actually checks is still unknown for
  both formats. A large uniform block using an existing valid flag was not
  enough to satisfy it here, same as most non-trivial RLE edits weren't
  enough back in 0.5.x -- whatever passes validation seems to be a narrow,
  structurally-specific class of edit, not "any internally-consistent
  content."
- Same open items as 0.6.8 otherwise.

## [0.6.8] - 2026-07-30

**"Save to GIF": the 8-slot dither palette decomposes into 3 independent
per-channel ditherers, and the pattern looks like error diffusion, not a
fixed matrix.** Follow-up to 0.6.7, same capture, no new hardware.

### Verified
- The 8 combo flags split cleanly along 3 independent per-channel bits: R
  is hi(206) for flags {0,1,8,10}, lo(156) for {5,6,7,9}; B is hi(206) for
  {0,1,7,9}, lo(156) for {5,6,8,10}; G is hi(215) for {0,5,8,9}, lo(170)
  for {1,6,7,10}.
- Measured over all 50880 gray-stripe pixels: R is lo 8.56% of the time, B
  is lo 8.50%, G is lo 31.25% -- in the same range as the duty cycle each
  channel alone would need under naive linear interpolation to average to
  the 200 target (12.0% for R/B, 33.3% for G).
- Per-row minor-flag counts are bursty, not periodic: rows 0-2 have zero,
  row 3 has 25, row 4 has 1, row 6 has 31 (checked the first 40 of 480
  rows) -- no fixed spacing.

### Changed
- The 8-slot palette is better understood as a precomputed enumeration of
  all 8 outcomes of 3 separate, independent single-channel ditherers (each
  choosing hi/lo on its own), not evidence of an inherently 3-dimensional
  dithering algorithm -- the 8 RGB565 corners exist because RGB565 can't
  express "this channel alone is dithered" as anything but a fully
  specified color.
- The burstiness argues for error diffusion (or another history-dependent
  scheme) over a fixed spatial Bayer/ordered-dither matrix, which would be
  expected to spread corrections evenly across rows.

### Known gaps
- The actual per-channel algorithm (error diffusion direction/coefficients,
  or something else entirely) is not identified -- duty cycles and
  burstiness are consistent with error diffusion, not proof of it.
- Same open items as 0.6.7 otherwise: the 528-byte prefix, one
  unidentified sub-header byte, whether `mode_flag` generally selects
  RLE-vs-raw, `save_to_gif_2`'s inefficiency, `0x04200000`, no
  `--target gif`.
- Still no hardware mutation this round -- static re-analysis only.

## [0.6.7] - 2026-07-30

**"Save to GIF": `save_to_gif_13`'s complex dithered frame is NOT
RLE-encoded -- it's a raw, uncompressed 1-byte-per-pixel palette-indexed
bitmap.** Resolves the 0.6.5/0.6.6 "token layout unmapped" gap: the flat
`(length, flag)` RLE model wasn't slightly off, it was the wrong model
entirely for this frame.

### Verified
- Frame 2's content region is exactly 153600 bytes == 320x480, and every
  byte in it is one of only 11 distinct values (0-10, the palette range),
  with zero exceptions across the full region. Read as 1 byte = 1 pixel in
  raster order, it decodes perfectly: no leftover bytes, no overshoot.
- Row structure confirmed identical at every row checked: 3 vertical
  stripes at columns [0:106) light gray, [106:212) dark red, [212:320)
  red (106/106/108 px). Red stripe is uniformly one flag (undithered).
  Dark-red stripe is a perfect alternating 2-slot pattern, literally every
  pixel -- the simple pair dither confirmed at pixel granularity for the
  first time (previously only inferred from aggregate pixel/token counts).
  Light-gray stripe's dominant pattern is a repeating 4-pixel
  `(flag0,flag0,flag0,flag1)` tile -- flag0 and flag1 share R and B
  (both 206), differing only in G (215 vs. 170), so this tile is a 3:1
  duty-cycle dither on the G channel alone.

### Changed
- Explains why the 8-slot per-channel scheme exists where a 2-slot pair
  (used for dark red here, and gray in `save_to_gif_10`/`11`/`12`) doesn't:
  a true per-channel independent ordered dither needs many more than 2
  achievable colors, and representing that via RLE tokens would be
  pathological (runs collapsing to 1 pixel, doubling the byte cost vs. a
  raw index) -- so past some complexity threshold the encoder appears to
  switch formats rather than emit degenerate RLE.
- The solid-red reference frame in the same capture (still RLE,
  `mode_flag=0x0100`) vs. this raw-bitmap frame (`mode_flag=0x0002`) is a
  plausible RLE-vs-raw format selector, consistent but not yet proven with
  only one example of each.

### Known gaps
- 475 of 480 rows substitute one of the other 6 combo flags
  (5,6,7,8,9,10) at scattered positions in the light-gray stripe, on top
  of the base 4-pixel tile -- a real 2D ordered/Bayer dither matrix looks
  likely, but the row-to-row substitution rule isn't mapped.
- Whether `mode_flag` generally selects RLE vs. raw bitmap (vs. some other
  meaning) needs more than one data point per mode to confirm.
- Same open items as before: the 528-byte prefix's contents/purpose, one
  unidentified sub-header byte, `save_to_gif_2`'s encoding inefficiency,
  `0x04200000`, no `--target gif`.
- No hardware mutation was attempted -- this round was static
  re-analysis of the existing capture, even though the panel is currently
  connected.

## [0.6.6] - 2026-07-29

**"Save to GIF": `save_to_gif_13`'s palette re-analyzed offline (no
hardware) -- its two dithered colors use two DIFFERENT schemes, not a
shared combinatorial one.** Follow-up to 0.6.5, working from the same
capture rather than new hardware data.

### Verified
- `save_to_gif_13`'s frame 2 has 11 populated palette slots: 1 clean
  (undithered) red reference stripe, 2 slots forming dark red's dither
  pair (as expected from the established simple 2-slot pattern), and 8
  slots for light gray -- confirmed to be the *exhaustive* set of all
  2x2x2 combinations of three independently-quantized channels (R in
  {156,206}, G in {170,215}, B in {156,206}), not a second 2-slot pair and
  not combinations shared with dark red's pair.
- Content region boundary re-confirmed algebraically for this frame too:
  `size32 - 528` matches the (overflowing) 16-bit content-length field
  exactly, consistent with every earlier capture's fixed 528-byte prefix.

### Changed
- Refines the 0.6.5 "combinations of the component brightness levels from
  both dithered targets" guess: the two dithered colors don't share or mix
  slots. Each gets its own independent scheme, and which scheme a color
  gets (2-slot pair vs. 8-slot per-channel grid) is not yet understood --
  dark red here and gray in `save_to_gif_10`/`11`/`12` both use the simple
  2-slot form, so it isn't simply chromatic-vs-achromatic.

### Known gaps
- The token/byte grammar for either dither scheme is still undecoded.
  Decoding flat `(length-1, flag)` pairs from content-start (528 bytes
  into the frame) never lands the running pixel total on exactly 153600
  (320x480) -- it jumps from 153598 to 153602 at the token that should
  close the frame. A "two independent full-frame passes" hypothesis (base
  layer + dither mask) was tested and ruled out the same way. The flat
  2-byte-token grammar confirmed for every 2-slot-or-simpler capture may
  not be the right model once an 8-slot color is involved.
- Why light gray (200,200,200) needs the richer 8-slot scheme when a
  coarser 2-slot pair sufficed for the earlier 128-gray is unexplained.
- Same open items as 0.6.5: the 528-byte prefix's contents/purpose, one
  unidentified sub-header byte, `save_to_gif_2`'s encoding inefficiency,
  `0x04200000`, no `--target gif`.
- The touchscreen panel is connected to this machine as of this analysis,
  but no hardware mutation was attempted this round -- the next step needs
  a sharper hypothesis about the token grammar before spending a physical
  test on it.

## [0.6.5] - 2026-07-29

**"Save to GIF": found the dithering trigger rule, and fixed a real bug in
how `CRC_INIT` is keyed.** Two more captures -- black/orange (`gif_12`) and
light gray/dark red (`gif_13`) -- refute the earlier "corner" theory and
nail down when a color dithers instead of getting a direct palette slot.
Regression-checking these against all prior captures also exposed a
length-collision bug in `CRC_INIT` that had been silently wrong for two
existing entries.

### Verified
- `save_to_gif_12.pcapng` (solid black background, orange stripe): both
  colors get clean direct palette slots -- refutes the earlier "colors at
  the 8 RGB565 gamut corners dither" theory, since orange is nowhere near a
  corner and still didn't dither.
- `save_to_gif_13.pcapng` (light gray, dark red): light gray dithers, dark
  red does not. Combined with all prior data, 12/12 tested colors are now
  exceptionless under a single rule: a color gets a direct palette slot iff
  `max(R, G, B)` is exactly 0 or 255; anything whose brightest channel is
  strictly between 0 and 255 dithers, regardless of the other channels.
- Rendered correctly on the physical panel, confirmed by the user.

### Fixed
- **`CRC_INIT` was keyed by the `cmd` byte from `final_chunk_cmd()`, which
  is wrong: `cmd = (CMD_WRITE + payload_len) % 256` is many-to-one, so two
  different lengths can collide on the same `cmd` and legitimately need
  different CRC inits.** The standard regression check caught this directly:
  `gif_12`'s 1080-byte final chunk collides on `cmd=0x3F` with `gif_10`/`11`'s
  312-byte chunk (inits `0x9E2E` vs. `0x922E`), and `gif_13`'s 248-byte final
  chunk collides on `cmd=0xFF` with `gif_8`'s 2040-byte chunk (inits
  `0x522F` vs. `0xD9D1`). A cmd-keyed dict silently returned the wrong init
  for the second capture in each pair. Fixed by re-keying `CRC_INIT` by the
  actual payload length instead, and changing `crc16_packet()` to derive
  `payload_len` from the body's own size rather than trusting a
  caller-supplied `cmd`. All 15 known captures re-verified byte-for-byte
  after the fix, including both collision pairs.

### Known gaps
- The exact byte layout when multiple colors dither simultaneously in one
  frame (`gif_13`'s case) isn't mapped to a specific rule yet.
- The 528-byte prefix's actual contents/purpose are still unknown.
- One sub-header byte ([13]) remains unidentified.
- `save_to_gif_2`'s solid frames still encode far less efficiently than
  `save_to_gif_3`/`4`/`5`'s, unexplained.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.
- Still no `--target gif`.

## [0.6.4] - 2026-07-29

**"Save to GIF": dithering confirmed color-specific, not a slot-order
limit.** An eleventh capture -- the same 8 colors as 0.6.3, reordered so
gray is first instead of last -- is the decisive control experiment.

### Verified
- Gray still dithers, now using palette slots 0-1 instead of 7-8, with the
  **exact same pair** as 0.6.3 -- `[16:18]`=`0x640C`, `[18:20]`=`0x9C13`,
  byte-identical to `save_to_gif_10`.
- Every other color, including white (now in gray's old last position),
  gets a clean direct palette slot. The content's dither-token run moves
  correspondingly to the start of the frame instead of the end.
- All 25 packets reproduce byte-for-byte against the existing `0x3F`
  `CRC_INIT` entry -- same final-chunk length as `save_to_gif_10`, not a
  new data point.

### Changed
- **Rules out "7-slot capacity, first come first served" conclusively.**
  It was never about position or order: the encoder maps this specific
  gray to this specific dither pair deterministically, independent of what
  else is in the frame or which slot it would otherwise occupy.

### Known gaps
- Exactly which *other* colors (besides this one gray) trigger dithering
  is still untested -- confirmed color-specific and deterministic, but the
  actual boundary (luminance? saturation? something else?) is unmapped.
- The 528-byte prefix's actual contents/purpose are still unknown.
- One sub-header byte ([13]) remains unidentified.
- `save_to_gif_2`'s solid frames still encode far less efficiently than
  `save_to_gif_3`/`4`/`5`'s, unexplained.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.
- Still no `--target gif`.

## [0.6.3] - 2026-07-29

**"Save to GIF": found the palette's real limit -- dithering, confirmed
visually.** A tenth capture -- eight distinct-colored vertical stripes, one
more than 0.6.1's four-color test, adding gray -- finds where the palette
mechanism actually breaks down, and it's more interesting than a simple
slot-count cutoff.

### Verified
- Only 7 of the 8 colors get an exact palette slot (red, green, blue,
  yellow, magenta, cyan, white -- all byte-exact RGB565 at `[16:18]`
  through `[28:30]`). Gray never appears in the sub-header.
- Instead, gray's stripe is 40 alternating 1-pixel tokens referencing two
  *new* palette slots (`[30:32]`, `[32:34]`) that decode to RGB
  `(96,128,96)` and `(152,128,152)` -- averaging to `(124,128,124)`, almost
  exactly the target gray, `(128,128,128)`.
- **Confirmed visually, not just from the bytes**: the user reported the
  gray stripe looked textured/dithered on the real panel, not smooth. The
  encoder dithers colors it can't represent directly by alternating two
  nearby palette entries pixel-by-pixel, rather than giving every distinct
  source color its own slot.
- The 528-byte prefix is still exactly 528 bytes with 9 total palette slots
  in play (7 real + 2 dither-pair).
- 12th `cmd`/`CRC_INIT` data point: a 312-byte final chunk predicted
  `cmd=0x3F` before checking, confirmed exact; its CRC init (`0x922E`)
  solved and added to `CRC_INIT`.

### Changed
- Reframes the "how many palette colors" question from 0.6.1: it's not
  simply "8 colors and no more" -- it's a deeper constraint on which
  *specific* colors qualify for a direct slot. Seven saturated primaries
  (including white) were all fine; one mid-tone gray triggered dithering
  instead of getting an 8th slot.

### Known gaps
- Exactly which colors trigger dithering vs. get a direct slot is
  untested beyond this one data point.
- The 528-byte prefix's actual contents/purpose are still unknown.
- One sub-header byte ([13]) remains unidentified.
- `save_to_gif_2`'s solid frames still encode far less efficiently than
  `save_to_gif_3`/`4`/`5`'s, unexplained.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.
- Still no `--target gif`.

## [0.6.2] - 2026-07-29

**"Save to GIF": continuous-RLE model confirmed at high density.** A ninth
capture -- a black background with a white 1px grid every 32px, frame 2
the same grid shifted 1px left and down -- stress-tests the model from
0.6.0/0.6.1 against much denser, higher-token-count content than any prior
capture, and it holds up completely. Mostly a strong confirmation round;
no new structural surprises.

### Verified
- 9315 tokens per frame (vs. hundreds in every prior capture), mostly tiny
  1px and 31px runs from the grid lines and cells. Pixels sum to exactly
  153600 in both frames.
- The 528-byte prefix is still exactly 528 bytes even at this density,
  reinforcing 0.6.1's finding that its size doesn't depend on content
  complexity.
- The two frames' token streams are structurally identical (same 9315-token
  shape, same length histogram) but start from opposite flag/color
  assignments -- each frame independently derives flag 0 from whatever
  color its own first pixel happens to be ((0,0) is white in frame 1, on
  both a horizontal and vertical line; black in frame 2, since the 1px
  shift moves both lines off that pixel). One more confirmation that
  frames are encoded fully independently, not as deltas against each other
  (0.5.14/0.6.0).
- 11th `cmd`/`CRC_INIT` data point: a 1492-byte final chunk predicted
  `cmd=0xDB` before checking, confirmed exact; its CRC init (`0x1E90`)
  solved and added to `CRC_INIT`.

### Known gaps
- The 528-byte prefix's actual contents/purpose are still unknown.
- One sub-header byte ([13]) remains unidentified.
- How many palette slots the format actually supports is untested beyond 4.
- `save_to_gif_2`'s solid frames still encode far less efficiently than
  `save_to_gif_3`/`4`/`5`'s, unexplained.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.
- Still no `--target gif`.

## [0.6.1] - 2026-07-29

**"Save to GIF": palette confirmed beyond 2 colors, 528-byte prefix ruled
out as a color table.** An eighth capture -- four distinct-colored vertical
stripes (red, green, blue, yellow, 80px each) -- answers two open questions
from 0.6.0 in a single test.

### Verified
- **The palette isn't fixed at 2 colors.** This frame's sub-header carries
  four populated RGB565 slots -- `[16:18]`=red, `[18:20]`=green,
  `[20:22]`=blue, `[22:24]`=yellow -- exactly the four stripe colors, in
  order. `flag` is a genuine multi-value palette index (values 0-3
  confirmed), not the binary 0/1 seen in every earlier 2-color capture.
- `[20:22]` is palette slot 2, not the mysterious "color variant" field
  guessed at in 0.5.5 -- that reading only looked plausible because every
  capture before this one used at most 2 colors.
- **The 528-byte prefix is still exactly 528 bytes with 4 colors in play**,
  ruling out "a palette/quantization table that scales with color count"
  as its purpose.
- The frame's content is the clean "no merge" case of the continuous-RLE
  model from 0.6.0: 1920 tokens, uniformly `(80,flag0)/(80,flag1)/
  (80,flag2)/(80,flag3)` x 480, summing to 153600 pixels. Row boundaries
  here always land on a color change (yellow -> red), so nothing merges
  across them -- same grammar as 0.6.0, just not the boundary-merge case.
- 10th `cmd`/`CRC_INIT` data point: a 2040-byte final chunk predicted
  `cmd=0xFF` before checking, confirmed exact; its CRC init (`0xD9D1`)
  solved and added to `CRC_INIT`.

### Known gaps
- The 528-byte prefix's actual contents/purpose are still unknown (now
  confirmed *not* a color table).
- One sub-header byte ([13]) remains unidentified.
- How many palette slots the format actually supports is untested beyond 4.
- `save_to_gif_2`'s solid frames still encode far less efficiently than
  `save_to_gif_3`/`4`/`5`'s, unexplained.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.
- Still no `--target gif`.

## [0.6.0] - 2026-07-29

**"Save to GIF" row-grammar SOLVED: it's a continuous, row-boundary-
crossing run-length encoding.** A seventh capture -- a real red/blue/red
vertical triple stripe, same proportions as the hand-built 3-run row test
that failed in 0.5.9 -- supplies the missing piece and replaces every
row-token theory from the last several rounds with one complete, simple
model. Minor version bump: this is the most significant resolution of the
GIF investigation to date, even though `--target gif` still doesn't exist.

### Verified
- The frame's pixels are walked in **raster order as one continuous
  sequence** -- not reset or re-paired at row boundaries. The stripe
  frame's content decodes to exactly 961 `(length, flag)` tokens summing to
  153600 (320x480) pixels: `(100,flag0)`, then `(120,flag1),(200,flag0)`
  repeated 479 times, then a final `(100,flag0)`. That is exactly what a
  row's trailing red run merging with the next row's leading red run (both
  100px, both red, visited back-to-back in raster order) predicts -- only
  the very first and very last red segments have nothing to merge with.
- Each token is `(length-1, flag)`, as established in 0.5.5/0.5.8. A run
  longer than 256px (the 1-byte length field's max) becomes multiple
  consecutive tokens sharing the SAME flag -- confirmed against the clean
  solid-red frame's 600x `(255, flag=0)` content: chained pieces of one
  giant run, not 600 independent runs.
- `flag` is the color index established in 0.5.10/0.5.11. It only changes
  when the actual color changes to a new run; chained continuation pieces
  of the same run keep the same flag.
- 9th `cmd`/`CRC_INIT` data point: a 122-byte final chunk predicted
  `cmd=0x81` before checking, confirmed exact; its CRC init (`0x13B0`)
  solved and added to `CRC_INIT`.

### Changed
- **This reconciles `save_to_gif_3`/`4`'s persistent, never-resetting flip**
  (open again as of 0.5.14/0.5.15): a solid-red image with one white pixel
  decodes as one tiny run (the white pixel) followed by one enormous red
  run (nearly the whole image), chained into hundreds of same-flag pieces
  just like the fully-solid case. The flag "staying flipped" was never a
  special persistent mode -- it's just many chained pieces of one giant run.
- Every row-token theory from 0.5.8 through 0.5.13 (2-tokens-per-row
  structure, per-row color-must-differ rule, frame-index/delta hypotheses)
  is superseded by this single continuous-RLE model, which fits all of that
  evidence at once without needing separate rules for each observation.

### Known gaps
- The fixed 528-byte prefix's actual contents/purpose are still unknown.
- A couple of sub-header bytes ([13], [20:22]) remain unidentified.
- Whether more than 2 palette colors is possible is untested.
- `save_to_gif_2`'s solid frames encode far less efficiently (4151 varied
  tokens) than `save_to_gif_3`/`4`/`5`'s clean 600 uniform tokens for the
  same 153600-pixel solid color -- possibly that source image wasn't
  perfectly flat, not investigated.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.
- Still no `--target gif`: even with the run-length grammar solved, safely
  constructing new content needs the 528-byte prefix decoded too.

## [0.5.15] - 2026-07-29

**"Save to GIF" research: padding confirmed as the cause of 0.5.13's
failure, by direct A/B test.** With the panel back on Linux, 0.5.13's
failed 3-frame experiment was re-sent using proper, unpadded packetization
instead of trailing zero-pad bytes.

### Verified
- Re-sent the exact same content that failed padded in 0.5.13's ninth
  experiment, this time as 3 full 2048-byte writes + the real 540-byte
  final chunk (`cmd 0x23`, solved in 0.5.14) + commit -- literally the same
  5 packets as `save_to_gif_6.pcapng`, byte-for-byte. Result: the full
  3-frame animation played correctly.
- Same bytes, only the packetization differed between this and 0.5.13's
  attempt. That is now a direct, confirmed A/B result, not inference from
  a separate capture: padding -- not frame index, not a delta requirement
  -- caused 0.5.13's failure, and by the same logic likely explains 0.5.12's
  eighth experiment too (identical technique).

### Changed
- **Padding's status is now known to be inconsistent, not simply unsafe.**
  0.5.9's padding-only control (padding the working 2-frame blob, nothing
  else changed) rendered correctly; this padded 3-frame content did not,
  despite the identical "round up to the next multiple of 2048" technique.
  Padding should not be trusted for further experiments -- prefer real
  captures or exact, unpadded packetization (solving the needed `CRC_INIT`
  entry from a genuine capture) instead.

### Known gaps
- 0.5.9's 3-stripe row-count experiment used the same padding technique and
  should be distrusted pending a re-test without it -- not yet done, since
  it needs a new `CRC_INIT` entry (for a 122-byte final chunk) that no
  capture has provided yet.
- `save_to_gif_3`/`4`'s persistent, never-resetting flip is unexplained
  again, with no replacement theory yet.
- The bulk of the entropy coding, and solid-color frames' unrelated byte
  structure, are otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.14] - 2026-07-29

**"Save to GIF" research: `save_to_gif_6.pcapng` overturns 0.5.12/0.5.13's
delta-encoding theory.** A sixth GIF capture -- a real, vendor-generated
3-frame animation (solid red, split, split again *unchanged*) built
specifically to see what "no visible change between frames" looks like --
answers that question directly and, in the process, reveals the actual
cause of two previous "failed" hardware experiments.

### Verified
- `save_to_gif_6.pcapng`'s frame 1 and frame 2 are **byte-for-byte
  identical**. The real encoder simply re-emits a frame's full content
  verbatim when nothing changes -- there is no delta or no-op token.
- Its frame 1 is also byte-identical to `save_to_gif_5`'s frame 1 (the same
  split, independently captured), confirming the encoder is deterministic
  and content-driven, not context- or position-dependent.
- 8th `cmd`/`CRC_INIT` data point: a 540-byte final chunk predicted
  `cmd=0x23` before checking, confirmed exact; its CRC init (`0xA9BB`)
  solved and added to `CRC_INIT`.
- Direct comparison: the hand-built 3-frame blob from 0.5.13's ninth
  experiment (built *before* this capture existed) is byte-for-byte
  identical in content to what `save_to_gif_6.pcapng` actually contains.
  The only difference was packetization -- the real capture ends in a
  genuine 540-byte final chunk, while the experiment padded the wire
  transfer to a round multiple of 2048 to avoid needing an unsolved CRC
  value. The user confirmed `save_to_gif_6`'s capture renders correctly on
  the panel.

### Changed
- **Overturns 0.5.12/0.5.13's delta/reference-frame hypothesis.** Since the
  content 0.5.13's ninth experiment sent was, byte-for-byte, exactly what a
  real capture proves renders correctly, the padding technique used in that
  experiment (and 0.5.12's eighth experiment, and 0.5.9's three-run row
  test) is the more likely cause of those failures, not frame index or a
  delta requirement. Pending direct re-test with the now-solved `0x23` CRC
  value (no padding needed) once hardware is available again.
- This removes the basis for reframing `save_to_gif_3`/`4`'s persistent,
  never-resetting flip as a one-time delta-mode switch (0.5.12). That
  observation still stands; its explanation is open again.

### Known gaps
- 0.5.9's three-run row-count experiment and 0.5.12's frame-slot-swap
  experiment both used the same padding technique and should be re-tested
  without it before trusting their conclusions either.
- `save_to_gif_3`/`4`'s persistent flip is unexplained again.
- The bulk of the entropy coding, and solid-color frames' unrelated byte
  structure, are otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.13] - 2026-07-29

**"Save to GIF" research, hardware round eight: 3-frame test is
inconclusive, but points toward a sequential delta.** One more experiment
against `save_to_gif_5`, extending it to 3 frames to test 0.5.12's
frame-index hypothesis more directly. The result doesn't cleanly confirm
or refute that hypothesis, but the reason why is itself informative.

### Verified
- Built a 3-frame blob: frame 0 solid red (unchanged), frame 1 the proven
  red/blue split (unchanged), frame 2 an exact byte-for-byte copy of frame
  1's content. Rebuilt the TOC as 3 entries (offsets, total-size,
  frame-count, checksum all recomputed) and padded the wire transfer to
  avoid needing an unverified CRC_INIT.
- Result: the fallback animation. Reverted afterward; confirmed restored.

### Changed
- **Identifies a confound in the test design, which refines the
  hypothesis.** If "any frame index other than 0 supports the row-grammar"
  were the whole story, frame 2 (an exact copy of frame 1's already-working
  content) should have rendered the same split. It didn't -- but if the
  row-grammar is a *sequential* delta (relative to the immediately
  preceding frame, not always frame 0), frame 2's bytes should describe the
  change from frame 1's state, not repeat frame 1's own delta-from-
  solid-red verbatim. Under that reading, this failure is evidence
  *against* "each frame deltas from frame 0" (which predicts reusing an
  already-valid delta twice should still work) and *for* a frame-to-frame
  sequential delta instead.
- This is inference from a negative result, not a confirmed mechanism --
  a real test of "does index 2 support row-grammar" would need frame 2 to
  encode a genuine delta (even a trivial "no change") from frame 1, which
  isn't attempted since the delta token grammar itself isn't decoded.

### Known gaps
- Whether row-grammar content works at frame index 2 (or any index beyond
  1) specifically is still untested in a way that isolates it from the
  delta-source confound above.
- The delta/reference-frame hypothesis from 0.5.12 remains unconfirmed.
- The bulk of the entropy coding is otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.12] - 2026-07-29

**"Save to GIF" research, hardware round seven: the row-grammar may be
tied to frame index, not content -- possible delta/reference-frame
scheme.** One more experiment against `save_to_gif_5`: swapping which
frame slot holds the row-grammar content, to test whether the encoding
choice depends on frame position rather than what's actually in the frame.

### Verified
- Frame 1's entire content (sub-header, 528-byte prefix, row data) was
  replaced with a byte-for-byte copy of frame 2's already-proven-working
  red/blue split. TOC's frame-2 offset, both entries' total-size field, and
  the `crc16_modbus` checksum were all updated to match the now-larger
  frame 1; wire transfer padded to avoid needing an unverified CRC_INIT.
- Result: the fallback animation -- the same failure signature as every
  invalid mutation tried so far, despite every byte in the new frame 1
  being bytes that render correctly when they're in frame 2's slot.
- Reverted afterward; confirmed restored.

### Changed
- **New leading hypothesis**: frame *index*, not frame *content*, selects
  which decode routine applies. Frame 0 requires the continuous-run
  encoding solid frames use; frame 1+ can use the row-grammar decoded in
  0.5.8-0.5.11.
- Speculative but consistent with the evidence gathered across this whole
  hardware investigation: frame 0 may serve as a full/reference frame that
  later frames are decoded *relative to* (a delta scheme), which frame 0
  itself can't participate in for lack of a prior frame to reference. This
  reframes `save_to_gif_3`/`4`'s persistent, never-resetting flip (from
  0.5.3/0.5.4): not a per-row flag that should realistically reset, but a
  one-time mode switch -- "same as reference, skip N pixels" until the
  first real difference, then permanently switched to explicit/absolute
  data for the rest of the frame.

### Known gaps
- The delta/reference-frame hypothesis is unconfirmed. This one experiment
  can't rule out some other unidentified field, or an error in
  reconstructing the modified frame, as the real cause of the failure.
- Solid-color frames' byte-level structure (`FF 00` repeated ~600 times, no
  per-row pairing) is only partially explained by this hypothesis.
- The bulk of the entropy coding is otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.11] - 2026-07-29

**"Save to GIF" research, hardware round six: palette confirmed
frame-wide.** One more experiment against `save_to_gif_5`, recoloring the
whole frame via its sub-header instead of touching any row data, confirms
0.5.10's color-index finding applies uniformly, not just to the one row
tested so far.

### Verified
- Sub-header's two RGB565 color fields changed from red/blue
  (`0xF800`/`0x001F`) to green/yellow (`0x07E0`/`0xFFE0`), with **no row
  data touched at all**. TOC `crc16_modbus` recomputed and re-uploaded the
  same way as every prior experiment.
- The entire frame rendered in the new colors -- not just row 240, all 480
  rows correctly resolved the new palette. Confirms the color-index
  mechanism from 0.5.10 is a real, uniformly applied per-frame palette
  read by every row, not something specific to the one row tested so far
  or hardcoded elsewhere.
- Incidentally clarified an earlier observation: the 2-frame animation has
  been alternating with frame 1 (unmodified solid red) throughout every
  experiment in this round -- easy to miss when frame 1's red and frame
  2's red-left half looked similar, obvious once frame 2 turned
  green/yellow and produced a visible "flash" between frames.
- Reverted afterward; confirmed restored.

### Known gaps
- Still open: reconciling the row-token/palette model with
  `save_to_gif_3`/`4`'s persistent, never-resetting flip, and why
  solid-color frames look completely different at the byte level (`FF 00`
  repeated ~600 times, no per-row pairing at all) rather than using this
  same row-token grammar.
- The bulk of the entropy coding is otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.10] - 2026-07-29

**"Save to GIF" research, hardware round five: flag byte confirmed as a
color index.** One more experiment against `save_to_gif_5` -- swapping
rather than replacing row 240's two flag values -- gives the cleanest
result of the whole investigation and revises 0.5.9's "fixed positional
marker" guess.

### Verified
- Row 240's flag bytes swapped (not set to a new value): `(0x9F,0x00)
  (0x9F,0x01) → (0x9F,0x01)(0x9F,0x00)`, same lengths, same 160/160 split.
  Rendered correctly -- not the fallback -- with the boundary in exactly
  the same place as always, but that row's colors visibly swapped.
  Confirmed by photo: a thin horizontal line at row 240 reading inverted
  relative to every row above and below it.
- This directly confirms the flag byte **is** a per-run color index,
  selecting between the sub-header's two RGB565 color slots.

### Changed
- **Revises 0.5.9.** Four data points on this row: `(0,1)` original renders
  normally; `(1,0)` swapped renders correctly with colors inverted; `(0,0)`
  and `(1,1)` (0.5.7's mutations) both fail to the fallback. The real rule
  isn't "must equal a specific value in a specific position" -- it's that a
  row's two runs must use two *different* color indices, one 0 and one 1,
  in either order; the same index twice fails.
- This also reframes 0.5.9's three-run failure: with only two possible flag
  values, three runs can never all differ pairwise from each other -- some
  pair is forced to repeat, which this same rule rejects regardless of
  whether rows can otherwise hold more than two runs. "A row's runs must
  cover each of the frame's colors exactly once" fits all six results to
  date (including the three-run failure) without a separate hardcoded-
  token-count rule. Consistent with a real encoder never emitting two
  consecutive same-colored runs in a row in the first place (it would just
  merge them, or use the continuous-run encoding solid frames use instead).

### Known gaps
- Still open: reconciling any of this with `save_to_gif_3`/`4`'s
  persistent, never-resetting flip, and why solid-color frames look
  completely different at the byte level (`FF 00` repeated ~600 times, no
  per-row pairing) rather than using this same row-token grammar.
- The bulk of the entropy coding is otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.9] - 2026-07-29

**"Save to GIF" research, hardware round four: rows are likely fixed at two
tokens.** Two more experiments against `save_to_gif_5`: one testing whether
a 3-run row can work at all, one a control isolating whether wire padding
was ever a confounding factor. Together they narrow the model further.

### Verified
- **3-run row test.** Row 240 rewritten as three runs (100px red, 100px
  blue, 120px red, still summing to 320) with continuation-style flags
  `(0, 0, 1)`, specifically to distinguish "flag = per-run color index" from
  "flag = continue/last framing bit" -- a distinction a 2-run row can't
  make, since both readings look identical when there are only ever runs 0
  and 1. Grew the row from 4 to 6 bytes; recomputed the frame's size
  fields, both TOC entries, and the checksum; padded the wire transfer to
  the next multiple of 2048 so every packet stayed a plain, already-solved
  `cmd=0x07` write rather than needing an unverified new CRC_INIT entry.
  Result: the fallback animation, same as every flag mutation.
- **Padding control.** The original, unmodified blob, with the same kind of
  trailing zero-padding and nothing else changed, uploaded and rendered
  correctly -- ruling out the padding mechanism itself as the cause of the
  3-run failure.

### Changed
- **Refines the model toward: rows in this encoding are hardcoded to
  exactly two fixed-size sub-tokens, not a flexible run-list a flag
  terminates.** The one successful mutation (0.5.8) changed lengths while
  keeping exactly 2 tokens; every failed one (0.5.7's three flag mutations,
  now plus this round's 3-token attempt) either changed a flag without
  changing token count or changed token count outright, and all fail
  identically. Under this reading the flag bytes may not carry chosen
  per-row information at all -- possibly a fixed per-slot marker (always 0
  for the first run, 1 for the second) that decoding checks strictly, with
  color implied by slot position rather than by the flag's value.
- This would also explain why solid-color frames look nothing like this
  row-token structure at the byte level (`FF 00` repeated ~600 times, no
  per-row pairing) -- possibly a separate, non-row-bounded "single
  continuous run" encoding for flat images entirely, not the same grammar.

### Known gaps
- Still unconfirmed, and still doesn't reconcile with `save_to_gif_3`/`4`'s
  persistent, never-resetting flip within what should, under this theory,
  be many independent solid rows.
- The bulk of the entropy coding is otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.8] - 2026-07-29

**"Save to GIF" research, hardware round three: first controlled content
change.** A fourth mutation experiment against the `save_to_gif_5` blob
breaks the "all-or-nothing" pattern from 0.5.7 and, for the first time in
this whole investigation, produces a predicted, position-correct change to
what the panel actually renders.

### Verified
- Row-token 240's two length bytes changed from `(159, 159)` (a 160/160
  pixel split) to `(99, 219)` (a 100/220 split) -- still summing to 320, the
  panel width, with the flag bytes left untouched. Recomputed the TOC
  `crc16_modbus` checksum and re-uploaded the same way as every prior
  experiment.
- The panel rendered the normal half-red/half-blue image, **not** the
  fallback animation, with the boundary notched inward for exactly one row.
  Confirmed by photo: the notch sits almost precisely at the panel's
  vertical midpoint, matching row 240 of 480 exactly.
- This directly confirms the run-length-stored-as-length-minus-one reading
  from 0.5.5 (previously inferred from byte patterns in captures, now
  demonstrated by controlling rendered output) and confirms the row-to-token
  mapping is exactly 1:1 with physical panel rows.
- Reverted afterward; confirmed restored (after one retry -- see Known gaps).

### Changed
- **Narrows 0.5.7's "any deviation fails identically" conclusion.** That
  held for three flag-byte mutations, but this length-byte mutation passed
  whatever validation the panel performs and rendered correctly. The
  emerging picture: the validation cares that each row's lengths still sum
  correctly (320 either way, here), not that the bytes are byte-for-byte
  identical to the original upload.

### Known gaps
- What the flag bytes need to satisfy is still unknown -- every flag-only
  edit tried so far has failed regardless of position or direction, now in
  contrast to a succeeding length-only edit.
- One restore attempt after this experiment silently didn't take (panel
  kept showing the previous fallback GIF despite a clean, acked re-upload of
  the known-good blob); an identical second re-upload fixed it. Possibly a
  read/write race if the panel was still mid-loop reading the region being
  overwritten. Not investigated further -- worth retrying a write before
  concluding a change had no effect.
- The bulk of the entropy coding is otherwise still undecoded, and this
  round's result still isn't reconciled with `save_to_gif_3`/`4`'s
  persistent-flip behavior.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.7] - 2026-07-29

**"Save to GIF" research, hardware round two: revises 0.5.6's conclusion.**
Two more single-byte mutation experiments against the same known-good
`save_to_gif_5` blob, both reverted afterward. Together with 0.5.6's first
experiment, the pattern across all three points somewhere different than
0.5.6 concluded.

### Verified
- Same flag-byte flip as 0.5.6, but on row-token 479 of 480 (the very last
  row -- the changed byte is literally the last byte of the whole upload):
  same result as before, the identical different, smaller, centered GIF.
- The opposite edit: row-token 240's *other* sub-token, flipped `0 → 1`
  instead of `1 → 0` (claiming a run stops immediately rather than claiming
  a nonexistent one continues -- the direction that should *shorten* a read
  rather than lengthen it, if the byte governs consumed length). Same
  result again.
- Confirmed directly: the fallback animation is the *exact same* one all
  three times, not three different-looking failures.
- Each mutation was reversible; re-uploading the original blob restored the
  correct half-red/half-blue image every time.

### Changed
- **Revises 0.5.6's leading theory.** Three mutations -- two positions
  (including one with nothing downstream left to run off to), two opposite
  directions -- all producing the identical result is a poor fit for
  "decoder desyncs and reads whatever raw bytes are next in flash" (0.5.6's
  conclusion): that predicts different-looking garbage per attempt, not one
  identical fallback. It fits much better with the panel validating the
  content somehow and falling back to a fixed, previously-cached animation
  on any failure, rather than rendering bad data.

### Known gaps
- Single-byte fuzzing of this stream looks like it won't reveal more on its
  own: the response is all-or-nothing, with no gradient between "slightly
  wrong" and "very wrong" to follow.
- What the content-level validation actually checks is unknown, and it
  still isn't reconciled with `save_to_gif_5`'s clean per-row alternation or
  `save_to_gif_3`/`4`'s persistent flip.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.6] - 2026-07-29

**"Save to GIF" research, first live hardware round.** The panel was plugged
directly into this Linux box, moving from passive capture analysis to
replay-and-mutate testing against real hardware. First result: strong
confirmation of everything so far. Second result: a mutation experiment that
didn't behave as predicted, but revealed something real about the flash and
decoder behavior.

### Verified
- `save_to_gif_5.pcapng`'s reconstructed blob, sent directly to the panel via
  `build_upload()` (all 4 packets acked), rendered the correct half-red/
  half-blue split. This is the first confirmation that our *output* is
  correct, not just that our wire bytes match a Windows capture -- validates
  the TOC/sub-header/checksum understanding built up over rounds 1-5 against
  the actual physical result, not just byte-comparison against captures.
- Flipping one byte in that known-good blob (the blue half's color-index
  byte in row-token 240 of 480) and re-uploading (recomputing the
  `crc16_modbus` TOC checksum to match) did not produce a localized change.
  The panel instead played a completely different, smaller GIF centered on
  screen. Re-uploading the original blob immediately restored the correct
  image, confirming the panel wasn't damaged -- this was a decode-time
  effect of the flipped byte, not a transfer-time failure.
- This is best explained by two things together: the flash write only
  touches the bytes actually sent (4216 in this case), so it doesn't erase
  whatever a previous, larger upload left further into that flash region;
  and the flipped byte likely isn't a simple static per-run color index (a
  plain index wouldn't explain jumping to unrelated, differently-sized
  content) but something that affects how many bytes the decoder consumes,
  so flipping it desynced the read position for everything downstream until
  it ran past this upload's own data and into that leftover content.

### Known gaps
- The three pieces of evidence about that "second byte" -- `save_to_gif_5`'s
  clean per-row alternation, `save_to_gif_3`/`4`'s persistent flip, and this
  round's decoder-desync result -- are not yet reconciled into one model.
- The entropy coding scheme is otherwise still not decoded. A working
  hardware replay-and-mutate loop now exists, though, which should make
  further experiments faster than capture-only analysis.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.5] - 2026-07-29

**"Save to GIF" research notes, round five.** A fifth capture
(`wireshark_dumps/save_to_gif_5.pcapng`: the same red baseline frame, but
frame 2 is a clean 50/50 vertical split -- left half red, right half blue --
instead of a single differing pixel) confirms the 528-byte fixed prefix is
genuinely content-independent, and produces the first real structural read
on the entropy-coded section itself. Still no new command.

### Verified
- `0x04240000` re-confirmed a fifth time; `crc16_modbus()` re-confirmed as
  the TOC checksum a fourth time.
- 7th `cmd`/`CRC_INIT` data point: a 120-byte final chunk predicted
  `cmd=0x7F` before checking, confirmed exact; its CRC init (`0x6F7A`) solved
  and added to `CRC_INIT`.
- **528-byte prefix confirmed genuinely fixed, not content-dependent.** With
  50% of the frame now a different color (vs. one pixel in rounds 3-4), the
  boundary between the fixed prefix and the entropy-coded section is still
  exactly 528 bytes. This was the specific question this capture was
  designed to answer.
- **First real structure decoded in the entropy-coded section.** The
  half-split frame's content is exactly 1920 bytes = 480 rows x 4 bytes, and
  is a single 4-byte unit (`9F 00 9F 01`) repeated identically 480 times.
  `0x9F` = 159 = 160-1, matching each color half's length minus one --
  evidence the first byte of a 2-byte sub-unit is a run length stored as
  length-1. The reference solid-red frame's content (1200 bytes = 600 x
  `FF 00`) fits the same reading: 600 x (255+1) = 153600, exactly the pixel
  count.

### Known gaps
- The second byte of each sub-unit (0/1 for the two color halves here) does
  not obviously reconcile with `save_to_gif_3`/`4`'s behavior, where the
  equivalent byte flips once at the point of divergence and stays flipped
  for hundreds of subsequent bytes across many rows, rather than
  alternating back per row. Whether it's a genuine per-run color index, a
  persistent context flag, or something else that looks like both depending
  on content, is unresolved.
- The rest of the sub-header and entropy coding scheme is still not fully
  decoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.4] - 2026-07-29

**"Save to GIF" research notes, round four.** A fourth capture
(`wireshark_dumps/save_to_gif_4.pcapng`: the same red-frame/one-white-pixel
pair as round three, but the white pixel moved from `(0,0)` to `(319,479)` --
the opposite end of raster order) produces the single most informative
result of the investigation so far: where the differing pixel sits controls
*how much* of the frame's encoding changes, not *how much data* the frame
needs. Still no new command.

### Verified
- `0x04240000` re-confirmed a fourth time; `cmd`/CRC-init formula holds again
  (`0xB1`, matching round three exactly since the payload length is
  identical); `crc16_modbus()` re-confirmed as the TOC checksum a third time.
- **Total frame size is independent of where the differing pixel is.** Both
  `save_to_gif_3.pcapng` (diff at top-left) and `save_to_gif_4.pcapng` (diff
  at bottom-right) produce frames of exactly the same two lengths (1728 and
  1730 bytes). The unchanged reference frame is even byte-identical between
  the two captures, confirming the encoder is deterministic.
- **Diff extent is sharply position-dependent.** Diffing each capture's two
  frames directly: the top-left diff (round three) changes 605 bytes, nearly
  the whole frame; the bottom-right diff (this round) changes only 5 bytes,
  clustered at the very end. This is strong, position-controlled evidence
  for a running encode-time context that a "differs from expectation" event
  permanently perturbs from that point in the raster scan onward -- an early
  divergence corrupts everything downstream of it, a late one corrupts
  almost nothing.
- **Color-field pair semantics resolved for these two captures**: one
  sub-header field holds the color of the frame's first pixel in raster
  order, the other holds the "other" color present (if any). Confirmed
  consistent between `save_to_gif_3` and `4` (the fields swap depending on
  whether the diff pixel is first or last), but this still doesn't explain
  `save_to_gif_2`'s solid frames, whose sole color sits in the "other" slot
  instead of the "first pixel" slot.
- The terminal-of-frame encoding for a last-pixel diff isn't a simple
  continuation of the same token-flip pattern seen for a first-pixel diff:
  the tail changes from repeating `...FF 00 FF 00` to `...FE 00 00 01`, a
  distinct pattern rather than one more flipped token.

### Known gaps
- The entropy-coded pixel section is still not decoded. This round narrows
  *where* a change appears; it doesn't yet reveal how a token is built.
- The color-field/`save_to_gif_2` inconsistency above is unresolved --
  possibly tied to `save_to_gif_2`'s much larger content length, not
  confirmed.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.3] - 2026-07-29

**"Save to GIF" research notes, round three.** A third capture
(`wireshark_dumps/save_to_gif_3.pcapng`: two frames, both solid red except
one white pixel at `(0,0)` in frame 2) resolves the TOC's frame-count
ambiguity, adds a sixth confirmed `cmd`/CRC-init data point, and — the main
result — locates a fixed ~528-byte per-frame prefix and pins down exactly
how a single-pixel difference between two otherwise-identical frames shows
up in the byte stream. Still no new command; the entropy-coded pixel data
itself remains undecoded.

### Verified
- `0x04240000` re-confirmed a third, independent time.
- Sixth `cmd`/`CRC_INIT` data point: a 1450-byte final chunk predicted
  `cmd=0xB1` by `final_chunk_cmd()` before checking, confirmed exact; its
  CRC init (`0x9F4E`) was solved and added to `CRC_INIT`. Still no general
  formula relating `CRC_INIT` to length, now checked against 6 points.
- **TOC frame-count ambiguity resolved.** 0.5.1/0.5.2 couldn't tell whether
  TOC-entry byte 12 or byte 13 was the real frame count, since both captures
  used 3-frame animations and both bytes read `3`. This capture uses 2
  frames: byte 12 stayed `3` (a constant format/version tag) and byte 13
  read `2` (the real frame count).
- `crc16_modbus()` over the post-header payload re-confirmed as the TOC's
  per-entry checksum field, byte-exact a second time.
- **Located a fixed ~528-byte per-frame prefix.** Every frame in both the
  second and third captures (5 frames total, 3 different solid colors plus
  the one-pixel-diff pair) has exactly 528 zero bytes right after its
  sub-header, regardless of color — strong evidence of a fixed table (as in
  JPEG's Huffman/quantization tables) independent of image content, with a
  variable-length entropy-coded section following it (whose length is a
  sub-header field, self-consistent with the frame's total size across all
  5 frames).
- **Located the single-pixel-diff signature.** The two frames differ at
  byte 528 itself (`0xFF`→`0x00`) and then, from the very first token after
  that boundary onward, a recurring 2-byte token's second byte is `0x00` in
  frame 1 and `0x01` in frame 2 for the rest of the frame — one flip, never
  reset. The change starting in the first post-prefix token matches `(0,0)`
  being first in raster-scan order. Reads as a running prediction context
  permanently perturbed by a "differs from expectation" event, consistent
  with (but not proof of) the transform/DCT-style coding hypothesis from
  0.5.2.

### Known gaps
- The entropy-coded pixel section itself is still not decoded — this
  capture shows *that* one pixel differing perturbs a running context, not
  *how* to construct that context or the tokens themselves.
- The RGB565-looking color-field pair's exact byte offset isn't consistent
  between captures 2 and 3, so its precise layout is still unclear even
  though the values themselves clearly track real colors.
- Next useful capture: the differing pixel at a different position, to map
  how position affects where in the byte stream the change appears and
  whether the 528-byte boundary is truly fixed or scales with something.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.2] - 2026-07-29

**"Save to GIF" research notes, round two.** A second, deliberately simple
capture (`wireshark_dumps/save_to_gif_2.pcapng`: solid red/green/blue
frames) cracks the final-chunk `cmd` byte, the TOC checksum, and part of the
per-frame sub-header. Still no new command — the bulk of each frame's pixel
payload remains undecoded — but this closes several of 0.5.1's open
questions and fixes a latent bug it left in `build_upload()`.

### Fixed
- `build_upload()` always used the fixed `CMD_FINAL` (`0x12`) for a final
  short chunk, correct only because every image this module has ever built
  is `320x480` and therefore always has the same 11-byte remainder. Any
  other image size would silently send the wrong `cmd` byte (and thus the
  wrong CRC) for its final chunk. Now computed via `final_chunk_cmd()`
  (below), which fails loudly with `ValueError` for a length with no known
  `CRC_INIT` entry instead of silently sending bad data. No behavior change
  for the `320x480` path this module actually uses — verified by re-running
  the byte-for-byte check against both `save_to_bkg_1/2.pcapng` captures.

### Verified
- **The final-chunk `cmd` byte is solved**: `cmd = CMD_WRITE + (payload_len %
  256)`, not a fixed opcode. `CMD_COMMIT` (`0x0B`) and `CMD_FINAL` (`0x12`)
  turn out to be ordinary instances of this formula, not independent
  opcodes — coincidentally constant because commit payloads are always 4
  bytes and this module's images always leave an 11-byte remainder. Checked
  exactly against 5 independent samples across 3 capture files, including
  both GIF captures' final chunks (`0x71` for 1386 bytes, `0x35` for 1582
  bytes) predicted correctly before being checked.
  - No general formula for the matching `CRC_INIT` was found: two
    hypotheses (init as a function of the cmd byte alone, or of the
    magic+lenfield+cmd prefix) were brute-forced against all 5 known
    (cmd, init) pairs and neither held. `CRC_INIT` gained two entries solved
    for the exact lengths seen (`0x71`→`0x1CB0`, `0x35`→`0xD9F1`), not a
    general result.
- **The GIF TOC's per-frame checksum field is solved**: it's
  `crc16_modbus()` — the same function already used for the single-image
  header — over the payload following the header. Verified byte-exact.
- **Two per-frame sub-header fields decoded**, by diffing two of the second
  capture's solid-color frames (byte-identical for ~8800 bytes except one
  4-byte window): the frame's own byte length (self-referential, exact for
  all 6 frames across both captures), and its dominant/fill color in RGB565
  (exactly pure red/blue/green for the three test frames).
- `0x04240000` re-confirmed as the "Save to GIF" address from a second,
  independent capture.

### Known gaps
- Each frame's actual pixel payload is still undecoded: not raw RGB565, not
  zlib/deflate, no JPEG SOI marker. The strongest lead — two solid-color
  frames being byte-identical except for one small window — points toward
  some transform/DCT-style coding rather than simple run-length encoding,
  but this is unconfirmed. Next step: a 2-frame GIF differing by one pixel,
  to isolate how a coefficient or delta is expressed.
- No general `CRC_INIT`-vs-length formula, so the cmd-byte fix above still
  can't extend to arbitrary new upload sizes without a matching capture.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.1] - 2026-07-29

**"Save to GIF" research notes.** No new command — the payload format isn't
understood well enough yet to safely construct one — but the flash address
and container header layout are now documented from a new capture.

### Verified
- `wireshark_dumps/save_to_gif_1.pcapng` reuses the exact same `5a a5`
  framing/CRC-init machinery as the photo-frame/background paths (157
  write/commit packets), at flash base `0x04240000` — this resolves half of
  0.5.0's "Known gaps" entry about the vendor binary's undocumented
  `0x4200000`/`0x4240000` slots. `0x04200000` is still unidentified.
- One difference from the other two paths: the final short data chunk uses
  `cmd 0x71` where they use `0x12`. Meaning unconfirmed.
- The blob written there is a small table-of-contents header — 20 bytes per
  frame (3 frames captured, well under the vendor's own
  `gif_maxframes="200"`/`gif_headlength="256"` in `layouts/rgb-keyboard.xml`)
  — giving each frame's absolute byte offset, `320x480` dimensions, frame
  count, a likely delay field, and a likely-but-unverified checksum. Full
  field breakdown is in `protocol.py` above `GIF_FLASH_BASE`.
- Each frame's own payload is **not raw RGB565**: roughly a third smaller
  than a full `320x480` RGB565 frame, not zlib/deflate, with a byte
  distribution that looks like a run-length or delta-coded scheme rather than
  pixels.

### Known gaps
- The per-frame pixel encoding is undecoded. Unlike the photo-frame CRC
  inits, which were solved from two independent captures, only one GIF
  capture exists, so there's no second sample to check a hypothesis against.
  Progress needs more targeted captures — e.g. a solid-color 1-frame GIF and
  a 2-frame GIF differing by one pixel.
- The `cmd 0x71` final-chunk opcode's meaning is unknown.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.0] - 2026-07-29

**"Save to BKG" (background image) support.** The vendor app's `--upload`
path was only ever exercised for one of its three upload destinations; this
release adds a second, confirmed from newly captured traffic.

### Added
- `--target {photo-frame,background}` for `--upload` (default `photo-frame`,
  unchanged from before). `--address` still exists and overrides `--target`.
- `protocol.PHOTO_FRAME_FLASH_BASE` (`0x041E0000`, renamed from `FLASH_BASE`)
  and `protocol.BACKGROUND_FLASH_BASE` (`0x04180000`).

### Verified
- The vendor app's own string table (`Windows/AULA L99/language/1033.lan`
  #866-868) names three distinct upload actions: "Save to GIF", "Save to
  BKG" and "Save to photo frame" — confirming these are separate
  destinations, not the same feature under different names.
- Two new captures of "Save to BKG" (`wireshark_dumps/save_to_bkg_1.pcapng`,
  `save_to_bkg_2.pcapng`) need **no protocol changes at all**: every one of
  the 154 bulk-OUT packets in each capture is reproduced byte-for-byte by the
  existing `protocol.build_packet()` — same magic, command bytes, and
  per-command CRC inits as the already-verified photo-frame path.
  Reconstructing each capture's chunks yields a 307200-byte RGB565 320x480
  payload whose header CRC checks out via `protocol.describe()`.
- The only difference is the flash base address: both captures write to
  `0x04180000` (commits at `0x04180000`, `0x041a0000`, `0x041c0000`), not
  `0x041E0000`. No extra "activate" command exists beyond the standard
  write/commit sequence and normal CDC-ACM serial-port open/close.
- `--target background` confirmed on real hardware: the panel's background
  changes as expected.

### Fixed
- `protocol.FLASH_BASE`'s comment claimed it was "where the vendor writes the
  wallpaper." That address is the photo-frame slot, not the background one;
  the comment was corrected as part of the rename.

### Known gaps
- "Save to GIF" (animated frames) is a third, uncaptured destination/protocol
  and remains unimplemented.
- The `0x4200000`/`0x4240000` slots referenced in the vendor binary are still
  unaccounted for.

## [0.4.1] - 2026-07-29

**Image upload works.** Confirmed on hardware: 154 packets sent, all 154 acked
by the panel, image visible on the screen. 0.4.0 had the payload format right
but no way to deliver it; this release adds the wire protocol.

### Added
- `--upload IMAGE` converts an image and writes it to the panel's flash, with
  `--address`, `--gap` and `--ignore-nak` for experimenting.
- Wire protocol, on bulk endpoints `0x03` out / `0x82` in:

        5a a5          magic
        <len/256>      uint16 BE
        <cmd>          0x07 write · 0x12 final partial · 0x0b commit
        <const>        0x64 data · 0x66 commit
        <address>      uint32 BE flash address
        <payload>
        <crc>          uint16 LE, poly 0xA001 reflected, init per command

  The `.bin` is written from flash base `0x041E0000` in 2048-byte chunks. After
  each filled 128 KiB region a commit carries that region's byte count; a final
  short packet and a last commit end the transfer.
- Per-command CRC inits: `0xF104` write, `0xEEC4` commit, `0xD141` final. No
  single init fits all three.
- `tools/aula_l99_screen/README.md` documenting both the image format and the
  wire protocol.

### Verified
- The packet generator reproduces **both** upstream captures byte-for-byte, all
  154 packets each.
- The CRC inits validate against **308/308** packets across both captures. They
  were solved algebraically over GF(2) after brute force failed — that search
  had been seeded from commit packets, which use a different init to the data
  chunks, so it could never have converged.
- Reconstructing the `.bin` from the captured chunks yields exactly 307211
  bytes whose embedded CRC validates, confirming the header/payload/trailer
  split independently of the generator.

### Fixed
- Ack detection accepted only ASCII `OK`, which rejected valid commit replies:
  a commit answers with a 21-byte reply carrying a 4-byte checksum of the region
  just written, so it is image-dependent and must not be compared literally.
  This aborted an otherwise correct upload at packet 64.

### Removed
- `--send`, which wrote the payload raw to the serial port. It was the delivery
  attempt built on the mis-attributed JPEG protocol; the panel ignores such
  writes entirely, so keeping it would only invite the same dead end.

### Root cause of 0.4.0's "nothing appears"
- The JPEG protocol (magic `12 34 56 78`) that 0.4.0 recorded as superseded
  **belongs to a different device**. In the upstream project's own captures that
  traffic goes to `87ad:70db`, another USB display on that machine, while the
  AULA panel `eeef:268a` is a separate device speaking the `5a a5` protocol
  above. Every dead end in 0.4.0 — no reply at any baud from 9600 to 2000000, no
  visible change, a hunt for a nonexistent HID "refresh" command — traces back
  to trusting that attribution without checking which device the captured
  traffic actually addressed.

### Known gaps
- Touch input, brightness and screen power remain uncaptured.
- Why each command needs a different CRC init is not understood; the values are
  empirical.
- Two further flash slots exist at `0x4200000` and `0x4240000` (the vendor
  binary references all three); only `0x041E0000` has been used.
- The panel may need a restart before it redraws from flash; no command to
  force a refresh has been identified.

## [0.4.0] - 2026-07-29

Touchscreen image **format decoding**. Establishes the panel's native image
format and ships a converter for it; delivery to the device came in 0.4.1. The
`EEEF:268A` panel is a CDC-ACM USB-serial device, entirely separate from the
keyboard's HID channel, so it lives in its own module and shares no code with
`aula_l99_hacky`.

### Added
- `tools/aula_l99_screen/`:
  - `--convert IMAGE -o FILE` produces the `.bin` the panel expects.
  - `--describe FILE` decodes a `.bin` header and checks its CRC.
  - `--list` finds the panel by VID/PID rather than assuming `/dev/ttyACM0`.
- Panel image format, derived from the vendor's own `qt-tool/Image2Bin.exe` by
  feeding it known images and decoding the output:

        [0..3]   uint32 LE  payload size (width * height * 2)
        [4..5]   uint16 LE  width   (320)
        [6..7]   uint16 LE  height  (480)
        [8]      0x00       constant in every sample
        [9..10]  uint16 LE  CRC16/MODBUS over the pixel data
        [11..]   pixels     RGB565, little-endian, row-major

- Binary-safe serial transport using a `cfmakeraw` equivalent, since Python
  exposes none.

### Verified
- The encoder reproduces `Image2Bin.exe` **byte-for-byte** for four images
  across two different sizes, header and pixels alike.
- Pixel encoding checked against a known image: the first pixel decodes to
  `0x05BF`, exactly RGB565 for the cyan `(0,180,255)` line at y=0, and the last
  to `0x0845` for the `(10,10,40)` background.
- The dimension fields are real rather than constants: a 200x100 input yields a
  40011-byte file with width=200, height=100.
- The checksum is CRC16/MODBUS little-endian; CRC16/ARC, CCITT, XMODEM, Kermit
  and plain byte and word sums were all tested and none matched.

### Fixed
- The serial port was opened as a cooked tty, corrupting binary payloads:
  `ONLCR` expands every `0x0A` and `IXON` swallows `0x11`/`0x13` — 100 bytes of
  a 17 KB payload. Raw mode is now mandatory in the transport.

### Superseded
- An earlier implementation of this module used a JPEG-based format taken from
  third-party documentation of this panel (64-byte header, magic
  `12 34 56 78`, command `0x02`). The vendor's own converter emits raw RGB565,
  so that format is wrong for this hardware. See 0.4.1 for why it existed at
  all.

### Known gaps
- **Nothing has been shown on the panel yet.** The payload is right, but the
  framing the vendor uses to send it is not known, and writing the bytes raw to
  the port produces no visible change and no reply, at any baud from 9600 to
  2000000.
- Byte 8 of the header is `0x00` in every sample; its meaning is unknown.
- Under Wine the vendor app cannot find the panel at all: it locates the port
  through SetupAPI, and Wine's `Enum\USB` tree contains the keyboard (which
  `winebus` registers) but not CDC-ACM serial devices. This is a limitation of
  Wine's device model, not a configuration error, and no COM-port symlink fixes
  it.
- Touch input, brightness and screen power remain uncaptured.

## [0.3.0] - 2026-07-28

### Added
- `--effect ID` selects one of the keyboard's built-in preset effects (opcode
  `0x13`), with `--color`, `--speed` (1–5) and `--brightness`. The effect runs
  on the keyboard; the host only selects it and its parameters.
- `--list-effects` lists all 20 preset ids and flags which are confirmed by
  capture rather than inferred.
- Effect payload layout: `[0]` effect id, `[1..3]` R G B, `[8]` a mode flag,
  `[9]` brightness, `[10]` speed `1..5`. Speed was pinned down by working the
  vendor app's slider from middle to minimum to maximum and watching byte 10
  go `03`, `01`, `05`.
- Effect ids are the 1-based position in the vendor app's 20-entry effect list.
  `0x04`–`0x08` (glittering, fluttering, colourful, breath, spectrum) and
  `0x01` (static) are confirmed by capture; the rest follow from list order.
- `0x80` identified as the custom per-key mode rather than a preset — it is
  what pairs with a `0x23` colour upload.
- Command headers are retried, so the tool still works if the vendor app is
  open at the same time; sharing the hidraw node with it otherwise makes reads
  return the app's own `0xF5` poll replies and time out. Data blocks are never
  retried, since a retry mid-transfer could corrupt an upload.

### Changed
- The `AA 55` trailer marks end-of-record and its offset varies per command:
  bytes 14–15 for an effect payload, 62–63 for colour and RTC blocks.

### Fixed
- `--color` no longer shadows `--effect`: passing both ran the solid-colour
  path and silently ignored the effect, since `--color` doubles as the effect's
  colour parameter.

### Known gaps
- Effect ids `0x02`, `0x03` and `0x09`–`0x14` are named from the vendor app's
  list order rather than confirmed by capture.
- Byte 8 of the effect payload is unidentified. It is `0x00` for ids `0x04` and
  `0x07` and `0x01` elsewhere, but it is not a "colour supported" flag: `0x04`
  accepts a colour.
- Byte 9 is read as brightness because it only ever appeared as `0x05`, which
  is the top of the speed byte's range. The vendor app exposes no brightness
  control, so this is inference, not evidence.
- There is no opcode `0x00`: it was an artifact of classifying data blocks by
  their first byte instead of positionally. Effect payloads for ids `0x04`–
  `0x08` begin with `0x04`, which reads exactly like a command header.

## [0.2.0] - 2026-07-28

### Added
- `--color RRGGBB` sets every key's colour (opcode `0x23`).
- `--gap` to tune the inter-packet delay.
- RTC-set on the wired path, which previously refused to run.
- Confirmed key-id table: 84 keys, ids `0x00`–`0x7F`, row = high nibble and
  column = low nibble.

### Changed
- `protocol.py` now describes the wired `0C45:800A` path from a capture of the
  vendor app rather than from AULA F75 MAX prior art. Every builder was checked
  to reproduce the vendor's own packets byte-for-byte.
- Corrected: `0x28` is the RTC-set command, not session-prepare as previously
  assumed, and `0x02` is a commit that returns a 16-bit value, not a session
  finalizer. The cable path has no checksum byte; the 32-byte packet size and
  trailing checksum apply only to the (still untested) dongle path.
- The 64-byte RTC payload puts `AA 55` at bytes 62–63, not adjacent to the date
  as in the 32-byte F75 format.
- Dongle-path constants and builders are kept but marked as unverified guesses.

### Fixed
- Packets are no longer issued back-to-back: with no gap, the second data block
  of a transfer fails with `ETIMEDOUT` and replies are read before the device
  sets its ack bit.
- hidraw transfers now carry the required leading `0x00` report-id byte on the
  dongle path too; the device declares no Report ID item.
- `--handshake` no longer commits an empty session, which the device rejects
  with `0xFF` in the ack byte.
- `--send-hex` rejects over-length packets instead of silently sending them.

### Known gaps
- The 16-bit value returned by the commit is unidentified; it is most likely a
  checksum over the upload. Macros have not been looked at.
- Nothing on the dongle path has been tested against hardware.

## [0.1.0] - 2026-07-28

### Added
- `tools/aula_l99_hacky/`: Linux CLI for the AULA L99's vendor HID channel
  (`0C45:800A` wired, `05AC:024F` 2.4G dongle).
  - `device.py` — hidraw device discovery and a transport supporting raw
    read/write plus `HIDIOCSFEATURE`/`HIDIOCGFEATURE` for the cable's feature
    reports.
  - `protocol.py` — confirmed session handshake (`SESSION_INIT`/`SESSION_QUERY`
    on the dongle path, `CABLE_SESSION_INIT`/`PREPARE` on the cable path), the
    packet checksum (`sum(bytes[0:31]) & 0xFF`), and the RTC-set command
    builder.
  - `cli.py` — `--list`, `--handshake`, `--rtc`, and `--send-hex` (test a raw
    packet captured from the vendor driver against real hardware).
- Research writeup (`Windows/AULA L99/PLAN.md`) covering static analysis of
  the extracted vendor installer and prior-art survey: confirms the keyboard
  side (`0C45:800A`) uses the standard Windows HID API, the touchscreen is a
  *separate* `EEEF:268A` USB-serial device (not part of the keyboard's HID
  interface), and links the most relevant open-source reverse-engineering
  projects for this hardware family.

### Known gaps
- RGB/lighting effect commands and macro commands for `0C45:800A` are not yet
  captured or documented anywhere (including this project) — only the
  session handshake and RTC-set command are confirmed.
- No live hardware/Windows capture has been performed yet; everything to
  date is static analysis plus third-party prior art.
