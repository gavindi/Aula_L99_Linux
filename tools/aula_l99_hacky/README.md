# aula_l99_hacky

Linux tool for the AULA L99's vendor HID channel (`0C45:800A` wired, `05AC:024F` 2.4G
dongle). This only covers the **keyboard-side HID protocol** — the touchscreen is a
separate `EEEF:268A` USB-serial device, already documented in
[Salamor/aula-l99-open-widgets](https://github.com/Salamor/aula-l99-open-widgets).

## Status

Confirmed on real hardware (wired `0C45:800A`, interface 3):

- Session framing, writing per-key RGB, and the RTC-set command.
- Every packet builder in `protocol.py` reproduces the vendor app's own packets
  byte-for-byte — see "Verifying against a capture" below.

Not yet known: how to select a lighting *effect*, brightness, macros, and
opcodes `0x13` and `0x00`. Effects run on the keyboard itself — the vendor app
polls `0xF5` ~27x/s to mirror the keyboard's current LED state in its preview,
rather than driving the lighting from the PC. The dongle path has never been
tested at all; its constants are inherited guesses from the AULA F75 MAX.

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

# set the keyboard's clock
python3 -m aula_l99_hacky.cli --rtc

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
| `0x28` | set RTC — `00 01 5a`, then Y M D h m s, weekday | 1 |
| `0x23` | write per-key colour                         | 9 out |
| `0xF5` | read back current per-key colour             | 9 in |
| `0x02` | commit; reply returns 16 bits at offset 4    | 0 |
| `0xF0` | end session                                  | 0 |
| `0x13` | unidentified                                 | 1 |
| `0x00` | unidentified                                 | 0 |

Data blocks flow *out* from the host for a write (`0x23`) and *back* from the
device for a query (`0xF5`). The command header looks identical either way, so
always check the direction of a captured packet before assuming it is a write.

**Colour blocks.** Nine blocks: eight key rows plus a zero-filled terminator.
Each row holds 16 entries of 4 bytes, `[key_id, R, G, B]`, where the entry's
position is the key id's low nibble and the block index is its high nibble.
Colour is plain RGB, passed through literally (verified with `#00FF00` →
`00 ff 00` and `#0000FF` → `00 00 ff`). The L99 has 84 keys in ids `0x00`–`0x7F`;
positions with no physical key are sent as four zero bytes.

**Timing.** Packets must not be issued back-to-back — with no gap the second
data block fails with `ETIMEDOUT`, and a reply read immediately after a command
returns the command echoed with the ack bit still clear. 2 ms was enough on the
test unit; the default is 10 ms, tunable with `--gap`. The vendor app leaves a
very uniform ~36.7 ms, which looks like Windows timer granularity rather than a
device requirement.

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
