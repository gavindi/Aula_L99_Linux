# System-monitor / weather data (it rides in the RTC block, opcode 0x28)

Decoded from `wireshark_dumps/save_to_gif_16.pcapng`, cross-checked against
`Windows/AULA L99/DeviceDriver.exe`.

**This supersedes the "Not applicable to the touchscreen / system-monitor
feature" section of `settings_write.md`.** That section concluded the CPU/GPU
and weather feed had to be a separate, still-uncaptured protocol on the
panel's `EEEF:268A` CDC-ACM port. It isn't. There is no separate protocol:
the stats are nine extra bytes in the *clock* packet on the keyboard's own HID
feature-report channel, and the keyboard forwards them to the panel itself.
`OP_RTC` was never only an RTC write -- we had simply never captured it with a
non-idle payload.

## The capture

184 packets, 7.1 s, USBPcap on bus 2. One transaction on `0C45:800A`
(dev 19), the same 64-byte feature-report channel as everything else in
`protocol.py`:

```
+3.467  04 18 ...            BEGIN
+3.539  04 28 ... byte[8]=01 OP_RTC, one block follows
+3.611  <data block>
+3.683  04 02 ...            COMMIT
```

No `OP_END` -- the capture stops before it, rather than the app omitting it.

The touchscreen (`EEEF:268A`, dev 21, re-enumerating as dev 22 at +4.94 s)
contributes nothing but enumeration and a single CDC `SET_LINE_CODING`
(115200 8N1). Zero bulk transfers in the whole capture. Despite the filename
there is no GIF or image payload here either.

## The block

```
00 01 5a 1a 08 01 05 0e 32 00 06 00 00 06 2c 06 28 1a 22 19 00 5f
                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^
```
plus zeros out to the `aa 55` trailer at bytes 62..63.

Bytes 0..12 are exactly what `build_rtc_blocks()` already emits, and the
capture re-confirms them independently: `5a` tag, year 26, month 8, day 1,
05:14:50, weekday 6. The capture's own wall clock is 2026-08-01 05:14:46
local and 2026-08-01 was a Saturday, so both the time and the weekday field
check out.

Bytes 13..21 are the new part. `build_rtc_blocks()` zeroes all nine.

| offset | value here | field |
|---|---|---|
| 13 | 0x06 = 6   | CPU load %          |
| 14 | 0x2C = 44  | CPU temperature     |
| 15 | 0x06 = 6   | GPU load %          |
| 16 | 0x28 = 40  | GPU temperature     |
| 17 | 0x1A = 26  | current air temp     |
| 18 | 0x22 = 34  | day high temp       |
| 19 | 0x19 = 25  | night low temp      |
| 20 | 0x00 = 0   | weather condition code |
| 21 | 0x5F = 95  | humidity %          |

### The rest of the block is dead space

Bytes 9, 11, 12 and 22..61 are not merely zero in this capture -- the vendor
app never writes them at all. Its builder `memset`s the whole 65-byte buffer
and then fills exactly offsets 0..8, 10, 13..21 and the 62..63 trailer, so 43
of the 64 bytes are untouched. The clock plus the nine monitor values is the
entire payload; there is no further parameter hiding in here.

One lead in that space. The app calls `GetLocalTime` into a `SYSTEMTIME` and
reads `wYear`, `wMonth`, `wDayOfWeek`, `wDay`, `wHour`, `wMinute`, `wSecond`
from it -- but pointedly not `wMilliseconds`, which is right there in the same
struct. Byte 9 is the one unwritten byte immediately after seconds. A
sub-second field the firmware may accept but the app declines to fill is the
obvious reading, though nothing tests it. Bytes 11..12, between weekday and
CPU load, have no equivalent story: alignment padding is as likely as a field
this app build doesn't use.

Both caveats that apply everywhere in this note apply here too: one code path
in one app build, and only views 1, 2, 3 and 5 have ever been exercised on the
panel.

## Where the vendor app gets each field

Two independent sources, merged into the one block.

**Hardware (bytes 13..16).** `DeviceDriver.exe` launches
`%s\HardwareMonitor\OpenHardwareMonitorServer.exe` (a .NET app over
`LibreHardwareMonitorLib.dll`), which publishes to `data.ini`. The driver
reads four keys back out of `[Hardware]` -- `CPU`, `CPU_Temperature`, `GPU`,
`GPU_Temperature`, in that order -- runs each through `_wtoi`, and stores the
**low byte only**, so any value over 255 wraps.

Note that `data.ini` also carries `Network_Upload` and `Network_Download`.
Neither is read into this block. If the panel can show network rates, it is
not through these nine bytes.

**Weather (bytes 17..21).** Fetched from
`https://api.ip138.com/weather/?&type=1&token=93901c1a610552b6e1eeef6749fd602e`
and scraped with two regexes, `"<key>":\s*([0-9.]+)` for numbers and
`"<key>":\s*"([^"]*)"` for strings. Keys used: `temp`, `dayTemp`,
`nightTemp`, `humidity`, `dayWeather`.

`dayWeather` comes back as Chinese text and is reduced to a small code by
substring search:

| code | matched substring |
|---|---|
| 0 | 云 (cloud) |
| 1 | 晴 (clear) |
| 2 | 小雪 (light snow) |
| 3 | 雷 (thunder) |
| 4 | 雨 (rain) |
| 5 | 大雪 (heavy snow) |

Order matters and is not a priority ranking -- it is just the order the app
tests in, first match winning, except that 大雪 is applied last and overrides
an earlier hit. So 晴间多云 ("clear, partly cloudy") scores 0, not 1, because
云 is tested first. A string matching nothing leaves the code at 0 as well,
which makes 0 ambiguous between "cloudy" and "unrecognised".

## Byte 1 is not the constant we assumed

`protocol.py` hardcodes `block[1] = 0x01`. The app computes it as
`MUI::LCDViewList::GetCurSel() + 1` -- the index of the selected screen
page/view in the app's own list, 1-based. `0x01` is therefore "first view",
not a fixed tag.

Tested on the panel on 2026-08-02, with the panel held on the real-time frame
for the whole session and each value sent once (single shots are reliable;
see below):

- **view 0 is ignored.** Neither single shots nor fifty streamed sends changed
  anything on the panel. The byte is a 1-based index, so 0 is outside its
  domain, which matches `GetCurSel() + 1` never producing it.
- **views 1, 2, 3 and 5 all land identically** on the same real-time readout
  frame. The byte does not switch the panel's screen (view 1 sent while on a
  different screen changed nothing there), and it does not select among
  frames: any value >= 1 routes to the one frame that shows this data. Whether
  values above 5 behave the same is untested, but nothing observed suggests
  the panel distinguishes among them.

## A retest corrected an earlier packet-loss theory

An earlier session concluded that a single `--rtc` send often fails to reach
the panel -- the keyboard acks every packet, but five single sends of the same
values changed nothing, while streaming them (231 sends / 30 s) updated the
panel. That looked like lossy keyboard-to-panel forwarding.

A controlled retest on 2026-08-02 disproved it. With the panel fixed on the
real-time frame and the view byte the only variable, **seven single shots in a
row all landed** (views 1, 2, 3 and 5, then view 1 three more times with
distinct values, all confirmed on the panel). The earlier "loss" was a
screen-state confound: a single send only shows up when the panel is
displaying the real-time frame, and during those earlier sends it evidently
wasn't. The view byte does not summon the frame or select a screen, so a send
that is not visible is not a lost packet -- the panel is just looking at a
different screen. `--rtc-stream SECS` remains useful for a live readout that
keeps refreshing, as the vendor app's ~1 Hz stream does, but it is not a
reliability workaround.

## Confidence

**Confirmed on real hardware.** All nine field assignments in the table above
were verified by writing distinctive values through
`aula_l99_hacky`'s `--rtc` and reading the panel:

```
--rtc --cpu-load 88 --cpu-temp 77 --gpu-load 66 --gpu-temp 55 \
      --air-temp 11 --day-high 22 --night-low 9 --condition rain --humidity 44
```

Every field landed where this note says it does. That takes bytes 13..21 out
of the "decoded from one capture" category -- the offsets, the CPU-before-GPU
and load-before-temperature ordering, and the condition code are all real.

Also confirmed, from the capture rather than the panel: the transaction shape,
the block's byte 0..12 layout (independently, against wall clock), and the
`aa 55` trailer position.

Still untested, and deliberately not upgraded by the run above:

- **Views above 5.** Views 1, 2, 3 and 5 are confirmed identical in routing
  and view 0 is confirmed dead; whether the panel owns any layout that a
  higher value selects (or whether it distinguishes among values at all)
  remains unknown.
- **The upper end of each range.** Nothing establishes what the panel does with
  a load above 100 or a nonsense condition code.

**Negative temperatures were the open question here, and a real-hardware test
has since answered it: the panel renders them as garbage.** On 2026-08-02,
`--air-temp -1` put `0xFF` on the wire (exactly what the vendor app's
`_wtoi`-then-low-byte-store would produce) and the panel displayed "55" — the
low two digits of 255, not -1. The temperature fields are unsigned on the
firmware side: the byte is displayed literally, so any negative value shows up
as a 250-something wrap. The CLI therefore rejects negative temperatures now,
rather than silently sending a byte the panel cannot render. The protocol
builder still accepts them — the two's-complement encoding is tested and
faithful to the vendor app — for capture reproduction and the `--send-hex`
path.

Do not use the repo's checked-in `Windows/AULA L99/data.ini` as
corroboration. It reads `CPU=21 CPU_Temperature=42 GPU=7
GPU_Temperature=44`, which does not match the captured bytes -- the file was
copied at some unrelated moment, not during this capture. Its
`GPU_Temperature=44` colliding with the captured byte 14 is a coincidence of
two temperatures both being in the 40s, not a sign the CPU/GPU order is
flipped; the read order is unambiguous in the code.

## The 2.4G dongle path

A second code path builds the same field set for the dongle transport
(`05AC:024F`), sending one 33-byte packet instead of the 65-byte feature
reports, with every field shifted +4 -- year at 7, hardware at 17..20,
weather at 21..25, trailer at 26. Consistent with the dongle framing carrying
a 4-byte prefix. Never captured, so treat those offsets as a lead rather than
a layout.

**This contradicts the dongle packet `protocol.py` already had.** That one
comes from F75_Initializer prior art and puts the tag at 4..5, the clock at
6..11 and `AA 55` at 17..18 -- a shift of +3, not +4, and its trailer sits
exactly where the vendor layout puts the first monitor byte. The two disagree
by one byte throughout, so no splice of them is a packet either source
supports; at least one reading is wrong.

`build_dongle_rtc_packet()` therefore switches layout on whether monitor data
was supplied: prior art unchanged for a clock-only write, the vendor's +4
layout when there are monitor fields to place. Not a design, just a way to
avoid silently corrupting the one of the two that someone might have been
relying on. Since the prior art is from a *different keyboard* and the +4
reading is this device's own code, the +4 layout is the better bet -- but no
L99 dongle has ever been tested, so whoever gets one should expect to try both.

## Applying this

`build_rtc_blocks()` now takes an optional `MonitorData` and a `view`, and the
CLI exposes both:

```
python3 -m aula_l99_hacky.cli --rtc --cpu-load 42 --cpu-temp 55 \
    --air-temp 26 --day-high 34 --night-low 25 --condition rain --humidity 95
```

Add `--rtc-stream 30` to keep the values refreshing for a live readout, the
way the vendor app streams at ~1 Hz. A single send already updates the panel
while it is showing the real-time frame (see the retest section).

Values are explicit on purpose, and that is what let the field assignments be
confirmed: sending a byte you chose is the only way to see which cell of the
panel it lands in. `tests/test_protocol.py` additionally reproduces the
captured block byte-for-byte from those nine values, pinning the builder to the
vendor app's own output.

Omitting every flag leaves the nine bytes zero, so a bare `--rtc` and the
GUI's "Set Clock to Now" both still emit exactly the block they emitted before
any of this was known.

The GUI does not populate these yet. Doing so means giving it a stats source
(`psutil` for load, `/sys/class/hwmon` or `lm-sensors` for temperatures) and,
for the weather half, deciding whether to call out to a network API at all.
Note also that `OP_COLOR_QUERY` polling is known to disturb a running effect
(see the colour-poll notes), so a periodic monitor write on the same handle
needs to be sequenced behind the poll thread the way `_pending_write` already
does for RTC writes.
