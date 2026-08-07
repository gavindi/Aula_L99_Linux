# TODO — Feature Gap vs. Vendor App

Feature comparison against the vendor's `AULA L99 Driver` (Beta 1.0.1.4,
`DeviceDriver.exe`), derived from its `language/1033.lan` UI strings. The
second table is the work backlog.

## Covered by this app (parity or better)

| Vendor feature | Status in this app |
|---|---|
| 20 built-in lighting effects + speed/brightness | ✓ Full parity — effect id is the 1-based vendor list position (hacky README) |
| User/custom per-key lighting | ✓ Per-key editor + vendor-format XML profile save/load |
| Real-time (host-animated) lighting | ~ Vendor has 8 modes; app has breathing, colour cycle, rainbow wave, currents, revolving, starlight (~17 fps) |
| Music Rhythm (Rhythm, Amplitude, Background Mode ×15, Background Brightness) | ✓ Same 15-entry lists, both persisted |
| Audio spectrum analyser | ✓ Plus live `arecord` capture → own FFT (17-band) |
| System monitor (CPU/GPU load & temp) | ✓ Fed to panel via RTC packet — reads `/proc/stat` + nvidia-smi/drm instead of LibreHardwareMonitor |
| Weather/forecast/humidity on panel | ~ Via CLI flags (manual values); vendor app has its own data source |
| Key response time (debounce levels) | ✓ (opcode 0x17) |
| Sleep timer (none/1/5/30 min) | ✓ (opcode 0x17) |
| Clock set | ✓ |
| Image upload to screen (photo-frame, BKG) | ✓ |
| Animated GIF upload | ~ Works, but "safe colors" only — vendor's dithering not reimplemented (the documented open blocker) |
| Tray behavior | ✓ (`--tray`, close-to-tray) |

## Missing entirely (or partial) — the work backlog

| Vendor feature | Notes |
|---|---|
| Key remapping ("My Exclusive Config") | Per-key functions, Fn layer, momentary/toggle, multi-key, mouse/media/Windows-shortcut, open program/website/file, send text — none present; "macros" listed under README's *What's still open* |
| Macro Manager | Record/edit keyboard+mouse macros, loops, delays, import/export |
| IPS screen GIF **editor** | Brush/eraser/text, per-frame delays, 200-frame editing, save/export — app only uploads finished GIFs |
| Side Light Mode | 10 modes (flowing/red/yellow/green/ice blue/blue/pink/white/neon/off) — absent |
| Disable Windows Key / Alt+F4 / Alt+Tab | Absent |
| Reset Keyboard / Factory Reset | Absent |
| Driver update / firmware update (keyboard + screen) | Absent |
| Language selection | Vendor ships 5 languages; app is English-only |
| Autostart on login | Absent (only tray) |
| Lighting Direction control | Vendor has it; effect block in `protocol.py` has no direction byte |
| 2.4G dongle colour/effect/settings | Partial — handshake + RTC-set confirmed; rest open |
| Weather auto-fetch / "Store" page | App has no online sources (arguably a plus) |
