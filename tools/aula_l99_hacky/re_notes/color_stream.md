# Realtime per-key colour stream (opcode 0x20)

Decoded from `wireshark_dumps/save_to_gif_18.pcapng`, a single capture of the
vendor app animating the keyboard from the host. Cable path (`0C45:800A`,
interface 3, 64-byte feature reports) — the same channel as colour, effect,
RTC and settings.

This is a **second colour-write path**, distinct from `OP_COLOR_SET` (0x23):
no session framing, a different key order, and no terminator block. Together
with the audio spectrum feed (`OP_AUDIO`, 0x78, decoded separately from
`save_to_gif_17.pcapng`) it makes the point that the begin/commit/end shape
and the matrix block layout are properties of *individual opcodes*, not of
the channel — `protocol.py`'s module docstring now says so. The two realtime
feeds are not even framed the same way as each other: the audio loop puts its
commit *before* the command, this one puts it *after*.

## Transaction shape

Steady state, repeated once per frame:

```
0x04 0x20 ..., byte[8]=8            -> ack (byte 3 flips 0x00 -> 0x01)
  8 data blocks (one frame, see layout below)
0x04 0x02 (COMMIT)                  -> ack
```

Two things to note against the paths already documented:

- **No `OP_BEGIN`, and no `OP_END` anywhere in the capture.** The write paths
  (`0x23`, `0x13`, `0x17`, `0x28`) are all wrapped in `begin ... commit, end`.
  This one is not wrapped in anything.
- **The commit comes *after* the data blocks.** In the `OP_COLOR_QUERY` (0xF5)
  poll loop the commit comes *first*, closing out the previous read before the
  next query. Here it closes out the frame that was just written. So "commit
  precedes the interesting command" is a fact about the query loop, not a rule.

245 frames over 16.1s. Median gap between consecutive `0x20` headers is
**58.7ms (~17 frames/s)** — `STREAM_FRAME_SECONDS`.

## Data block layout

The 8 blocks are **not** eight independent blocks; they are one flat 512-byte
array of 128 `[key_id, R, G, B]` quads, chopped into 64-byte reports. The
first **84 quads are the physical keys, packed with no gaps**; quads 84..127
are zero padding (all four bytes, id included).

There is **no `0xAA 0x55` trailer** in any block — not at offset 62..63 like
`OP_COLOR_SET`/`OP_RTC`, not at 14..15 like the effect block, not anywhere.
`TRAILER_OFFSET` would land mid-quad here, which is presumably why. (The
audio block drops the trailer too, so "realtime feeds don't carry one" is
now two opcodes rather than one, though still not a rule anything confirms.)

Compare with `OP_COLOR_SET`, which does the opposite on all three counts:
9 blocks, one per matrix row, each key at the column offset its id encodes,
plus a terminator block carrying the trailer.

### Key order

The 84 ids are exactly `protocol.KEY_IDS` — same set, no additions, no
omissions — but sorted into **visual reading order**: rows top to bottom, keys
left to right within a row. That was checked, not eyeballed: the capture's
order reproduces exactly by sorting the vendor layout XML's key rects by
`(rect_top, rect_left)`, i.e.

```python
sorted(KEY_RECTS, key=lambda k: (KEY_RECTS[k].top, KEY_RECTS[k].left))
```

which is the order a host-side animation would want to walk the keyboard in.
`protocol.py` hardcodes it as `STREAM_KEY_ORDER` rather than deriving it, to
keep `aula_l99_hacky` free of the GUI's layout XML; `tools/aula_l99_gui`
already asserts `light_index == key_id` across the same 84 keys, so the two
can be cross-checked if either ever drifts.

The order was byte-identical in all 245 frames, so it is fixed, not per-frame.
`parse_stream_blocks()` verifies each slot's id rather than trusting position,
so a frame in some other order raises instead of decoding into nonsense.

## What the capture actually animated

Exactly one key is ever non-black across all 245 frames: **`0x73`, the Pause
key**. The other 83 are transmitted every frame at `00 00 00`. Its colour
changes on nearly every frame — a hold at `#FE0000`, a linear fade down to
black, then a series of hue sweeps (`#000185` → `#00D7F3` → `#FE3400` …).

That is enough to establish the wire format and the frame rate, but it is a
thin sample in one respect: **only one key was ever lit at a time**, so
nothing here proves the device renders more than one non-black slot per frame.
There is no reason to expect it doesn't. It just hasn't been shown.

## Volatile or not

Untested, but 245 writes in 16 seconds is not something flash would survive,
so this path is almost certainly RAM-only — which is what makes it the right
one for a live GUI preview, where `OP_COLOR_SET` is not (it survives a replug,
so it writes flash). Confirming this needs one experiment: stream a frame,
replug, see whether it persists.

Also worth noting: **no `OP_EFFECT` (0x13) anywhere in the capture.** The
stream did not need `EFFECT_CUSTOM` selected first, unlike the `0x23` path,
which the vendor app pairs with an effect selection. Whether the stream
*overrides* a running built-in effect, or is ignored while one runs, is
untested — worth checking against the known interaction where `OP_COLOR_QUERY`
polling silently reverts a running effect.

## Timing

Within a frame the vendor app left only **~2.8ms between data blocks**, versus
the very uniform ~36.7ms it uses between packets everywhere else. Both figures
come from the same app on the same machine, so the 36.7ms is a host-side
artefact, not a device requirement — consistent with 2ms already being enough
on the test unit. Whole-frame budget from the capture: header→ack 6.6ms, 8
blocks at 2.8ms, ~9ms to the commit, commit→ack 6.3ms, ~16ms idle.

## RTC injected mid-stream

Four `OP_RTC` writes appear during the stream, ~5s apart, each stalling it for
~1.3s. They are framed `begin → 0x28 → block → commit` — and that commit is
the stream loop's own; there is no `end`. Their blocks carry **non-zero**
monitor data, which decodes cleanly against the offsets in
`system_monitor_block.md`:

```
00 01 5a 1a 08 01 06 01 24 00 06 00 00 06 2c 06 28 1a 22 19 00 5f
```

→ view 1, 2026-08-01 06:01:36, weekday 6 (a Saturday, which 2026-08-01 is),
CPU 6% / 44°, GPU 6% / 40°, air 26°, day high 34°, night low 25°, condition 0,
humidity 95%. An independent capture confirming that block a second time.

## Tooling note

Read with the same hand-rolled pcapng/USBPcap parser described at the bottom
of `settings_write.md` (`tshark` still isn't installed on this machine). One
addition worth recording: on OUT control transfers the 8-byte USB setup packet
sits *inside* the same captured payload, so the 64-byte report starts at offset
8 and the whole packet is 72 bytes; IN transfers put the setup in a separate
packet and the payload is a bare 64 bytes. Filtering on "length == 64" alone
therefore silently drops every host-to-device report.
