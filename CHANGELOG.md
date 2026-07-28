# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
