# Settings-panel write (opcode 0x17)

Decoded from three captures: `wireshark_dumps/response_time_1.pcapng`,
`wireshark_dumps/sleep_time_1.pcapng`, `wireshark_dumps/profile_read_1.pcapng`.
Parsed with a hand-rolled pcapng/USBPcap reader (no `tshark` on the analysis
machine) — see the packet-block layout note at the bottom if this needs
redoing.

All three are the cable path (`0C45:800A`, bus 2 device 6, interface 3,
64-byte feature reports), same channel `protocol.py` already documents for
colour/effect/RTC. This is a second, previously-undocumented command family
on that same channel, for the vendor app's settings dropdowns (response time,
sleep timer). It fits the existing `CMD_PREFIX 0x04 <opcode>` /
`begin -> command -> data blocks -> commit -> end` session shape from
`protocol.py` exactly — nothing here contradicts that model, it just fills in
one more opcode.

## Transaction shape

```
BEGIN   (0x04 0x18 ...)                    -> ack (byte 3 flips 0x00 -> 0x01)
SETTINGS_WRITE (0x04 0x17 ..., byte[8]=1)  -> ack
  1 data block (see layout below)
COMMIT  (0x04 0x02 ...)                    -> ack, byte[4:6] = sequence counter
... repeat BEGIN..COMMIT once per value the user changes on the panel ...
END     (0x04 0xF0 ...)                    -> ack
```

`OP_SETTINGS_WRITE`'s command header is byte-for-byte identical in both
captures (`04 17 01 00 00 00 00 00 01`), regardless of which dropdown changed —
it just means "one settings block follows," same as `OP_COLOR_SET`/`OP_RTC`
declaring their own block counts. Note byte 2 = `0x01`: no other command sets
it. It was confirmed against a live capture from the vendor app under Wine
(the capture shim, which also showed the vendor's ioctls carry the 65-byte
report — `0x00` report-id byte plus the 64-byte packet). `build_command()`
now takes a `byte2` argument for this.

## Data block layout

64 bytes, `0xAA 0x55` trailer at the default offset 62..63 (not the special
14..15 offset the effect block uses). Only two fields vary across both
captures; everything else observed was constant zero:

```
[0]    0x00               (constant, purpose unknown -- maybe a sub-type tag)
[1]    0x01               (constant, ditto)
[6]    sleep-time value, 0..3
[8]    response-time value, 1..5
```

The sleep-time byte is fully decoded: 0 = no sleep, 1 = 1 minute, 2 = 5
minutes, 3 = 30 minutes — the vendor app's own dropdown labels
(`protocol.SLEEP_TIME_MINUTES`). The response-time byte is fully decoded
too: the levels 1..5 carry the vendor app's documented per-link delays
(`protocol.RESPONSE_TIME_DELAYS_MS`) — level 1 ≈ 2-3 ms wired / 5-6 ms
2.4GHz / 12-13 ms Bluetooth, rising to level 5 ≈ 17-18 / 19-21 / 27-28 ms
(the app calls these "approximately", noting switch type and environment
shift them).

Both fields are present in *every* write, not just the one the user is
changing -- this looks like the vendor app applies the whole settings panel
as one unit rather than one field at a time. Cross-validated between the
captures: `response_time_1` ends with byte[8] (response-time slot) at its
last-known value; `sleep_time_1`, captured afterwards, opens with that exact
same byte[8] held constant across all 4 of its own rounds while byte[6]
(sleep-time slot) sweeps instead. If these were two independent single-field
writes at different offsets, that carry-over wouldn't line up.

Evidence (block bytes, 0-indexed, after stripping the report):

| capture | byte[6] (sleep-time) | byte[8] (response-time) |
|---|---|---|
| `response_time_1`, 5 rounds | `02` constant | `01,02,03,04,05` |
| `sleep_time_1`, 4 rounds | `00,01,02,03` | `05` constant |
| `sleep_timer.log` (capture shim), 14 writes | `01,02,00,01,02,03,0,1,2,3...` sweeping | `01` constant |
| `response_time.log` (capture shim), 11 writes | `02` constant | `01,02,03,04,05,01,02,03,04,05,01` |

The shim captures settle the slot assignment. The sleep-timer capture holds
the Sleep Time dropdown being stepped: byte[6] swept the four-value range
`0..3` (exactly the app's sleep options, including 0 = no sleep) while
byte[8] held `01` the whole time. The response-time capture is the mirror
image: byte[8] swept `1..5` while the Response Time dropdown moved through
its five levels and byte[6] held `02` (sleep still at 5 minutes). Earlier
notes had this mapping backwards (they assumed the capture names were
swapped); the names were right all along. Both slots are now fully decoded:
sleep meanings in `protocol.SLEEP_TIME_MINUTES`, response levels in
`protocol.RESPONSE_TIME_DELAYS_MS`.

## Commit reply counter

`OP_COMMIT`'s reply carries a 16-bit little-endian value at offset 4..5.
`protocol.py` previously guessed this was a checksum. Across all three
captures it increments by exactly 1 on every single commit, independent of
what the payload was -- e.g. response_time_1 saw `0x0103, 0x0104, 0x0105,
0x0106, 0x0107` back to back. That rules out a checksum; it's a plain
monotonic sequence/generation counter, presumably so the app can confirm a
specific commit landed rather than an older one still being in flight.
Corrected in `protocol.py`'s module docstring.

## profile_read_1 -- related but not deciphered

Same session shape, but the command opcode after `BEGIN` is `0x11` (not
`0x17`), and a later round in the same capture uses `0x27` instead. Both
carry `byte[8]=0x09` (9 blocks). This is almost certainly the profile-list
read path (`profile_read` = enumerating saved profile slots), but the
9-block payloads weren't decoded here -- next step if this matters is a
capture that reads back only one or two profile slots in isolation, since
`profile_read_1` mixes several read cycles together.

## Not applicable to the touchscreen / system-monitor feature

**Superseded -- see `system_monitor_block.md`.** The conclusion below was
drawn from `system_monitor_2.pcapng`, which turns out to contain nothing but
device enumeration. `save_to_gif_16.pcapng` shows the CPU/GPU/weather feed
does travel over this HID feature-report channel after all: it is nine extra
bytes in the `OP_RTC` (0x28) data block, which we had only ever captured with
those bytes idle. There is no separate touchscreen protocol for it.

The part that still holds: the touchscreen is a separate `EEEF:268A` CDC-ACM
USB-serial device (`/dev/ttyACMn`), covered by `tools/aula_l99_screen`, and
none of the `0x17`/`0x11`/`0x27` opcodes above have anything to do with the
monitor data. What was wrong was the inference that the panel being a separate
device meant the *data* had to reach it over that device's own port -- the
keyboard receives it and forwards it.

## Recapturing with the shim

The open question above — byte[6] vs byte[8] mapping — is exactly what the
`capture/` tooling in this repo is for (see the README's "Capturing more from
the vendor app"). The old captures came from a Windows box with USBPcap; the
vendor app runs under Wine here, so the same sweeps were redone with the
shim in minutes. Both sweeps have since answered it (byte 6 = sleep-time,
byte 8 = response-time, meanings in `protocol.SLEEP_TIME_MINUTES` /
`protocol.RESPONSE_TIME_DELAYS_MS`):

```bash
cd tools/aula_l99_hacky/capture
./run_vendor_capture.sh response_time   # in the app: Response Time 1 -> 2 -> 3 -> 4 -> 5
python3 parse_shim_log.py logs/response_time.log --settings
./run_vendor_capture.sh sleep_timer     # in the app: Sleep Time 0 -> 1 -> 2 -> 3
python3 parse_shim_log.py logs/sleep_timer.log --settings
```

`--settings` prints one row per `0x17` write: both slots, which one changed
since the previous write, and any block anomaly (bad trailer, nonzero bytes
outside the known fields). Because every write carries both slots, either
sweep alone identifies the slot that moves; doing both cross-validates. The
sleep-timer sweep already settled it: byte 6 = sleep-time (0..3, meaning in
`protocol.SLEEP_TIME_MINUTES`), byte 8 = response-time (1..5, meaning
unknown).

## Tooling note

`tshark`/`pyshark` aren't installed on the analysis machine. These captures
were read with a ~40-line pure-Python pcapng block parser (SHB/IDB/EPB) plus
a USBPcap `usbpcap_buffer_header` parser (2-byte headerLen, 8-byte irpId,
4-byte status, 2-byte function, 1-byte info, 2-byte bus, 2-byte device,
1-byte endpoint, 1-byte transfer type, 4-byte dataLength, then payload).
Control transfers carry an 8-byte USB setup packet immediately after that
header when there's a data stage. Worth turning into a small script under
`tools/` if more captures need this treatment -- currently it only exists as
scratch code from this session.
