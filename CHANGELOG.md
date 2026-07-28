# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-07-29

Touchscreen image support. This is the `EEEF:268A` panel, a CDC-ACM USB-serial
device — an entirely separate device from the keyboard's HID channel, so it
lives in its own module and shares no code with `aula_l99_hacky`.

### Added
- `tools/aula_l99_screen/`: convert images to the panel's native format.
  - `--convert IMAGE -o FILE` produces the `.bin` the panel expects.
  - `--describe FILE` decodes a `.bin` header and verifies its CRC.
  - `--list` finds the panel by VID/PID rather than assuming `/dev/ttyACM0`.
  - `--send IMAGE` writes the payload to the port (see Known gaps).
- Panel image format, derived from the vendor's own `qt-tool/Image2Bin.exe` by
  feeding it known images and decoding the output:

        [0..3]   uint32 LE  payload size (width * height * 2)
        [4..5]   uint16 LE  width
        [6..7]   uint16 LE  height
        [8]      0x00       constant in every sample
        [9..10]  uint16 LE  CRC16/MODBUS over the pixel data
        [11..]   pixels     RGB565, little-endian, row-major

- Binary-safe serial transport: the port is put in raw mode via a `cfmakeraw`
  equivalent, since Python exposes none.

### Verified
- The encoder reproduces `Image2Bin.exe` **byte-for-byte** for four images
  across two different sizes, header and pixels alike.
- Pixel encoding was checked against a known input: the first pixel decodes to
  `0x05BF`, exactly RGB565 for the cyan `(0,180,255)` line at y=0, and the last
  to `0x0845` for the `(10,10,40)` background.
- The dimension fields are real rather than constants: a 200x100 input yields a
  40011-byte file with width=200, height=100.
- The checksum is CRC16/MODBUS little-endian; CRC16/ARC, CCITT, XMODEM, Kermit
  and plain byte and word sums were all tested and none matched.

### Fixed
- The serial port was being opened as a cooked tty, which corrupted binary
  payloads: `ONLCR` expands every `0x0A` and `IXON` swallows `0x11`/`0x13` —
  100 bytes of a 17 KB test payload. Raw mode is now mandatory in the
  transport.

### Known gaps
- **Nothing has been shown on the panel yet.** The payload is right, but the
  framing the vendor uses to send it is not known, and writing the bytes raw to
  the port produces no visible change and no reply, at any baud from 9600 to
  2000000.
- The vendor sends images via `qt-tool/SerialPortTool.exe`, which takes three
  arguments and exits immediately without them. Driving it under an `ioctl`
  shim is the most direct route to capturing the real framing.
- Under Wine the vendor app cannot find the panel at all: it locates the port
  through SetupAPI, and Wine's `Enum\USB` tree contains the keyboard (which
  `winebus` registers) but not CDC-ACM serial devices. This is a limitation of
  Wine's device model, not a configuration error, and no COM-port symlink fixes
  it.
- Byte 8 of the header is `0x00` in every sample; its meaning is unknown.
- Touch input, brightness and screen power remain uncaptured.

### Superseded
- An earlier implementation of this module used a JPEG-based format taken from
  third-party documentation of this panel (64-byte header, magic
  `12 34 56 78`, command `0x02`). That format is wrong for this hardware — the
  vendor's converter emits raw RGB565 — and it is why images sent with it never
  appeared. It has been replaced, not kept as a fallback.

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
