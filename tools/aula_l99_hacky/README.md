# aula_l99_hacky

Linux tool for the AULA L99's vendor HID channel (`0C45:800A` wired, `05AC:024F` 2.4G
dongle). This covers the **keyboard-side HID protocol** — the touchscreen is a
separate `EEEF:268A` USB-serial device, already documented in
[Salamor/aula-l99-open-widgets](https://github.com/Salamor/aula-l99-open-widgets).

One exception to that split: the panel's CPU/GPU and weather readout arrives
over *this* channel, not the panel's own serial port, riding in the RTC packet
(`0x28`) for the keyboard to forward. See
[re_notes/system_monitor_block.md](re_notes/system_monitor_block.md).

## Status

Confirmed on real hardware (wired `0C45:800A`, interface 3):

- Session framing, writing per-key RGB, reading per-key RGB back, selecting
  built-in effects, and the RTC-set command.
- The nine system-monitor and weather bytes of the `0x28` block — CPU/GPU load
  and temperature, current/high/low temperature, weather condition, humidity —
  each verified by writing a distinctive value and reading the panel.
- The audio spectrum feed (`0x78`): 23 band levels, low frequency first, with
  the ack/echo behaviour and band ordering confirmed by driving one band at a
  time. Note the panel's analyser renders only 17 segments (wire bands 0..16);
  bands 17..22 have no visible effect.
- Every packet builder in `protocol.py` reproduces the vendor app's own packets
  byte-for-byte — see "Verifying against a capture" below.

Also confirmed on real hardware (2.4G dongle `05AC:024F`, interface 3):

- The F75_Initializer dongle probes work on the L99 dongle unchanged: the
  session-init and session-query packets get their expected replies, and an
  RTC-set returns the prior-art ack (`0C 10 00 00 … 1C`). Byte 11 of the
  session-init reply is a per-device firmware version — `0x08` on the F75 MAX,
  `0x29` on the L99 dongle under test — stable across sessions and unchanged
  before/after the keyboard pairs, so `dongle_replies_match()` does not require
  it to match. Keystrokes from a paired keyboard arrive on interface 0, not
  this vendor channel.

Decoded but **not** confirmed on hardware: byte 1 of the `0x28` block being a
screen-view index rather than a constant. Only view 1 has ever been used, so
what a higher value does is unknown. Nor is it known whether the panel reads a
negative temperature as signed — `--air-temp -5` sends `0xFB` because that is
what the vendor app would send, not because the result was observed.

Key remapping and macros are now documented too: opcodes `0x11` (key-profile
table), `0x19`/`0x15` (macro slot write) and the suspect `0x27` (Fn-layer
table) in [re_notes/key_remap_macros.md](re_notes/key_remap_macros.md).
Remaps, disables, media bindings and the macro sequence are stored on the
keyboard — they keep working with the driver closed.

Still unknown: the meaning of byte 8 of the effect payload.
Effects run on the keyboard itself — the vendor app
polls `0xF5` ~27x/s to mirror the keyboard's current LED state in its preview,
rather than driving the lighting from the PC. On the dongle, only the handshake
and RTC-set have been tested: its colour/effect/settings commands still await a
capture of the vendor app driving the dongle (its 32-byte framing differs from
the cable's 64-byte blocks), and the RTC block's monitor-field offsets remain
unverified against the dongle.

## Usage

No root needed on most systems — a udev rule usually gives the logged-in user
an ACL on the keyboard's hidraw nodes. Check with `getfacl /dev/hidraw7`.

```bash
cd tools

# find the vendor interface (interface 3 is the one that matters)
python3 -m aula_l99_hacky.cli --list

# open and close a session: proves the channel works
python3 -m aula_l99_hacky.cli --handshake --debug

# set every key to one colour, stored on the keyboard
python3 -m aula_l99_hacky.cli --color 00FF00

# read back every key's current colour
python3 -m aula_l99_hacky.cli --read-color

# run a built-in effect: id, colour, speed 1-5
python3 -m aula_l99_hacky.cli --list-effects
python3 -m aula_l99_hacky.cli --effect 0x05 --color 0000FF --speed 5

# set the keyboard's clock
python3 -m aula_l99_hacky.cli --rtc

# the same packet drives the touchscreen's monitor readout; omitted fields
# are sent as zero, which is what the vendor app sends with nothing to report
python3 -m aula_l99_hacky.cli --list-conditions
python3 -m aula_l99_hacky.cli --rtc \
    --cpu-load 42 --cpu-temp 55 --gpu-load 10 --gpu-temp 48 \
    --air-temp 26 --day-high 34 --night-low 25 --condition rain --humidity 95

# test a candidate packet from your own capture
python3 -m aula_l99_hacky.cli --send-hex "04 23 00 00 00 00 00 00 09"
```

## Protocol

Transport is HID **feature reports** on interface 3: `SET_REPORT`/`GET_REPORT`,
`wValue 0x0300`, `wIndex 3`, 64 bytes. The report descriptor declares no Report
ID item, so Linux hidraw needs an explicit leading `0x00` on every transfer.

```
command:  04 <opcode> 00 00 00 00 00 00 <block_count> 00 ...   (64 bytes)
reply:    04 <opcode> 00 01 ...                                (byte 3 = ack)
          then <block_count> raw 64-byte data blocks, no header
          the last block of a transfer carries AA 55 at bytes 62..63
```

| Opcode | Meaning | Blocks |
|--------|---------------------------------------------|--------|
| `0x18` | begin session                                | 0 |
| `0x28` | set RTC *and* the panel's monitor readout — `00 VV 5a`, then Y M D h m s, weekday, then CPU/GPU load and temperature and the weather fields | 1 |
| `0x23` | write per-key colour                         | 9 out |
| `0xF5` | read back current per-key colour             | 9 in |
| `0x02` | commit; reply returns 16 bits at offset 4    | 0 |
| `0xF0` | end session                                  | 0 |
| `0x13` | select a built-in effect                     | 1 out |
| `0x11` | write the key-remap ("My Exclusive Config") table — 4-byte entries at `key_index * 4` | 9 out |
| `0x15` | write the macro slot — 8-byte key events (`00 00 <usage> <B0|30> <delay> 00 00 50`), preceded per round by `0x19` | 9-10 out |
| `0x27` | same table shape as `0x11`, seen only at startup with an all-zero table; Fn-layer table is the working hypothesis | 9 out |

Data blocks flow *out* from the host for a write (`0x23`) and *back* from the
device for a query (`0xF5`). The command header looks identical either way, so
always check the direction of a captured packet before assuming it is a write.

A query is **not** wrapped in a begin/commit/end session the way a write is.
The vendor app's steady-state poll loop, confirmed against a capture, is just
`commit -> query -> 9 blocks in`, repeated: the commit closes out the previous
read before the next query is issued. An unrelated begin/effect/commit/end
session elsewhere in the same capture (the user picking an effect) runs
independently and doesn't interrupt the poll. `cmd_read_color()` in `cli.py`
reproduces this exact sequence and has been run against real hardware.

**Colour blocks.** A write is nine blocks: eight key rows plus a zero-filled
terminator carrying `AA 55`. A query reply is also nine blocks but has no
terminator — all nine are real rows (`0x00`–`0x8F`), the ninth simply has no
physical keys in it. Each row holds 16 entries of 4 bytes, `[key_id, R, G, B]`,
where the entry's position is the key id's low nibble and the block index is
its high nibble. Colour is plain RGB, passed through literally (verified with
`#00FF00` → `00 ff 00` and `#0000FF` → `00 00 ff`). The L99 has 84 keys in ids
`0x00`–`0x7F`; positions with no physical key are sent/received as four zero
bytes.

**Effect blocks.** One block, with the trailer at bytes 14–15 rather than
62–63 — the trailer marks end-of-record and records are not all the same
length. Layout: `[0]` effect id, `[1..3]` R G B, `[8]` a mode flag (`0x01` for
most ids but `0x00` for `0x04` and `0x07`), `[9]` brightness (only ever seen as
`0x05`), `[10]` speed `1..5`. Speed was confirmed by working the vendor slider
from middle to minimum to maximum and watching byte 10 go `03`, `01`, `05`.

The id is the **1-based position in the vendor app's effect list**, which has 20
entries: `0x01` static, `0x02` single-on, `0x03` single-off, `0x04` glittering,
`0x05` fluttering, `0x06` colourful, `0x07` breath, `0x08` spectrum, `0x09`
outward, `0x0A` scrolling, `0x0B` rolling, `0x0C` rotating, `0x0D` explode,
`0x0E` launch, `0x0F` ripples, `0x10` flowing, `0x11` pulsating, `0x12` tilt,
`0x13` shuttle, `0x14` led-off. Ids `0x04`–`0x08` were confirmed by capture; the
rest follow from list order. `--list-effects` marks which is which.

`0x80` is not in that list: it is the custom per-key mode, sent whenever the
vendor app had the per-key colour editor open, and it is what pairs with a
`0x23` colour upload.

**Beware when parsing captures.** A data block is whatever follows a header
with a non-zero block count, *positionally*. Do not classify by first byte:
effect payloads for ids `0x04`–`0x08` start with `0x04`, which reads exactly
like a command header and will silently corrupt an analysis.

**Timing.** Packets must not be issued back-to-back — with no gap the second
data block fails with `ETIMEDOUT`, and a reply read immediately after a command
returns the command echoed with the ack bit still clear. 2 ms was enough on the
test unit; the default is 10 ms, tunable with `--gap`. The vendor app leaves a
very uniform ~36.7 ms, which looks like Windows timer granularity rather than a
device requirement.

**Do not run this while the vendor app is open.** Both processes share the one
hidraw node, and the app polls `0xF5` continuously, so a `GET_FEATURE` here
picks up the reply to *its* poll instead of ours: commands come back as
`04 F5 00 FF`, replies desync, and reads time out. It took 9 attempts to open a
session under that contention. With the app closed, none of this happens — not
even while an effect is running on the keyboard, which was my first and wrong
explanation for it. Command headers are retried anyway so the tool degrades
gracefully; data blocks are never retried, since a retry mid-transfer could
corrupt an upload.

**Commit errors.** Committing a session that uploaded nothing replies with
`0xFF` in the ack byte instead of `0x01`.

## Capturing more from the vendor app

The vendor app runs under Wine, which routes the device through the Linux
kernel — so no Windows VM, no USBPcap, and the app and this tool can be
alternated against the same keyboard in seconds. Wine's `winedevice.exe`
(that's `winebus.sys`) is the process that holds the `hidraw` fds.

Two capture routes, in order of preference:

1. **`LD_PRELOAD` shim on `ioctl()`** — full 64-byte payloads, no root, no extra
   packages. This is how the protocol above was decoded. Note that `wineserver`
   must be *fully* dead before relaunching, or the new app attaches to the old
   un-shimmed `winedevice.exe` and the capture comes back empty.
2. **usbmon** (`sudo modprobe usbmon`, read `/sys/kernel/debug/usb/usbmon/<bus>u`)
   — catches everything regardless of syscall, but its *text* interface
   truncates data at 32 of 64 bytes. Use the binary interface via `tshark` if
   you need full payloads this way.

**The shim, built:** `capture/` in this directory holds the shim source
(`wine_ioctl_shim.c`), a build script, a launcher that kills `wineserver` and
preloads the shim into the vendor app, and a log parser:

```bash
cd tools/aula_l99_hacky/capture
./build_shim.sh                                        # → wine_ioctl_shim.so
./run_vendor_capture.sh effect_05                      # app + shim; log → logs/effect_05.log
python3 parse_shim_log.py logs/effect_05.log           # events in order, poll loop stripped
python3 parse_shim_log.py logs/effect_05.log --hex --dir OUT   # --send-hex-pasteable payloads
python3 parse_shim_log.py logs/effect_05.log --verify  # sessions byte-checked against protocol.py
```

The launcher has presets for the two settings-panel dropdowns — they print
the in-app steps before launching, and the parser's `--settings` mode
tabulates the resulting `0x17` rounds (per-write byte 6 = sleep-time /
byte 8 = response-time, with a changed-slot column); see
`re_notes/settings_write.md`:

```bash
./run_vendor_capture.sh response_time   # sweep Response Time 1 -> 5 in the app
python3 parse_shim_log.py logs/response_time.log --settings
./run_vendor_capture.sh sleep_timer     # sweep Sleep Time 0 -> 3 in the app
python3 parse_shim_log.py logs/sleep_timer.log --settings
# or one session covering both dropdowns:
./run_vendor_capture.sh settings
python3 parse_shim_log.py logs/settings.log --settings
```

`run_vendor_capture.sh` runs `wineserver -k` first (mandatory, see above), then
launches `Windows/AULA L99/DeviceDriver.exe` with `LD_PRELOAD` set to the shim
and `AULA_IOCTL_LOG` pointing at `logs/<name>.log`; quit the app to close the
capture. Name one log file per UI action. Every captured event is also echoed
to the terminal the app was launched from, so the live exchange is visible
while you change settings.

The shim logs only the AULA devices, resolved by VID/PID from sysfs (and the
keyboard's vendor interface 3): `0c45:800a` (cable), `05ac:024f` (dongle) and
`eeef:268a` (touchscreen ttyACM). Other hidraw devices are invisible to it —
otherwise every mouse report and keystroke would land in the log. Override the
list with `AULA_IOCTL_DEVICES="vid:pid[:iface],..."` (`*` logs everything).
Ioctls on the vendor channel carry the 65-byte report (`0x00` report-id byte
+ the 64-byte packet); the parser strips the report id, so its packets always
match `protocol.py`. The shim logs hidraw ioctls
(`HIDIOCSFEATURE`/`HIDIOCGFEATURE`, full payloads both directions) plus
`read`/`write` on the allowed nodes. Note it is built for the wine prefix's
architecture — a win32 prefix needs `-m32` (and `gcc-multilib`); this win64
prefix needs neither.

`strace` alone is not enough: it cannot dump `ioctl` argument buffers, and this
device is driven entirely by feature-report ioctls, not `write()`.

Capture one setting change at a time, and **verify the keyboard physically
changed** before trusting a capture — the vendor colour picker can snap to a
preset swatch instead of the value you typed.

### Verifying against a capture

`protocol.py`'s builders were checked against the captured packets by
generating each one and comparing bytes. Worth redoing whenever a builder
changes: parse a shim log into 64-byte payloads and assert, for example,
`build_command(OP_COLOR_SET, 9)` equals the captured `04 23` header and
`build_color_blocks(build_uniform_colors((0,0,0xFF)))` equals the nine blocks
that followed it.

## Prior art

- [Simon-Martens/F75_Initializer](https://github.com/Simon-Martens/F75_Initializer)
  — same VID/PID on the AULA F75 MAX; source of the dongle-path constants.
- [Salamor/aula-l99-open-widgets](https://github.com/Salamor/aula-l99-open-widgets)
  — the L99's separate `EEEF:268A` touchscreen.
