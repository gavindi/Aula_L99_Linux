# aula_l99_screen

Linux tool for the AULA L99's **touchscreen** (`EEEF:268A`) — a CDC-ACM
USB-serial device that appears as `/dev/ttyACMn`. This is a different device
from the keyboard's vendor HID channel; nothing in `aula_l99_hacky` applies
here, and the two share no code.

## Status

Image upload works, confirmed on real hardware for both `--target
photo-frame` (the default) and `--target background`: 154 packets, every one
acked by the panel, image visible afterwards. The panel may need a restart
before it redraws from flash.

Not implemented: touch input, brightness, screen power, `--target gif`.

## Usage

No root needed if you are in the `dialout` group.

```bash
# find the panel by VID/PID
python3 -m aula_l99_screen.cli --list

# upload an image (any format Pillow reads; resized to 320x480 automatically)
python3 -m aula_l99_screen.cli --upload picture.png
python3 -m aula_l99_screen.cli --upload picture.png --target background

# just build the .bin the panel expects, without touching hardware
python3 -m aula_l99_screen.cli --convert picture.png -o picture.bin
python3 -m aula_l99_screen.cli --describe picture.bin
```

## Upload destinations

The vendor app's own string table (`Windows/AULA L99/language/1033.lan`
#866-868) names three upload actions: "Save to GIF", "Save to BKG" and "Save
to photo frame". Two are supported here, both using the identical wire
protocol and image format below — only the flash base address differs:

| `--target`    | flash base   | status                 |
|---------------|--------------|------------------------|
| `photo-frame` | `0x041E0000` | confirmed on hardware  |
| `background`  | `0x04180000` | confirmed on hardware  |

`--address` overrides `--target` if you want to experiment with other
locations. `0x04240000` is "Save to GIF"'s address (see below); one more slot
the vendor binary references, `0x04200000`, is still unidentified.

### Save to GIF (unimplemented)

`0x04240000` is confirmed as the "Save to GIF" flash address — independently,
from thirteen captures: `wireshark_dumps/save_to_gif_1.pcapng` (a real photo
GIF), `save_to_gif_2.pcapng` (3 solid red/green/blue frames),
`save_to_gif_3.pcapng` (2 frames, both solid red except one white pixel at
`(0,0)` — top-left), `save_to_gif_4.pcapng` (the same pair, white pixel moved
to `(319,479)` — bottom-right), `save_to_gif_5.pcapng` (the same red
frame 1, but frame 2 is a clean 50/50 vertical split — left half red, right
half blue), `save_to_gif_6.pcapng` (a 3-frame version of `save_to_gif_5`
where the split frame repeats unchanged), `save_to_gif_7.pcapng` (a
red/blue/red vertical triple stripe), `save_to_gif_8.pcapng` (four
distinct-colored vertical stripes), `save_to_gif_9.pcapng` (a black/white
grid, shifted one pixel in frame 2), `save_to_gif_10.pcapng` (eight
distinct-colored vertical stripes, including gray), `save_to_gif_11.pcapng`
(the same eight colors, reordered so gray is first), `save_to_gif_12.pcapng`
(black and orange, testing the dithering boundary), and `save_to_gif_13.pcapng`
(light gray and dark red, following up). There is still no `--target gif`,
because the pixel payload format isn't understood well enough to safely
construct one, but the core row-grammar is now solved (see below). What's
known:

- Same wire protocol/framing as the other two targets. The final short data
  chunk's `cmd` byte, previously a mystery, is solved: `cmd = CMD_WRITE +
  (payload_len % 256)`, not a fixed opcode. This mapping is many-to-one,
  though — different lengths can share a `cmd` byte — so the matching CRC
  init is keyed by the actual payload length, not by `cmd`; two collisions
  (312 vs. 1080 bytes both giving `cmd=0x3F`, 248 vs. 2040 bytes both giving
  `cmd=0xFF`) confirmed this needed fixing, not just documenting. There's no
  known general formula relating length to its CRC init, so this doesn't
  unlock arbitrary upload sizes — see `final_chunk_cmd()` and `CRC_INIT` in
  `protocol.py`.
- The blob is a small table-of-contents header (20 bytes per frame). Its
  per-entry checksum field is **solved**: `crc16_modbus()`, the same function
  already used for the single-image header, confirmed byte-exact in nine of
  the ten captures. `save_to_gif_3` resolved an earlier ambiguity: byte 12
  is a constant format/version tag, byte 13 is the real frame count. Bytes
  16-17 are the inter-frame delay — every capture so far reads 50, which
  looked like it could just be the vendor UI's shared default until the
  user confirmed they explicitly set the frame speed to 50 when generating
  `save_to_gif_13`, matching the wire value exactly. The unit (likely
  centiseconds, GIF's own convention) is still unconfirmed — no capture
  with a different speed setting exists yet.
- Each frame has its own ~24-byte sub-header, including the self-referential
  frame byte length and a pair of RGB565 color fields: one holds the color of
  the frame's first pixel in raster order, the other holds the "other" color
  present (if any). Consistent across `save_to_gif_3`, `4` and `5`, but still
  doesn't explain `save_to_gif_2`'s solid frames, whose single color sits in
  the "other" slot instead — unexplained.
- **528 bytes of zero right after the sub-header, confirmed genuinely
  fixed.** `save_to_gif_5` answers the question this round set out to ask:
  even with 50% of the frame a different color (vs. one pixel in the earlier
  tests), that boundary is still exactly 528 bytes. Strong evidence of a
  fixed table (Huffman/quantization-style, as in JPEG) independent of image
  content, ahead of a variable-length entropy-coded section.
- **First real structure found in that entropy-coded section.**
  `save_to_gif_5`'s split-color frame content is exactly 1920 bytes = 480
  rows × 4 bytes, and is a single 4-byte unit repeated identically all 480
  times (`9F 00 9F 01`). `0x9F` = 159 = 160−1, exactly the length of each
  color half minus one — strong evidence the first byte of each 2-byte
  sub-unit is a run length stored as length−1. The reference solid-red
  frame's content (1200 bytes = 600 × `FF 00`) fits the same reading: 600
  tokens × (255+1) = 153600, exactly the pixel count. But the second byte
  (0 for the red half, 1 for the blue half here) doesn't obviously reconcile
  with `save_to_gif_3`/`4`, where the equivalent byte flips once at the
  point of divergence and then *stays* flipped for hundreds of bytes across
  many rows, rather than alternating back per row the way a clean color
  index would. Unresolved.

**Live hardware testing, no capture file this time.** With the panel plugged
directly into Linux, `save_to_gif_5`'s reconstructed blob was sent straight
to the panel with `build_upload()` and it rendered the correct half-red/
half-blue split — the first time our own code's *output*, not just its wire
bytes, was confirmed correct, rather than just matching a Windows capture.

From that known-good blob, three single-byte mutations were tried, each
re-uploaded (with the TOC `crc16_modbus` checksum recomputed to match) and
each reverted afterward by re-uploading the original:

1. The blue half's flag byte in row-token 240 of 480, `1 → 0`.
2. The same flag byte in row-token 479 — the very *last* row, where the
   changed byte is literally the last byte of the whole upload.
3. The *other* sub-token's flag in row-token 240, the opposite direction,
   `0 → 1`.

All three produced the exact same result: not a localized change, and not
three different glitches, but the identical different, smaller GIF playing
centered on screen every time. That's a poor fit for "wrong byte count
consumed, decoder reads whatever's next in flash" — attempt 2 in particular
shouldn't have had anywhere to run off to, being the last byte of the
stream, and a raw overread would more plausibly land somewhere different
each time rather than reproducing identically. It fits much better with the
panel validating the uploaded content somehow (not the TOC-level checksum,
which was correct each time and still acked normally) and falling back to a
fixed, previously-cached animation on failure, rather than rendering bad
data or erroring visibly.

A fourth experiment broke that "all-or-nothing" pattern, and produced the
first real win: instead of touching a flag byte, row-token 240's two
*length* bytes were changed from `(159, 159)` — a 160/160 pixel split — to
`(99, 219)` — a 100/220 split, still summing to 320 (the panel width),
flags left untouched. This time the panel did **not** fall back. It
rendered the normal image with the red/blue boundary visibly notched inward
for exactly one row — confirmed by photo to sit almost precisely at the
panel's vertical midpoint, matching row 240 of 480 exactly. First
controlled, predicted, position-correct change to rendered content in this
whole investigation, and direct confirmation of the run-length-as-length-
minus-one reading, rather than an inference from byte patterns alone.

So the panel's validation looks narrower than "any change fails" — more
like it cares that each row's lengths still sum correctly (320 either way,
so this edit passed) rather than rejecting any deviation. What the flag
bytes need to satisfy is still open, since every flag-only edit has failed
regardless of position or direction. (One operational note: a restore
attempt right after this experiment silently didn't take — the panel kept
showing the fallback GIF despite a clean, acked re-upload of the known-good
blob — and an identical second re-upload fixed it. Possibly a read/write
race if the panel was still mid-loop reading the region being overwritten;
worth a retry before concluding a change had no effect.)

A fifth experiment tried to tell apart two readings of the flag byte that a
2-run row can't distinguish between (a per-run color index and a
continue/last framing bit look identical when there are only ever 2 runs,
indexed 0 and 1). Row 240 was rewritten as **three** runs — 100px red,
100px blue, 120px red, still summing to 320 — with continuation-style flags
`(0, 0, 1)`. This grows the row from 4 to 6 bytes, so the frame's size
fields, both TOC entries, and the checksum were all recomputed, and the
wire transfer was padded with trailing zero bytes to the next multiple of
2048 so every packet stayed a plain, already-verified `cmd=0x07` write.
Result: the fallback animation again. A control upload — the *original*,
unmodified blob with the same kind of zero-padding and nothing else changed
— rendered correctly, ruling out the padding itself as the culprit.

A sixth experiment resolved this cleanly, by **swapping** row 240's two
flag bytes instead of setting them to a new value —
`(0x9F,0x00)(0x9F,0x01)` → `(0x9F,0x01)(0x9F,0x00)`, same lengths, same
160/160 split, just the two flags exchanged. This rendered correctly, not
the fallback — with the boundary in exactly the same place as always, but
that one row's **colors visibly swapped** (confirmed by photo: a thin
horizontal line at row 240 reading inverted relative to every row above and
below it). That directly confirms the flag byte **is** a per-run color
index, selecting between the sub-header's two RGB565 color slots —
contradicting the "fixed positional marker" guess above.

Four data points on this one row: `(0,1)` (original) renders normally;
`(1,0)` (swapped) renders correctly with that row's colors inverted; `(0,0)`
and `(1,1)` (0.5.7's two mutations) both fail to the fallback. The pattern
isn't "must equal a specific value in a specific position" — it's that a
row's two runs must use two *different* color indices, one 0 and one 1, in
either order; using the same index twice fails. That also reframes the
three-run failure: with only two possible flag values, a three-run row can
never give all three runs different indices from each other — some pair is
forced to repeat, which this same rule would reject regardless of whether
rows can otherwise hold more than two runs. So "rows are hardcoded to
exactly two tokens" may not be the real constraint after all — "a row's
runs must cover each of the frame's colors exactly once" fits all six
results at once, including the failed three-run attempt, with no separate
token-count rule needed. Consistent with a real encoder simply never
emitting two consecutive same-colored runs in one row (it would merge them,
or use the continuous-run encoding solid frames use instead) — so the
decoder may never have been built to tolerate it.

A seventh experiment confirmed the palette reading comprehensively: with
**no row data touched at all**, the sub-header's two RGB565 color fields
were changed from red/blue (`0xF800`/`0x001F`) to green/yellow
(`0x07E0`/`0xFFE0`). The whole frame rendered in the new colors — not just
row 240, every one of the 480 rows correctly resolved the new palette.
Confirms the color-index mechanism is a real, uniformly applied per-frame
palette, not something specific to one row or hardcoded elsewhere.
(Incidentally, this also made obvious the 2-frame animation had been
alternating with frame 1 — unmodified solid red — the whole time; easy to
miss when frame 1's red and frame 2's red-left half looked similar, obvious
once frame 2 turned green/yellow.)

An eighth experiment (frame 1's content replaced with a byte-for-byte copy
of frame 2's proven split) and a ninth (a hand-built 3-frame blob: solid
red, split, split again via an exact copy) both produced the fallback
animation. At the time these were read as evidence for frame index
selecting the decode routine, and/or a sequential delta encoding between
frames. Both experiments padded the wire transfer with trailing zero bytes
to reach a round multiple of 2048, to avoid needing an unsolved CRC value
for a new final-chunk length — which turned out to matter.

**`save_to_gif_6.pcapng` overturns that reading.** It's a real,
vendor-generated 3-frame capture — solid red, split, split again
*unchanged* — captured specifically to see what "no visible change between
frames" looks like from the real encoder. Its frame 1 and frame 2 are
**byte-for-byte identical**: the real encoder just re-emits a frame's full
content verbatim when nothing changes. There's no delta or no-op token to
find. Its frame 1 is also byte-identical to `save_to_gif_5`'s frame 1 (the
same split, independently captured), confirming the encoder is
deterministic and content-driven. And the reconstructed blob from
experiment nine — built by hand, before this capture existed — turned out
to be byte-for-byte identical to what `save_to_gif_6.pcapng` actually
contains. The only difference was packetization: the real capture ends in
a genuine 540-byte final chunk (now solved: `cmd 0x23`, init `0xA9BB`),
while the experiment padded to avoid needing that unsolved value.
Confirmed on real hardware: `save_to_gif_6`'s capture renders correctly.

**Confirmed directly** once the panel was back on Linux: re-sent as a
proper, unpadded upload — the same 5 packets as `save_to_gif_6.pcapng`,
byte-for-byte — the exact content that failed padded in experiment 9
rendered correctly, the full 3-frame animation playing as expected. Same
bytes, only the packetization differed. Padding — not frame index, not a
delta requirement — was the cause, and by the same logic likely explains
experiment 8's failure too.

That makes padding's status genuinely inconsistent rather than simply
"unsafe": the padding-only control from earlier (padding the working
2-frame blob with no other change) rendered correctly, while this padded
3-frame content did not, despite using the identical technique. Padding
isn't reliably safe for further experiments — prefer real captures or
exact, unpadded packetization over it going forward.

### RESOLVED: the row-grammar is a continuous run-length encoding

`save_to_gif_7.pcapng` supplied exactly the missing piece — a real capture
with a 122-byte final chunk, same length as the earlier failed hand-built
3-stripe attempt. It's a red/blue/red vertical triple stripe (100/120/100
px, same proportions as that earlier attempt), and decoding it in full
replaces every row-token theory above with one simple, complete model:

- The frame's pixels are walked in raster order as **one continuous
  sequence** — not reset or re-paired at row boundaries. This stripe
  frame's content decodes to exactly 961 `(length, flag)` tokens summing to
  153600 (320×480) pixels, and the run lengths prove it: `(100,flag0)`,
  then `(120,flag1),(200,flag0)` repeated 479 times, then a final
  `(100,flag0)`. That's exactly what you'd get if a row's trailing red
  merges with the next row's leading red into one 200px run, every time,
  since raster order visits them back-to-back with nothing in between —
  only the very first and very last red segments stay unmerged, having
  nothing to merge with.
- Each token is `(length−1, flag)`, as established earlier. A run longer
  than 256px (the 1-byte length field's max) becomes multiple consecutive
  tokens sharing the **same** flag — confirmed against the solid-red
  frame's clean 600× `(255, flag=0)` content: chained pieces of one giant
  run, not 600 independent runs.
- `flag` is a color index into the sub-header's palette, established in
  earlier rounds. It only changes when the actual color changes to a new
  run; chained continuation pieces of the same run keep the same flag.

This also finally reconciles `save_to_gif_3`/`4`'s persistent, never-
resetting flip: a solid-red image with one white pixel decodes as one tiny
run (the white pixel) followed by one enormous red run (nearly the whole
image), chained into hundreds of same-flag pieces just like the fully-solid
case. The flag "staying flipped" was never a special persistent mode — it's
just many chained pieces of one giant run.

**`save_to_gif_8.pcapng`** (four distinct-colored vertical stripes — red,
green, blue, yellow, 80px each) answered two more open questions in one
capture:

- **The palette isn't fixed at 2 colors.** This frame's sub-header carries
  four populated RGB565 slots — `[16:18]`=red, `[18:20]`=green,
  `[20:22]`=blue, `[22:24]`=yellow — exactly the four stripe colors, in
  order. `flag` is a genuine multi-value palette index (0–3 confirmed
  here), and `[20:22]` is palette slot 2, not the mysterious "color
  variant" field guessed at earlier — that reading only looked plausible
  because every capture before this one used at most 2 colors.
- **The 528-byte prefix is still exactly 528 bytes with 4 colors in play**,
  ruling out "a palette/quantization table that scales with color count"
  as its purpose. Whatever it is, its size doesn't depend on how many
  distinct colors the frame uses.

**`save_to_gif_9.pcapng`** (a black background with a white 1px grid every
32px, frame 2 the same grid shifted 1px left and down) stress-tests the
model at far higher density — 9315 tokens per frame, mostly tiny 1px and
31px runs — and it holds up completely: pixels sum to exactly 153600 in
both frames, and the 528-byte prefix is still exactly 528 bytes. The two
frames' token streams are structurally identical but start from opposite
flag assignments, since each frame independently derives flag 0 from
whatever color its own first pixel happens to be — one more confirmation
that frames are encoded fully independently, not as deltas against each
other.

**`save_to_gif_10.pcapng`** (8 distinct-colored vertical stripes — one more
than `save_to_gif_8`, adding gray) found the palette's actual limit, and
something unexpected past it. Only 7 of the 8 colors got an exact palette
slot (red, green, blue, yellow, magenta, cyan, white — all byte-exact).
Gray never appears in the sub-header at all. Instead, gray's stripe is 40
alternating 1-pixel tokens referencing two *new* palette slots that decode
to RGB `(96,128,96)` and `(152,128,152)` — whose average, `(124,128,124)`,
is almost exactly the target gray, `(128,128,128)`. **Confirmed visually**,
not just from the bytes: the gray stripe looked textured/dithered on the
real panel, not smooth. The encoder dithers colors it can't represent
directly by alternating two nearby palette entries pixel-by-pixel, rather
than giving every distinct color its own slot — so it's less "8 colors and
no more" than a deeper constraint on which specific colors qualify for a
direct slot (7 saturated primaries were fine; one mid-tone gray wasn't).
The 528-byte prefix is still exactly 528 bytes with 9 total palette slots
in play (7 real + 2 dither-pair).

**`save_to_gif_11.pcapng`** is the control: same 8 colors, reordered so
gray is *first* (was last) and white is last (was first). Decisive result:
gray still dithers, now using slots 0–1 instead of 7–8, with the **exact
same pair** — `[16:18]`=`0x640C`, `[18:20]`=`0x9C13`, byte-identical to
`save_to_gif_10`. Every other color, including white in gray's old spot,
gets a clean direct slot. This rules out "ran out of slots, first come
first served" — it was never about position. The encoder maps this
specific gray to this specific dither pair deterministically, regardless
of what else is in the frame.

**`save_to_gif_12.pcapng`** tests the dithering boundary directly: black
(the missing 8th RGB-cube corner) and orange (255,128,0 — clearly not a
corner, its G channel is mid-value). Neither dithers — both get clean,
exact slots (`0x0000` black, `0xFC00` orange). That refutes "8 corners
only": a non-corner color can be represented exactly.

**`save_to_gif_13.pcapng`** follows up with light gray (200,200,200, a
different achromatic mid-tone) and dark red (128,0,0, chromatic, one
mid-value channel like orange — but not paired with a maxed-out channel).
Confirmed correct on the panel. Both dither, refuting "achromatic-only"
too. Checking every color tested so far against its own **maximum channel
value** gives a clean, exceptionless rule: a color gets a direct palette
slot only if `max(R,G,B)` is exactly 0 (black) or 255 (any hue at full
intensity in at least one channel); anything whose brightest channel lands
strictly in between dithers, regardless of how many other channels are
already at an extreme. 12 for 12 colors tested fit this, including
predictions made *before* checking. Consistent with the palette
fundamentally representing "hue at full brightness, or black."

`save_to_gif_13`'s byte-level layout is now decoded. Offline re-analysis of
the raw capture (no hardware) found the two dithered colors do **not**
share slots or combine with each other. Dark red keeps the simple 2-slot
pair pattern already known from gray in `save_to_gif_10`/`11`/`12` (slots
decode to (99,0,0)/(156,0,0), averaging almost exactly to the 128,0,0
target). Light gray instead gets a new, richer scheme: 8 slots that are the
*exhaustive* set of all 2×2×2 combinations of three independently-quantized
channels — R∈{156,206}, G∈{170,215}, B∈{156,206} — rather than one shared
pair.

That richer palette turned out to need a different content format
entirely, which is what had blocked decoding: **this frame's content isn't
RLE tokens at all — it's a raw, uncompressed 1-byte-per-pixel
palette-indexed bitmap.** The content region is exactly 153600 bytes
(320×480, no more, no less), and every one of those bytes is confined to
0–10, the 11-slot palette range, with zero exceptions. Read as 1
byte = 1 pixel in raster order, it decodes perfectly: three clean vertical
stripes (columns 0–105 light gray, 106–211 dark red, 212–319 red,
identical on every row checked), the red stripe uniformly one flag (no
dithering), the dark-red stripe alternating its 2-slot pair every single
pixel, and the light-gray stripe dominated by a repeating
`(flag0,flag0,flag0,flag1)` 4-pixel tile — a 3:1 duty-cycle dither on the G
channel alone, since those two slots share the same R and B. Most rows (475
of 480) also substitute one of the other 6 combo flags at scattered
positions. The 8 flags decompose cleanly into 3 independent per-channel
bits (R hi/lo, G hi/lo, B hi/lo), and measured over all 50880 gray-stripe
pixels, R and B sit at their "lo" value 8.5% of the time each and G 31.25%
— in the same range as the naive linear-interpolation duty cycle each
channel alone would need to average to 200 (12.0% for R/B, 33.3% for G).
That fits the 8-slot palette being nothing more than a precomputed
enumeration of all 8 outcomes of 3 separate single-channel ditherers, not
evidence of a genuinely 3D dithering algorithm. The per-row minor-flag
count is bursty rather than periodic (rows 0–2 have none, row 3 has 25,
row 4 has 1, row 6 has 31, ...), which fits error diffusion better than a
fixed spatial Bayer matrix — the exact algorithm isn't identified. This
also explains
*why* the 8-slot scheme exists: an independent per-channel ordered dither
needs far more achievable colors than a single alternating pair, and doing
that via RLE tokens would be pathological (nearly every run 1 pixel,
doubling the byte cost) — so past some complexity threshold the encoder
appears to switch from RLE to a flat indexed bitmap. The solid-red
reference frame in the same capture (still RLE, `mode_flag=0x0100`) vs.
this raw-bitmap frame (`mode_flag=0x0002`) is a plausible format selector,
though with only one example of each it isn't proven.

**First hardware test of the raw-bitmap reading was inconclusive, not a
refutation — but a follow-up test confirmed it directly.** With the panel
connected, a 40×40 block of an existing valid flag (red) was written into
`save_to_gif_13`'s light-gray stripe, `crc16_modbus` recomputed correctly,
all 79 packets acked — and the panel fell back to its cached animation
instead of showing the edit. The byte-layout reading itself stood (the
full 528-byte prefix was re-checked byte-by-byte for both frames —
genuinely all zero past the known header fields, no hidden checksum this
edit could have broken). A second experiment swapped two whole 40×40
blocks between the gray and red stripes instead of overwriting — a pure
permutation that leaves every flag's total pixel count exactly unchanged —
and still fell back, ruling out "preserves the frame's aggregate color
histogram" as the validator's criterion.

A third experiment, the smallest possible edit — swapping just two
adjacent bytes (row 0, columns 2 and 3) — **worked**: all 79 packets
acked, and the panel rendered the normal animation with the intended
single-pixel change visible, confirmed by the user. This is the first
genuine hardware proof of the raw-bitmap byte-layout reading, not just the
best fit for static evidence. Since the failed block swap is the *same
kind* of edit (a histogram-preserving permutation) just ~800x larger, the
pass/fail split points toward a scale- or magnitude-based validation —
how much of the frame differs from some reference — rather than a
property of the difference's statistics. The exact threshold isn't
mapped. Restoring the pristine original after this round needed two
retries before the panel actually redrew — the same flaky-restore
behavior documented in the 0.5.x era, just needing one more retry than
that case did; every upload itself acked cleanly, so the flakiness is on
the panel's redraw-trigger side, not the wire transfer.

**Bisecting that pass/fail boundary retracts the scale/magnitude
hypothesis and replaces it with something cleaner: per-region flag
membership.** Cross-stripe block swaps (same gray↔red type, between the
light-gray and red stripes) at 8×8 (128 total differing positions), 4×4
(32), 2×2 (8), and 1×1 (2) all fell back — including the 1×1 case, which
changes the exact same byte count (2) as the successful within-stripe swap
above. Byte count alone can't be the deciding factor if 2 bytes changed
produces opposite outcomes depending on *what* was swapped. A same-region
swap in the dark-red stripe (columns 106–107, values 2 and 3, both native
there) rendered correctly — a second, independent within-region success in
a different stripe with a different flag pair. Across all 8 data points so
far (2 within-region successes, 6 cross-region failures spanning 1 to 1600
pixels/side): edits that keep every pixel within its *own* stripe's
already-established flag set (gray: {0,1,5,6,7,8,9,10}; dark-red: {2,3};
red: {4}) pass; edits that put a flag value into a column range where it
doesn't already belong fail, regardless of how many bytes are touched
either way. Reads as a per-region (likely per-column-range) flag-membership
constraint, not a diff-size threshold — though this is a pattern match
across 8 tests, not a decoded algorithm.

**A large within-region swap confirmed edit size genuinely doesn't
matter.** Two 40×40 blocks, both entirely inside the gray stripe — the
exact same size as the 40×40 swap that failed every time it crossed a
stripe boundary — were swapped with each other. All 79 packets acked, and
the panel rendered correctly, confirmed by a user photo showing a clean
3-stripe layout with no fallback. Within-region edits now pass at both 2
bytes changed and 3200 bytes changed, while cross-region edits fail at
every size tested from 2 to 3200 bytes. Still untested: whether the
boundary is truly per contiguous stripe or some finer/coarser partition
that happens to align with these 3 stripes.

**Testing that exact question found a counterexample that complicates the
picture.** Swapping columns 105 (last light-gray pixel) and 106 (first
dark-red pixel) on row 0 — a single-pixel-pair edit crossing the stripe
boundary exactly — passed: all 79 packets acked, panel rendered real
content, not the fallback. Every *other* cross-region edit tested (6 of 6,
at sizes from 1 to 1600 pixels/side, always well inside a stripe's
interior) failed. So "every pixel's flag must belong to its column's
stripe, no exceptions" is too strong as stated — it predicted this should
fail, and it didn't. Whatever the real invariant is, edits exactly at a
stripe transition behave differently from edits deep in a stripe's
interior. One plausible, untested explanation: the real check cares about
local transition/run structure — an interior edit creates a brand-new
isolated anomaly with two new transitions where none existed, while a
boundary edit just adds a small wiggle at a transition that was already
there. Not yet tested: whether near-but-not-exactly-at-the-boundary
positions behave like "boundary" or "interior."

*Human-verification note:* distinguishing "correct content with a 1–2px
change" from "correct content, unchanged" by eye turned out to be
unreliable — this GIF alternates between the 3-stripe frame and a full
solid-red reference frame, and the flicker defeats fine pixel-level
inspection. Every pass/fail conclusion above actually rests on a coarser,
reliable distinction instead: fallback animation (visibly different
content) vs. real content (whichever frame, edited or not), which is easy
to tell apart on sight regardless of the flicker.

**Two more tests settle it.** A swap 5 columns into the gray interior
(column 100) with the dark-red boundary pixel (column 106) — crossing
regions, NOT adjacent — fell back, same as every other non-adjacent
cross-region test. A swap at the *other* stripe boundary (columns 211/212,
dark-red/red, adjacent) rendered correctly — ruling out "something specific
to the gray/dark-red transition" as the explanation for the first boundary
success. The full picture (2 adjacent cross-region successes at both
boundaries, 7 non-adjacent cross-region failures, 3 within-region
successes at various sizes — 13 hardware data points total) fits one clean
account: what fails is creating a brand-new isolated anomaly — a
foreign-colored pixel with mismatched neighbors on both sides, which is
what every non-adjacent cross-region edit does. An adjacent swap across a
boundary just shifts an *already-existing* transition by one pixel instead
of creating a new one; a within-region edit of any size never introduces a
foreign value at all. Reading this as a check on each row's
transition/run structure, not raw per-column palette membership, explains
all 13 data points without exception — still a pattern match, not a
decoded algorithm, but a strong one.

Also confirmed: the TOC-level delay field (previously "50 in every
capture, plausibly a delay, unit unconfirmed") is genuinely a delay, not a
coincidental shared UI default — the user explicitly set the frame speed
to 50 in the Windows app when generating `save_to_gif_13`, and the wire
value is literally 50. The unit (likely centiseconds, GIF's own
convention) is still unconfirmed, since every capture so far used the
same speed setting.

These two captures also caught and fixed a real bug, not just a
documentation gap: `CRC_INIT` was keyed by the `cmd` byte, which seemed
reasonable since `cmd` is derived from length — but that mapping is
many-to-one (two different lengths can share a `cmd` byte). `save_to_gif_12`'s
1080-byte final chunk collides with `save_to_gif_10`'s 312-byte one on
`cmd=0x3F`; `save_to_gif_13`'s 248-byte one collides with `save_to_gif_8`'s
2040-byte one on `cmd=0xFF` — and in both cases the correct CRC init
genuinely differs. `CRC_INIT` is now keyed by the real payload length
instead, which is unambiguous. All 15 captures re-verified byte-for-byte
after the fix.

Still open: the 528-byte prefix's actual contents/purpose (confirmed *not*
a color table, fixed-size up to 11 palette slots, and confirmed still
exactly 528 bytes in `save_to_gif_13`'s frame 2 by construction — size32 -
528 matches the overflowing content-length field exactly), one
unidentified sub-header byte, why a dithered color sometimes gets the
simple 2-slot pair and sometimes the 8-slot per-channel grid, the exact
per-channel dithering algorithm (duty cycles are roughly right for linear
interpolation, burstiness suggests error diffusion, neither confirmed),
whether `mode_flag` genuinely selects RLE-vs-raw-bitmap in general (one
example of each so far), the exact scope/mechanism of the content
validator (13 hardware data points now fit "a row's transition/run
structure must stay locally valid" without exception — a strong pattern
match, not yet a decoded algorithm), the delay field's unit (likely
centiseconds, unconfirmed), and why
`save_to_gif_2`'s solid
frames encode far less efficiently (4151 varied tokens vs.
`save_to_gif_3`/`4`/`5`'s clean 600 — possibly that source image wasn't
perfectly flat).

## Image format

Byte-identical to what the vendor's own `qt-tool/Image2Bin.exe` produces:

```
[0..3]   uint32 LE   payload size (width * height * 2)
[4..5]   uint16 LE   width   (320)
[6..7]   uint16 LE   height  (480)
[8]      0x00        constant in every sample
[9..10]  uint16 LE   CRC16/MODBUS over the pixel data
[11..]   pixels      RGB565, little-endian, row-major
```

Derived by feeding known images to `Image2Bin.exe` and decoding the output, not
from documentation. Our encoder reproduces its output byte-for-byte for every
image tested, across two different image sizes.

## Wire protocol

Bulk endpoints `0x03` out / `0x82` in. Every packet:

```
5a a5          magic
<len/256>      uint16 BE   payload bytes / 256 (8 for a 2048-byte chunk, 0 otherwise)
<cmd>          0x07 write chunk · 0x12 final partial chunk · 0x0b commit
<const>        0x64 for data · 0x66 for commit
<address>      uint32 BE   flash address
<payload>
<crc>          uint16 LE   poly 0xA001 reflected, init per command
```

The `.bin` is written from flash base `0x041E0000` in 2048-byte chunks, the
address advancing by 2048 each time. After each filled 128 KiB region a commit
is sent for that region carrying the number of bytes written to it. Any
remainder goes out as a final short packet, followed by a last commit.

Each command uses **its own CRC init**: `0xF104` for writes, `0xEEC4` for
commits, `0xD141` for the final partial. No single init fits all three. These
were solved algebraically over GF(2) and validated against all 308 packets in
both upstream captures.

Write and final chunks are acked with a 19-byte reply ending in ASCII `OK`.
Commits get a 21-byte reply carrying a 4-byte checksum of the region just
written — it is image-dependent, so never compare it literally.

## A warning about prior art

[Salamor/aula-l99-open-widgets](https://github.com/Salamor/aula-l99-open-widgets)
documents a JPEG protocol with magic `12 34 56 78` for "the AULA L99 screen".
**That protocol is not this panel's.** In that project's own captures the JPEG
traffic goes to device `87ad:70db`, a different USB display on the same machine;
the AULA panel (`eeef:268a`) is a separate device speaking the `5a a5` protocol
above. Building on the JPEG description leads nowhere — no error, no reply, no
visible change — which is a slow way to discover the mistake.

Their captures are still valuable: this protocol was decoded from them.

## Deriving this again

The vendor app cannot drive the panel under Wine: it locates the port via
SetupAPI, and Wine's `Enum\USB` tree carries HID devices but not CDC-ACM serial
ones, so enumeration returns nothing. No COM-port symlink fixes it. Capture on
real Windows, or work from the upstream pcapng files as was done here.
