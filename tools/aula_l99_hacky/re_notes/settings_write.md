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
captures (`04 17 01 00 00 00 00 01`), regardless of which dropdown changed —
it just means "one settings block follows," same as `OP_COLOR_SET`/`OP_RTC`
declaring their own block counts.

## Data block layout

64 bytes, `0xAA 0x55` trailer at the default offset 62..63 (not the special
14..15 offset the effect block uses). Only two fields vary across both
captures; everything else observed was constant zero:

```
[0]    0x00               (constant, purpose unknown -- maybe a sub-type tag)
[1]    0x01               (constant, ditto)
[6]    response-time value, 1..5
[8]    sleep-time value, 0..3
```

Both fields are present in *every* write, not just the one the user is
changing -- this looks like the vendor app applies the whole settings panel
as one unit rather than one field at a time. Cross-validated between the two
captures: `response_time_1` ends with byte[8] (sleep-time slot) sitting at
its last-known value; `sleep_time_1`, captured afterwards, opens with that
exact same byte[8] held constant across all 4 of its own rounds while
byte[6] (response-time slot) sweeps instead. If these were two independent
single-field writes at different offsets, that carry-over wouldn't line up.

Evidence (block bytes, 0-indexed, after stripping the report):

| capture | byte[6] (response-time) | byte[8] (sleep-time) |
|---|---|---|
| `response_time_1`, 5 rounds | `02` constant | `01,02,03,04,05` |
| `sleep_time_1`, 4 rounds | `00,01,02,03` | `05` constant |

Not yet known: what byte[6]=`02` constant during the response-time test
actually means (it never changed, so it's not confirmed as "the value" —
could equally be a fixed category tag with the real response-time value
living somewhere unexamined). The safer reading is: byte[8] is confirmed as
the sleep-time value (0..3, cross-validated); byte[6] is very likely the
response-time value (1..5) but only single-capture evidence supports it.

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

Confirmed while investigating `system_monitor_2.pcapng`: the touchscreen is
a *separate* `EEEF:268A` CDC-ACM USB-serial device (`/dev/ttyACMn`), already
covered by `tools/aula_l99_screen`. It does not go through this HID
feature-report channel at all, so none of the opcodes above apply to
CPU/GPU/weather data -- that protocol is still uncaptured.

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
