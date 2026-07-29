# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.19] - 2026-07-30

**"Save to GIF": "the unidentified sub-header byte [13]" was stale
bookkeeping, not a real gap.** No hardware needed -- this was a
documentation audit, prompted by the user asking to investigate it
directly.

### Changed
- Traced "sub-header byte [13]" back through the changelog history. Both
  bytes that could plausibly be meant are already fully solved elsewhere:
  the TOC-entry's own byte 13 is the frame count, resolved explicitly back
  in the `save_to_gif_3.pcapng` round ("TOC frame-count ambiguity
  resolved"); the per-frame sub-header's byte 13 is simply the high byte
  of the `[12:14]` content-length `u16` field, solved from the start and
  re-verified repeatedly this session (including for `save_to_gif_13`'s
  overflowing case). Neither is an open mystery. The item had been
  mechanically carried forward in the "Known gaps" / "Still open" lists
  across roughly a dozen rounds without anyone re-checking whether it was
  still true.
- Removed from `protocol.py`'s and `README.md`'s open-items lists, with a
  short correction note explaining why, so it doesn't get silently
  reintroduced.

### Known gaps
- None closed by hardware this round -- this was purely a documentation
  correction. Real open items are otherwise unchanged: the 528-byte
  prefix's contents/purpose (though its 8-byte tolerance is now known),
  the dithering algorithm, `mode_flag`, the delay field's unit,
  `save_to_gif_2`'s inefficiency.

## [0.6.18] - 2026-07-30

**"Save to GIF": the 8-byte tolerance is not specific to frame 0 or the
RLE format -- it's identical in frame 1's raw-bitmap mode too.**

### Verified
- Repeated the 0.6.17 bisection on `save_to_gif_13`'s frame 1 (the
  154128-byte raw-bitmap frame, padding starting at offset 38 instead of
  frame 0's offset 18): 8 non-zero bytes passes, 9 fails. Exactly the same
  boundary as frame 0 (1728 bytes, RLE mode).

### Changed
- With the same exact threshold holding across two frames of very
  different size (1728 vs. 154128 bytes) and different content encoding
  (RLE tokens vs. raw indexed bitmap), "8" looks like a genuine constant
  of the format or firmware -- not an artifact of frame size, position
  within the blob, or encoding mode. Still no candidate mechanism for why
  8 specifically (alignment, a small fixed buffer, a coarse checksum
  granularity, etc. are all just guesses at this point).

### Known gaps
- No candidate explanation for why 8 is the specific number.
- Same open items otherwise: sub-header byte [13], dithering algorithm,
  `mode_flag`, delay field's unit, `save_to_gif_2` inefficiency.

## [0.6.17] - 2026-07-30

**"Save to GIF": the 528-byte prefix's tolerance boundary is exactly 8
bytes, and it's a pure count threshold, not a specific critical byte.**
Tight bisection of 0.6.16's 5-10 byte range, plus a confirming isolation
test.

### Verified
- Bisected the padding-region tolerance from 0.6.16 down to an exact
  boundary: 7 bytes non-zero passes, 8 bytes passes, 9 bytes fails, 10
  bytes fails (0.6.16). **Exactly 8 bytes tolerated, the 9th breaks it.**
- Isolated the 9th byte specifically: flipping ONLY offset 26 (frame 0's
  padding, the byte that turns a passing 8-byte edit into a failing
  9-byte one when added) from 0 to 1, with offsets 18-25 left untouched,
  rendered correctly -- not the fallback. So offset 26 is not itself a
  meaningfully-checked field; the failure at 9 bytes was purely about
  *how many* bytes were touched in total, not *which* byte.

### Changed
- Confirms the 0.6.16 "magnitude threshold" reading over the "hidden
  structured field" alternative: if there were a real field starting
  around offset 26, flipping it alone should have broken something. It
  didn't. The padding region genuinely tolerates a small, fixed number of
  changed bytes (8) regardless of which bytes they are, and rejects more
  than that -- a count-based check, not a positional one.

### Known gaps
- Whether the count that matters is "bytes changed from the original
  all-zero state" or something more specific (e.g. "bytes with a specific
  bit pattern") is untested -- all tests here used non-zero-from-zero
  changes only.
- Whether 8 is specific to this frame/region or a broader constant
  (e.g. shared with some other part of the format) is unknown.
- Whether this generalizes to frame 1 (raw-bitmap mode) is untested.
- Same open items otherwise: sub-header byte [13], dithering algorithm,
  `mode_flag`, delay field's unit, `save_to_gif_2` inefficiency.

## [0.6.16] - 2026-07-30

**"Save to GIF": the 528-byte prefix's zero padding is NOT inert -- it's
validated, and the tolerance boundary sits between 5 and 10 bytes.** First
active test of this previously totally opaque region, on `save_to_gif_13`'s
simplest frame (frame 0, solid red, RLE mode).

### Verified
- Frame 0's zero-padding region (bytes 18-527 of its 528-byte prefix, all
  zero in the original capture) was overwritten with non-zero patterns of
  increasing size, `crc16_modbus` recomputed correctly each time, all 79
  packets acked every time:
  - 200 bytes non-zero: fallback.
  - 20 bytes: fallback.
  - 10 bytes: fallback.
  - 5 bytes: **real content, not fallback.**
  - 1 byte (offset 18 flipped 0->1): **real content, not fallback.**
- This rules out "must be strictly all-zero, zero tolerance" (1 and 5
  non-zero bytes were both accepted) AND rules out "genuinely unused,
  ignored padding" (10+ non-zero bytes reliably triggers the fallback).
  Something checks this region, and it has real tolerance, not an
  exact-match requirement.
- Restores this round needed a retry twice (same known flaky-redraw
  behavior as every prior round); every upload itself acked cleanly.

### Changed
- The prefix's zero region behaves differently in character from the
  content region's transition/run-structure tolerance (0.6.11-0.6.15):
  content-region within-region edits passed at ANY size tested (up to
  3200 bytes), while here even a fairly arbitrary 10-byte pattern already
  fails. This looks more like a literal magnitude/length threshold
  specific to this region than a structural check -- though it's also
  possible the boundary (somewhere in bytes 23-28, i.e. offset 18+5 to
  18+10) marks the start of a real, still-unidentified structured field
  that happens to read as zero in every simple capture seen so far, rather
  than a tolerance-based check on otherwise-free padding.

### Known gaps
- The exact byte where the boundary sits (between offset 23 and 28) is
  not pinned down -- worth a tighter bisection.
- Whether the boundary is a true magnitude threshold or the edge of a
  real structured field is unresolved; testing with a structured pattern
  (e.g. a plausible checksum, a copy of a known-good value) instead of an
  arbitrary byte sequence at ~7-8 bytes might help distinguish.
- Whether this generalizes to frame 1 (raw-bitmap mode) or is specific to
  frame 0's RLE mode is untested.
- Same open items otherwise: sub-header byte [13], dithering algorithm,
  `mode_flag`, delay field's unit, `save_to_gif_2` inefficiency.

## [0.6.15] - 2026-07-30

**"Save to GIF": a 3-pixel-wide boundary shift also passes, further
confirming the transition/run-structure reading over "only exactly
1-pixel adjacent swaps work."**

### Verified
- A symmetric 3-pixel-wide block swap centered on the gray/dark-red
  boundary (columns 103-105 swapped with 106-108 on row 0 -- moving the
  transition point by 3 columns as a single clean shift, not scattered
  anomalies) rendered correctly, not the fallback. All 79 packets acked.
- Restore acked cleanly and took immediately, no retry needed this time.

### Changed
- Extends the boundary tolerance beyond exactly-adjacent 1-pixel swaps:
  a small symmetric shift of the transition point is also accepted. 14
  hardware data points now fit the transition/run-structure reading
  without exception: edits that move an existing transition by a small
  amount, or that stay entirely within one region regardless of size,
  pass; edits that create a brand-new isolated anomaly with mismatched
  neighbors on both sides fail, regardless of how few bytes are touched.

### Known gaps
- How far a boundary shift can move before it starts failing (3 columns
  passes; unknown upper bound) is untested.
- Same open items as 0.6.14 otherwise (528-byte prefix, sub-header byte
  [13], dithering algorithm, `mode_flag`, delay field's unit, `save_to_gif_2`
  inefficiency).

## [0.6.14] - 2026-07-30

**"Save to GIF": both stripe boundaries tolerate adjacent-pixel swaps,
pointing at a transition/run-structure check rather than raw region
membership; the TOC delay field is confirmed, not just plausible.**

### Verified
- A swap 5 columns into the gray stripe's interior (column 100) with the
  dark-red boundary pixel (column 106) -- crossing regions but NOT
  adjacent -- fell back, same as every other non-adjacent cross-region
  test so far.
- A swap of the OTHER stripe boundary -- columns 211 (last dark-red pixel)
  and 212 (first red pixel), adjacent -- rendered correctly, not the
  fallback. Second independent boundary-swap success, ruling out
  "something specific to the gray/dark-red transition" as the explanation
  for 0.6.13's result.
- The TOC-level delay field (`[16:18]`, previously "50 in every capture,
  plausibly a delay, unit unconfirmed") is now genuinely confirmed: the
  user explicitly set the frame speed to 50 in the Windows app when
  generating `save_to_gif_13.pcapng`, and the wire value is literally 50.
  Not a coincidental shared default -- a real, user-controlled field.

### Changed
- The full boundary-swap picture (2 adjacent cross-region successes at
  both stripe transitions, 1 non-adjacent cross-region failure just past
  one of them, 6 earlier non-adjacent cross-region failures, 3 within-region
  successes at various sizes) now fits a single clean account: what fails
  is creating a brand-new isolated anomaly -- a foreign-colored pixel with
  mismatched neighbors on both sides, which is what every non-adjacent
  cross-region edit does. An adjacent swap across a boundary just shifts
  an ALREADY-EXISTING transition by one pixel rather than creating a new
  one, and a within-region edit of any size never introduces a foreign
  value at all. Reading this as a check on each row's transition/run
  structure (not raw per-column palette membership) now explains all 13
  hardware data points from this investigation without exception.
- Unit for the delay field still not pinned down (likely centiseconds by
  GIF convention, i.e. 50 = 0.5s), since every capture used the same
  speed setting so far -- would need a capture with a different value to
  confirm the scale factor.

### Known gaps
- The transition/run-structure reading is now well-supported (13/13 data
  points) but still not a decoded algorithm -- what exactly counts as an
  acceptable transition, and whether there's a limit on transitions per
  row in general (independent of these experiments), is unknown.
- Same open items otherwise: the 528-byte prefix, sub-header byte [13],
  the dithering algorithm, `mode_flag`, delay field's unit,
  `save_to_gif_2`'s inefficiency.

## [0.6.13] - 2026-07-30

**"Save to GIF": a swap exactly AT the stripe boundary passed, contradicting
the strict per-region reading from 0.6.11/0.6.12.** Complicates, rather than
confirms, last round's "clean" conclusion -- genuinely open again.

### Verified
- Swapped columns 105 (last light-gray pixel) and 106 (first dark-red
  pixel) on row 0 -- a single-pixel-pair edit straddling the visual stripe
  boundary exactly, moving a gray-family flag into the dark-red column and
  vice versa. By every prior cross-region result (0.6.10, 0.6.11: 6/6
  failures at various interior positions and sizes), this should fail.
  Instead: all 79 packets acked and the panel rendered the normal content
  (3-stripe frame alternating with the solid-red reference frame), not the
  fallback.
- Restoring the original blob after this test needed one retry (the usual
  flaky-redraw behavior, not a new issue) -- confirmed back to normal
  after the retry, including the expected solid-red/3-stripe alternation.

### Changed
- The strict "every pixel's flag must belong to its column's stripe, no
  exceptions" reading from 0.6.11/0.6.12 is too strong: it predicted this
  boundary swap should fail, and it didn't. Whatever the real invariant is,
  it tolerates -- or doesn't apply the same way to -- edits exactly at a
  stripe transition, unlike edits deep inside a stripe's interior (which
  have failed 100% of the time, from 1 pixel to 1600 pixels/side). A
  transition-count or run-structure explanation (the boundary swap adds a
  small extra wiggle at an already-existing transition, vs. interior
  edits which create a brand-new isolated anomaly with two new
  transitions where none existed) is a plausible refinement, not yet
  tested against a case designed to separate it from the simpler
  "boundary pixels are special" reading.
- Human-verification note for future rounds: distinguishing "correct
  content with a 1-2px change" from "correct content, no change" by eye is
  unreliable given the GIF alternates between this frame and a full solid-
  red reference frame -- the flicker makes fine pixel-level confirmation
  impractical. The reliable signal these experiments actually depend on is
  coarser and unaffected by this: fallback animation (visibly different
  content) vs. real content (whichever frame, modified or not) is easy to
  tell apart on sight, and that's the distinction every pass/fail
  conclusion in this investigation is actually built on.

### Known gaps
- Whether "boundary-adjacent" edits pass in general, or whether this
  specific position was special, is untested -- worth trying a swap a few
  columns off the boundary (e.g. column 100 <-> 106) to see if there's a
  tolerance zone near transitions or a hard line right at column 105/106.
  Also worth an OFF-boundary interior swap between two stripes' extreme
  edges without crossing (e.g. column 104 <-> 105, both still gray) as a
  control.
- Same open items as 0.6.12 otherwise.

## [0.6.12] - 2026-07-30

**"Save to GIF": a large within-region swap renders correctly, closing
0.6.11's biggest open gap.** The per-region flag-membership hypothesis now
holds across the full size range tested, from 2 bytes to 3200.

### Verified
- Two 40x40 blocks, both entirely within `save_to_gif_13`'s light-gray
  stripe (columns 10-49 and 60-99, same size as 0.6.10's failed
  cross-stripe 40x40 swap), were swapped with each other. All 79 packets
  acked, and the panel rendered the normal, correct 3-stripe animation --
  confirmed by a user photo showing a clean light-gray / dark-red / red
  layout with no fallback. This is the same edit size that failed every
  time it crossed a stripe boundary (0.6.10, 0.6.11), now succeeding
  because both sides stayed within the gray stripe's own flag set.
- Restoring the original blob needed one retry before the panel visibly
  redrew (same flaky-redraw behavior as every prior round; the retry
  fixed it immediately, and every upload itself acked cleanly both times).

### Changed
- Confirms the per-region flag-membership reading from 0.6.11 is not
  merely a small-edit-size artifact: within-region edits now pass at 2
  bytes changed (0.6.10, 0.6.11) AND at 3200 bytes changed (this round),
  while cross-region edits fail at every tested size from 2 to 3200 bytes
  (0.6.10, 0.6.11). Edit size appears to genuinely not matter once the
  region-membership constraint is satisfied.

### Known gaps
- Still untested: whether the boundary is truly per contiguous stripe or
  something finer/coarser (e.g. per exact column) that happens to align
  with the 3 stripes here.
- The underlying mechanism is still a hypothesis pattern-matched across 9
  data points (3 within-region successes at sizes 2/2/3200 bytes, 6
  cross-region failures at sizes 2-3200 bytes), not a decoded algorithm.
- Same open items as 0.6.11 otherwise (528-byte prefix, sub-header byte
  [13], dithering algorithm, `mode_flag`, `save_to_gif_2` inefficiency).

## [0.6.11] - 2026-07-30

**"Save to GIF": the content validator isn't a magnitude threshold -- it's
per-region flag membership.** Bisection of 0.6.10's pass/fail boundary
overturns that round's leading hypothesis and replaces it with a cleaner,
fully-explanatory one.

### Verified
- Cross-stripe block swaps (same gray<->red swap type as 0.6.10, between
  `save_to_gif_13`'s light-gray and red stripes) at decreasing sizes: 8x8
  (128 total differing positions), 4x4 (32), 2x2 (8), and 1x1 (2) --
  **every single one fell back**, all the way down to a single pixel pair.
- A 1x1 cross-stripe swap (2 total differing positions -- the exact same
  byte count as 0.6.10's successful within-stripe swap) still fell back.
  This directly refutes 0.6.10's "scale/magnitude threshold" hypothesis:
  byte count alone cannot be the deciding factor, since 2 bytes changed
  produced opposite outcomes depending on *what* was swapped.
- A same-region swap in the DARK-RED stripe (columns 106-107, values 2 and
  3 -- both native to that stripe, the same kind of edit as 0.6.10's
  successful gray-stripe swap but in a different region and a different
  flag pair) rendered correctly, not the fallback. Second independent
  confirmation that within-region swaps pass.
- All restores this round acked cleanly every time; one needed a retry
  before the panel visibly redrew (same known flaky-redraw behavior as
  0.6.10, not a new issue).

### Changed
- Retracts the "scale/magnitude-based validation" hypothesis from 0.6.10.
  The real pattern across all data so far: edits that keep every pixel
  within its own stripe's already-established flag set (gray stripe:
  {0,1,5,6,7,8,9,10}; dark-red stripe: {2,3}; red stripe: {4}) pass,
  regardless of how many pixels are touched (a within-region swap of 2
  bytes passes the same as, presumably, a larger one would). Edits that
  put a flag value into a column range where it doesn't already belong --
  even a single pixel -- fail, regardless of how few bytes are touched.
  This is a per-region (likely per-column-range) flag-membership
  constraint, not a diff-size threshold.

### Known gaps
- Not yet tested: a within-region swap larger than 2 bytes (would confirm
  region-membership is sufficient on its own, independent of size, rather
  than "small AND region-correct").
- Not yet tested: whether the boundary is truly per contiguous stripe, or
  something coarser/finer (e.g. per exact column, or per some other
  partition that happens to align with the 3 stripes here).
- The underlying mechanism is still a hypothesis, not a decoded algorithm
  -- consistent with 6 cross-region failures and 2 within-region successes
  so far, not yet stress-tested against a case designed to break it.
- Same open items as 0.6.10 otherwise (528-byte prefix, sub-header byte
  [13], dithering algorithm, `mode_flag`, `save_to_gif_2` inefficiency).

## [0.6.10] - 2026-07-30

**"Save to GIF": first hardware-confirmed edit of the raw-bitmap format --
a single-pixel swap rendered correctly, a block swap didn't.** Directly
follows 0.6.9's two failed edits; narrows down what the panel's content
validator actually cares about.

### Verified
- A single adjacent-pixel swap (row 0, columns 2 and 3, values 0 and 1
  exchanged -- the smallest possible edit) was uploaded with `crc16_modbus`
  recomputed correctly. All 79 packets acked, and the panel rendered the
  normal 3-stripe animation **with the intended pixel visibly changed** --
  confirmed by the user. This is the first genuine hardware proof that the
  raw-bitmap byte-layout reading (0.6.7) is not just the best fit for the
  static evidence, but the panel's actual internal representation: editing
  one byte at a known position produced exactly the predicted one-pixel
  visual change.
- A second experiment -- swapping two whole 40x40 blocks between the
  gray and red stripes (same size, so a pure permutation: every flag's
  total pixel count across the frame is exactly unchanged, unlike 0.6.9's
  overwrite) -- still fell back. Same acked/checksum-correct-but-rejected
  pattern as every larger edit so far.
- Restoring the original blob after the block-swap experiment needed two
  retries before the panel actually redrew the pristine content (the first
  retry's re-upload acked cleanly but the panel kept showing the swapped
  render). This matches the flaky-restore behavior already documented in
  the 0.5.x era exactly, just needing one more retry than that case did.

### Changed
- Rules out "preserves the frame's aggregate flag histogram" as the
  validator's criterion: the failed block swap preserves it exactly, same
  as the successful pixel swap, so histogram preservation alone can't be
  what separates the two outcomes.
- The successful/failed pair (2 bytes changed -> fine; 1600 bytes changed,
  same permutation type -> fallback) points toward a scale- or
  magnitude-based check -- how much of the frame differs from some
  reference, not what statistical properties the difference has -- though
  the exact threshold and mechanism are still unknown.

### Known gaps
- Where the pass/fail boundary sits between "2 bytes changed" and "1600
  bytes changed" is unmapped -- worth bisecting in a future round.
- The validator's real mechanism is still unidentified; this only narrows
  the hypothesis space.
- Same open items as 0.6.9 otherwise.

## [0.6.9] - 2026-07-30

**"Save to GIF": first hardware test of the raw-bitmap model failed to the
fallback animation -- inconclusive, not a refutation.** The panel is
connected, so the 0.6.7 raw-bitmap reading got its first real hardware
check: a 40x40-pixel block in `save_to_gif_13`'s light-gray stripe was
overwritten with an existing, valid palette flag (4, the frame's own clean
red), `crc16_modbus` was recomputed correctly over the modified payload and
written into both TOC entries, and the modified blob was packetized with
`build_upload()` (same length as the real capture, so no new `CRC_INIT`
entry was needed) and uploaded.

### Verified
- All 79 packets acked -- the wire transfer and TOC-level `crc16_modbus`
  were structurally valid.
- The panel showed the fallback animation instead of the edited stripe.
  Re-uploading the original, unmodified blob (same procedure) restored the
  correct 3-stripe animation; user confirmed. The panel was not damaged.
- The full 528-byte prefix was re-checked byte-by-byte (not just the first
  80 bytes as before) for both frames: no hidden nonzero region exists
  anywhere in it beyond the already-decoded header fields. There is no
  room for an undiscovered per-frame content checksum -- frame 1's raw
  bitmap content runs from byte 528 to the frame's exact end (size32),
  with nothing trailing it either.

### Changed
- Nothing about the raw-bitmap structural reading is retracted: the static
  evidence for it (content length exactly 320x480, all bytes confined to
  the palette range, clean row-by-row stripe structure, measured
  per-channel duty cycles in the right range) is unaffected by this
  result, since ruled out is only a hidden checksum, not the byte-per-pixel
  layout itself.
- This result matches the established pattern from the 0.5.x-era RLE
  experiments: an ack'd, TOC-checksum-correct upload can still fail the
  panel's own undocumented content validation and fall back, for reasons
  never fully reverse-engineered even after many RLE-mode attempts back
  then. That opacity apparently isn't specific to the RLE format --  it
  now shows up in the raw-bitmap format too.

### Known gaps
- What the panel's content validator actually checks is still unknown for
  both formats. A large uniform block using an existing valid flag was not
  enough to satisfy it here, same as most non-trivial RLE edits weren't
  enough back in 0.5.x -- whatever passes validation seems to be a narrow,
  structurally-specific class of edit, not "any internally-consistent
  content."
- Same open items as 0.6.8 otherwise.

## [0.6.8] - 2026-07-30

**"Save to GIF": the 8-slot dither palette decomposes into 3 independent
per-channel ditherers, and the pattern looks like error diffusion, not a
fixed matrix.** Follow-up to 0.6.7, same capture, no new hardware.

### Verified
- The 8 combo flags split cleanly along 3 independent per-channel bits: R
  is hi(206) for flags {0,1,8,10}, lo(156) for {5,6,7,9}; B is hi(206) for
  {0,1,7,9}, lo(156) for {5,6,8,10}; G is hi(215) for {0,5,8,9}, lo(170)
  for {1,6,7,10}.
- Measured over all 50880 gray-stripe pixels: R is lo 8.56% of the time, B
  is lo 8.50%, G is lo 31.25% -- in the same range as the duty cycle each
  channel alone would need under naive linear interpolation to average to
  the 200 target (12.0% for R/B, 33.3% for G).
- Per-row minor-flag counts are bursty, not periodic: rows 0-2 have zero,
  row 3 has 25, row 4 has 1, row 6 has 31 (checked the first 40 of 480
  rows) -- no fixed spacing.

### Changed
- The 8-slot palette is better understood as a precomputed enumeration of
  all 8 outcomes of 3 separate, independent single-channel ditherers (each
  choosing hi/lo on its own), not evidence of an inherently 3-dimensional
  dithering algorithm -- the 8 RGB565 corners exist because RGB565 can't
  express "this channel alone is dithered" as anything but a fully
  specified color.
- The burstiness argues for error diffusion (or another history-dependent
  scheme) over a fixed spatial Bayer/ordered-dither matrix, which would be
  expected to spread corrections evenly across rows.

### Known gaps
- The actual per-channel algorithm (error diffusion direction/coefficients,
  or something else entirely) is not identified -- duty cycles and
  burstiness are consistent with error diffusion, not proof of it.
- Same open items as 0.6.7 otherwise: the 528-byte prefix, one
  unidentified sub-header byte, whether `mode_flag` generally selects
  RLE-vs-raw, `save_to_gif_2`'s inefficiency, `0x04200000`, no
  `--target gif`.
- Still no hardware mutation this round -- static re-analysis only.

## [0.6.7] - 2026-07-30

**"Save to GIF": `save_to_gif_13`'s complex dithered frame is NOT
RLE-encoded -- it's a raw, uncompressed 1-byte-per-pixel palette-indexed
bitmap.** Resolves the 0.6.5/0.6.6 "token layout unmapped" gap: the flat
`(length, flag)` RLE model wasn't slightly off, it was the wrong model
entirely for this frame.

### Verified
- Frame 2's content region is exactly 153600 bytes == 320x480, and every
  byte in it is one of only 11 distinct values (0-10, the palette range),
  with zero exceptions across the full region. Read as 1 byte = 1 pixel in
  raster order, it decodes perfectly: no leftover bytes, no overshoot.
- Row structure confirmed identical at every row checked: 3 vertical
  stripes at columns [0:106) light gray, [106:212) dark red, [212:320)
  red (106/106/108 px). Red stripe is uniformly one flag (undithered).
  Dark-red stripe is a perfect alternating 2-slot pattern, literally every
  pixel -- the simple pair dither confirmed at pixel granularity for the
  first time (previously only inferred from aggregate pixel/token counts).
  Light-gray stripe's dominant pattern is a repeating 4-pixel
  `(flag0,flag0,flag0,flag1)` tile -- flag0 and flag1 share R and B
  (both 206), differing only in G (215 vs. 170), so this tile is a 3:1
  duty-cycle dither on the G channel alone.

### Changed
- Explains why the 8-slot per-channel scheme exists where a 2-slot pair
  (used for dark red here, and gray in `save_to_gif_10`/`11`/`12`) doesn't:
  a true per-channel independent ordered dither needs many more than 2
  achievable colors, and representing that via RLE tokens would be
  pathological (runs collapsing to 1 pixel, doubling the byte cost vs. a
  raw index) -- so past some complexity threshold the encoder appears to
  switch formats rather than emit degenerate RLE.
- The solid-red reference frame in the same capture (still RLE,
  `mode_flag=0x0100`) vs. this raw-bitmap frame (`mode_flag=0x0002`) is a
  plausible RLE-vs-raw format selector, consistent but not yet proven with
  only one example of each.

### Known gaps
- 475 of 480 rows substitute one of the other 6 combo flags
  (5,6,7,8,9,10) at scattered positions in the light-gray stripe, on top
  of the base 4-pixel tile -- a real 2D ordered/Bayer dither matrix looks
  likely, but the row-to-row substitution rule isn't mapped.
- Whether `mode_flag` generally selects RLE vs. raw bitmap (vs. some other
  meaning) needs more than one data point per mode to confirm.
- Same open items as before: the 528-byte prefix's contents/purpose, one
  unidentified sub-header byte, `save_to_gif_2`'s encoding inefficiency,
  `0x04200000`, no `--target gif`.
- No hardware mutation was attempted -- this round was static
  re-analysis of the existing capture, even though the panel is currently
  connected.

## [0.6.6] - 2026-07-29

**"Save to GIF": `save_to_gif_13`'s palette re-analyzed offline (no
hardware) -- its two dithered colors use two DIFFERENT schemes, not a
shared combinatorial one.** Follow-up to 0.6.5, working from the same
capture rather than new hardware data.

### Verified
- `save_to_gif_13`'s frame 2 has 11 populated palette slots: 1 clean
  (undithered) red reference stripe, 2 slots forming dark red's dither
  pair (as expected from the established simple 2-slot pattern), and 8
  slots for light gray -- confirmed to be the *exhaustive* set of all
  2x2x2 combinations of three independently-quantized channels (R in
  {156,206}, G in {170,215}, B in {156,206}), not a second 2-slot pair and
  not combinations shared with dark red's pair.
- Content region boundary re-confirmed algebraically for this frame too:
  `size32 - 528` matches the (overflowing) 16-bit content-length field
  exactly, consistent with every earlier capture's fixed 528-byte prefix.

### Changed
- Refines the 0.6.5 "combinations of the component brightness levels from
  both dithered targets" guess: the two dithered colors don't share or mix
  slots. Each gets its own independent scheme, and which scheme a color
  gets (2-slot pair vs. 8-slot per-channel grid) is not yet understood --
  dark red here and gray in `save_to_gif_10`/`11`/`12` both use the simple
  2-slot form, so it isn't simply chromatic-vs-achromatic.

### Known gaps
- The token/byte grammar for either dither scheme is still undecoded.
  Decoding flat `(length-1, flag)` pairs from content-start (528 bytes
  into the frame) never lands the running pixel total on exactly 153600
  (320x480) -- it jumps from 153598 to 153602 at the token that should
  close the frame. A "two independent full-frame passes" hypothesis (base
  layer + dither mask) was tested and ruled out the same way. The flat
  2-byte-token grammar confirmed for every 2-slot-or-simpler capture may
  not be the right model once an 8-slot color is involved.
- Why light gray (200,200,200) needs the richer 8-slot scheme when a
  coarser 2-slot pair sufficed for the earlier 128-gray is unexplained.
- Same open items as 0.6.5: the 528-byte prefix's contents/purpose, one
  unidentified sub-header byte, `save_to_gif_2`'s encoding inefficiency,
  `0x04200000`, no `--target gif`.
- The touchscreen panel is connected to this machine as of this analysis,
  but no hardware mutation was attempted this round -- the next step needs
  a sharper hypothesis about the token grammar before spending a physical
  test on it.

## [0.6.5] - 2026-07-29

**"Save to GIF": found the dithering trigger rule, and fixed a real bug in
how `CRC_INIT` is keyed.** Two more captures -- black/orange (`gif_12`) and
light gray/dark red (`gif_13`) -- refute the earlier "corner" theory and
nail down when a color dithers instead of getting a direct palette slot.
Regression-checking these against all prior captures also exposed a
length-collision bug in `CRC_INIT` that had been silently wrong for two
existing entries.

### Verified
- `save_to_gif_12.pcapng` (solid black background, orange stripe): both
  colors get clean direct palette slots -- refutes the earlier "colors at
  the 8 RGB565 gamut corners dither" theory, since orange is nowhere near a
  corner and still didn't dither.
- `save_to_gif_13.pcapng` (light gray, dark red): light gray dithers, dark
  red does not. Combined with all prior data, 12/12 tested colors are now
  exceptionless under a single rule: a color gets a direct palette slot iff
  `max(R, G, B)` is exactly 0 or 255; anything whose brightest channel is
  strictly between 0 and 255 dithers, regardless of the other channels.
- Rendered correctly on the physical panel, confirmed by the user.

### Fixed
- **`CRC_INIT` was keyed by the `cmd` byte from `final_chunk_cmd()`, which
  is wrong: `cmd = (CMD_WRITE + payload_len) % 256` is many-to-one, so two
  different lengths can collide on the same `cmd` and legitimately need
  different CRC inits.** The standard regression check caught this directly:
  `gif_12`'s 1080-byte final chunk collides on `cmd=0x3F` with `gif_10`/`11`'s
  312-byte chunk (inits `0x9E2E` vs. `0x922E`), and `gif_13`'s 248-byte final
  chunk collides on `cmd=0xFF` with `gif_8`'s 2040-byte chunk (inits
  `0x522F` vs. `0xD9D1`). A cmd-keyed dict silently returned the wrong init
  for the second capture in each pair. Fixed by re-keying `CRC_INIT` by the
  actual payload length instead, and changing `crc16_packet()` to derive
  `payload_len` from the body's own size rather than trusting a
  caller-supplied `cmd`. All 15 known captures re-verified byte-for-byte
  after the fix, including both collision pairs.

### Known gaps
- The exact byte layout when multiple colors dither simultaneously in one
  frame (`gif_13`'s case) isn't mapped to a specific rule yet.
- The 528-byte prefix's actual contents/purpose are still unknown.
- One sub-header byte ([13]) remains unidentified.
- `save_to_gif_2`'s solid frames still encode far less efficiently than
  `save_to_gif_3`/`4`/`5`'s, unexplained.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.
- Still no `--target gif`.

## [0.6.4] - 2026-07-29

**"Save to GIF": dithering confirmed color-specific, not a slot-order
limit.** An eleventh capture -- the same 8 colors as 0.6.3, reordered so
gray is first instead of last -- is the decisive control experiment.

### Verified
- Gray still dithers, now using palette slots 0-1 instead of 7-8, with the
  **exact same pair** as 0.6.3 -- `[16:18]`=`0x640C`, `[18:20]`=`0x9C13`,
  byte-identical to `save_to_gif_10`.
- Every other color, including white (now in gray's old last position),
  gets a clean direct palette slot. The content's dither-token run moves
  correspondingly to the start of the frame instead of the end.
- All 25 packets reproduce byte-for-byte against the existing `0x3F`
  `CRC_INIT` entry -- same final-chunk length as `save_to_gif_10`, not a
  new data point.

### Changed
- **Rules out "7-slot capacity, first come first served" conclusively.**
  It was never about position or order: the encoder maps this specific
  gray to this specific dither pair deterministically, independent of what
  else is in the frame or which slot it would otherwise occupy.

### Known gaps
- Exactly which *other* colors (besides this one gray) trigger dithering
  is still untested -- confirmed color-specific and deterministic, but the
  actual boundary (luminance? saturation? something else?) is unmapped.
- The 528-byte prefix's actual contents/purpose are still unknown.
- One sub-header byte ([13]) remains unidentified.
- `save_to_gif_2`'s solid frames still encode far less efficiently than
  `save_to_gif_3`/`4`/`5`'s, unexplained.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.
- Still no `--target gif`.

## [0.6.3] - 2026-07-29

**"Save to GIF": found the palette's real limit -- dithering, confirmed
visually.** A tenth capture -- eight distinct-colored vertical stripes, one
more than 0.6.1's four-color test, adding gray -- finds where the palette
mechanism actually breaks down, and it's more interesting than a simple
slot-count cutoff.

### Verified
- Only 7 of the 8 colors get an exact palette slot (red, green, blue,
  yellow, magenta, cyan, white -- all byte-exact RGB565 at `[16:18]`
  through `[28:30]`). Gray never appears in the sub-header.
- Instead, gray's stripe is 40 alternating 1-pixel tokens referencing two
  *new* palette slots (`[30:32]`, `[32:34]`) that decode to RGB
  `(96,128,96)` and `(152,128,152)` -- averaging to `(124,128,124)`, almost
  exactly the target gray, `(128,128,128)`.
- **Confirmed visually, not just from the bytes**: the user reported the
  gray stripe looked textured/dithered on the real panel, not smooth. The
  encoder dithers colors it can't represent directly by alternating two
  nearby palette entries pixel-by-pixel, rather than giving every distinct
  source color its own slot.
- The 528-byte prefix is still exactly 528 bytes with 9 total palette slots
  in play (7 real + 2 dither-pair).
- 12th `cmd`/`CRC_INIT` data point: a 312-byte final chunk predicted
  `cmd=0x3F` before checking, confirmed exact; its CRC init (`0x922E`)
  solved and added to `CRC_INIT`.

### Changed
- Reframes the "how many palette colors" question from 0.6.1: it's not
  simply "8 colors and no more" -- it's a deeper constraint on which
  *specific* colors qualify for a direct slot. Seven saturated primaries
  (including white) were all fine; one mid-tone gray triggered dithering
  instead of getting an 8th slot.

### Known gaps
- Exactly which colors trigger dithering vs. get a direct slot is
  untested beyond this one data point.
- The 528-byte prefix's actual contents/purpose are still unknown.
- One sub-header byte ([13]) remains unidentified.
- `save_to_gif_2`'s solid frames still encode far less efficiently than
  `save_to_gif_3`/`4`/`5`'s, unexplained.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.
- Still no `--target gif`.

## [0.6.2] - 2026-07-29

**"Save to GIF": continuous-RLE model confirmed at high density.** A ninth
capture -- a black background with a white 1px grid every 32px, frame 2
the same grid shifted 1px left and down -- stress-tests the model from
0.6.0/0.6.1 against much denser, higher-token-count content than any prior
capture, and it holds up completely. Mostly a strong confirmation round;
no new structural surprises.

### Verified
- 9315 tokens per frame (vs. hundreds in every prior capture), mostly tiny
  1px and 31px runs from the grid lines and cells. Pixels sum to exactly
  153600 in both frames.
- The 528-byte prefix is still exactly 528 bytes even at this density,
  reinforcing 0.6.1's finding that its size doesn't depend on content
  complexity.
- The two frames' token streams are structurally identical (same 9315-token
  shape, same length histogram) but start from opposite flag/color
  assignments -- each frame independently derives flag 0 from whatever
  color its own first pixel happens to be ((0,0) is white in frame 1, on
  both a horizontal and vertical line; black in frame 2, since the 1px
  shift moves both lines off that pixel). One more confirmation that
  frames are encoded fully independently, not as deltas against each other
  (0.5.14/0.6.0).
- 11th `cmd`/`CRC_INIT` data point: a 1492-byte final chunk predicted
  `cmd=0xDB` before checking, confirmed exact; its CRC init (`0x1E90`)
  solved and added to `CRC_INIT`.

### Known gaps
- The 528-byte prefix's actual contents/purpose are still unknown.
- One sub-header byte ([13]) remains unidentified.
- How many palette slots the format actually supports is untested beyond 4.
- `save_to_gif_2`'s solid frames still encode far less efficiently than
  `save_to_gif_3`/`4`/`5`'s, unexplained.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.
- Still no `--target gif`.

## [0.6.1] - 2026-07-29

**"Save to GIF": palette confirmed beyond 2 colors, 528-byte prefix ruled
out as a color table.** An eighth capture -- four distinct-colored vertical
stripes (red, green, blue, yellow, 80px each) -- answers two open questions
from 0.6.0 in a single test.

### Verified
- **The palette isn't fixed at 2 colors.** This frame's sub-header carries
  four populated RGB565 slots -- `[16:18]`=red, `[18:20]`=green,
  `[20:22]`=blue, `[22:24]`=yellow -- exactly the four stripe colors, in
  order. `flag` is a genuine multi-value palette index (values 0-3
  confirmed), not the binary 0/1 seen in every earlier 2-color capture.
- `[20:22]` is palette slot 2, not the mysterious "color variant" field
  guessed at in 0.5.5 -- that reading only looked plausible because every
  capture before this one used at most 2 colors.
- **The 528-byte prefix is still exactly 528 bytes with 4 colors in play**,
  ruling out "a palette/quantization table that scales with color count"
  as its purpose.
- The frame's content is the clean "no merge" case of the continuous-RLE
  model from 0.6.0: 1920 tokens, uniformly `(80,flag0)/(80,flag1)/
  (80,flag2)/(80,flag3)` x 480, summing to 153600 pixels. Row boundaries
  here always land on a color change (yellow -> red), so nothing merges
  across them -- same grammar as 0.6.0, just not the boundary-merge case.
- 10th `cmd`/`CRC_INIT` data point: a 2040-byte final chunk predicted
  `cmd=0xFF` before checking, confirmed exact; its CRC init (`0xD9D1`)
  solved and added to `CRC_INIT`.

### Known gaps
- The 528-byte prefix's actual contents/purpose are still unknown (now
  confirmed *not* a color table).
- One sub-header byte ([13]) remains unidentified.
- How many palette slots the format actually supports is untested beyond 4.
- `save_to_gif_2`'s solid frames still encode far less efficiently than
  `save_to_gif_3`/`4`/`5`'s, unexplained.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.
- Still no `--target gif`.

## [0.6.0] - 2026-07-29

**"Save to GIF" row-grammar SOLVED: it's a continuous, row-boundary-
crossing run-length encoding.** A seventh capture -- a real red/blue/red
vertical triple stripe, same proportions as the hand-built 3-run row test
that failed in 0.5.9 -- supplies the missing piece and replaces every
row-token theory from the last several rounds with one complete, simple
model. Minor version bump: this is the most significant resolution of the
GIF investigation to date, even though `--target gif` still doesn't exist.

### Verified
- The frame's pixels are walked in **raster order as one continuous
  sequence** -- not reset or re-paired at row boundaries. The stripe
  frame's content decodes to exactly 961 `(length, flag)` tokens summing to
  153600 (320x480) pixels: `(100,flag0)`, then `(120,flag1),(200,flag0)`
  repeated 479 times, then a final `(100,flag0)`. That is exactly what a
  row's trailing red run merging with the next row's leading red run (both
  100px, both red, visited back-to-back in raster order) predicts -- only
  the very first and very last red segments have nothing to merge with.
- Each token is `(length-1, flag)`, as established in 0.5.5/0.5.8. A run
  longer than 256px (the 1-byte length field's max) becomes multiple
  consecutive tokens sharing the SAME flag -- confirmed against the clean
  solid-red frame's 600x `(255, flag=0)` content: chained pieces of one
  giant run, not 600 independent runs.
- `flag` is the color index established in 0.5.10/0.5.11. It only changes
  when the actual color changes to a new run; chained continuation pieces
  of the same run keep the same flag.
- 9th `cmd`/`CRC_INIT` data point: a 122-byte final chunk predicted
  `cmd=0x81` before checking, confirmed exact; its CRC init (`0x13B0`)
  solved and added to `CRC_INIT`.

### Changed
- **This reconciles `save_to_gif_3`/`4`'s persistent, never-resetting flip**
  (open again as of 0.5.14/0.5.15): a solid-red image with one white pixel
  decodes as one tiny run (the white pixel) followed by one enormous red
  run (nearly the whole image), chained into hundreds of same-flag pieces
  just like the fully-solid case. The flag "staying flipped" was never a
  special persistent mode -- it's just many chained pieces of one giant run.
- Every row-token theory from 0.5.8 through 0.5.13 (2-tokens-per-row
  structure, per-row color-must-differ rule, frame-index/delta hypotheses)
  is superseded by this single continuous-RLE model, which fits all of that
  evidence at once without needing separate rules for each observation.

### Known gaps
- The fixed 528-byte prefix's actual contents/purpose are still unknown.
- A couple of sub-header bytes ([13], [20:22]) remain unidentified.
- Whether more than 2 palette colors is possible is untested.
- `save_to_gif_2`'s solid frames encode far less efficiently (4151 varied
  tokens) than `save_to_gif_3`/`4`/`5`'s clean 600 uniform tokens for the
  same 153600-pixel solid color -- possibly that source image wasn't
  perfectly flat, not investigated.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.
- Still no `--target gif`: even with the run-length grammar solved, safely
  constructing new content needs the 528-byte prefix decoded too.

## [0.5.15] - 2026-07-29

**"Save to GIF" research: padding confirmed as the cause of 0.5.13's
failure, by direct A/B test.** With the panel back on Linux, 0.5.13's
failed 3-frame experiment was re-sent using proper, unpadded packetization
instead of trailing zero-pad bytes.

### Verified
- Re-sent the exact same content that failed padded in 0.5.13's ninth
  experiment, this time as 3 full 2048-byte writes + the real 540-byte
  final chunk (`cmd 0x23`, solved in 0.5.14) + commit -- literally the same
  5 packets as `save_to_gif_6.pcapng`, byte-for-byte. Result: the full
  3-frame animation played correctly.
- Same bytes, only the packetization differed between this and 0.5.13's
  attempt. That is now a direct, confirmed A/B result, not inference from
  a separate capture: padding -- not frame index, not a delta requirement
  -- caused 0.5.13's failure, and by the same logic likely explains 0.5.12's
  eighth experiment too (identical technique).

### Changed
- **Padding's status is now known to be inconsistent, not simply unsafe.**
  0.5.9's padding-only control (padding the working 2-frame blob, nothing
  else changed) rendered correctly; this padded 3-frame content did not,
  despite the identical "round up to the next multiple of 2048" technique.
  Padding should not be trusted for further experiments -- prefer real
  captures or exact, unpadded packetization (solving the needed `CRC_INIT`
  entry from a genuine capture) instead.

### Known gaps
- 0.5.9's 3-stripe row-count experiment used the same padding technique and
  should be distrusted pending a re-test without it -- not yet done, since
  it needs a new `CRC_INIT` entry (for a 122-byte final chunk) that no
  capture has provided yet.
- `save_to_gif_3`/`4`'s persistent, never-resetting flip is unexplained
  again, with no replacement theory yet.
- The bulk of the entropy coding, and solid-color frames' unrelated byte
  structure, are otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.14] - 2026-07-29

**"Save to GIF" research: `save_to_gif_6.pcapng` overturns 0.5.12/0.5.13's
delta-encoding theory.** A sixth GIF capture -- a real, vendor-generated
3-frame animation (solid red, split, split again *unchanged*) built
specifically to see what "no visible change between frames" looks like --
answers that question directly and, in the process, reveals the actual
cause of two previous "failed" hardware experiments.

### Verified
- `save_to_gif_6.pcapng`'s frame 1 and frame 2 are **byte-for-byte
  identical**. The real encoder simply re-emits a frame's full content
  verbatim when nothing changes -- there is no delta or no-op token.
- Its frame 1 is also byte-identical to `save_to_gif_5`'s frame 1 (the same
  split, independently captured), confirming the encoder is deterministic
  and content-driven, not context- or position-dependent.
- 8th `cmd`/`CRC_INIT` data point: a 540-byte final chunk predicted
  `cmd=0x23` before checking, confirmed exact; its CRC init (`0xA9BB`)
  solved and added to `CRC_INIT`.
- Direct comparison: the hand-built 3-frame blob from 0.5.13's ninth
  experiment (built *before* this capture existed) is byte-for-byte
  identical in content to what `save_to_gif_6.pcapng` actually contains.
  The only difference was packetization -- the real capture ends in a
  genuine 540-byte final chunk, while the experiment padded the wire
  transfer to a round multiple of 2048 to avoid needing an unsolved CRC
  value. The user confirmed `save_to_gif_6`'s capture renders correctly on
  the panel.

### Changed
- **Overturns 0.5.12/0.5.13's delta/reference-frame hypothesis.** Since the
  content 0.5.13's ninth experiment sent was, byte-for-byte, exactly what a
  real capture proves renders correctly, the padding technique used in that
  experiment (and 0.5.12's eighth experiment, and 0.5.9's three-run row
  test) is the more likely cause of those failures, not frame index or a
  delta requirement. Pending direct re-test with the now-solved `0x23` CRC
  value (no padding needed) once hardware is available again.
- This removes the basis for reframing `save_to_gif_3`/`4`'s persistent,
  never-resetting flip as a one-time delta-mode switch (0.5.12). That
  observation still stands; its explanation is open again.

### Known gaps
- 0.5.9's three-run row-count experiment and 0.5.12's frame-slot-swap
  experiment both used the same padding technique and should be re-tested
  without it before trusting their conclusions either.
- `save_to_gif_3`/`4`'s persistent flip is unexplained again.
- The bulk of the entropy coding, and solid-color frames' unrelated byte
  structure, are otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.13] - 2026-07-29

**"Save to GIF" research, hardware round eight: 3-frame test is
inconclusive, but points toward a sequential delta.** One more experiment
against `save_to_gif_5`, extending it to 3 frames to test 0.5.12's
frame-index hypothesis more directly. The result doesn't cleanly confirm
or refute that hypothesis, but the reason why is itself informative.

### Verified
- Built a 3-frame blob: frame 0 solid red (unchanged), frame 1 the proven
  red/blue split (unchanged), frame 2 an exact byte-for-byte copy of frame
  1's content. Rebuilt the TOC as 3 entries (offsets, total-size,
  frame-count, checksum all recomputed) and padded the wire transfer to
  avoid needing an unverified CRC_INIT.
- Result: the fallback animation. Reverted afterward; confirmed restored.

### Changed
- **Identifies a confound in the test design, which refines the
  hypothesis.** If "any frame index other than 0 supports the row-grammar"
  were the whole story, frame 2 (an exact copy of frame 1's already-working
  content) should have rendered the same split. It didn't -- but if the
  row-grammar is a *sequential* delta (relative to the immediately
  preceding frame, not always frame 0), frame 2's bytes should describe the
  change from frame 1's state, not repeat frame 1's own delta-from-
  solid-red verbatim. Under that reading, this failure is evidence
  *against* "each frame deltas from frame 0" (which predicts reusing an
  already-valid delta twice should still work) and *for* a frame-to-frame
  sequential delta instead.
- This is inference from a negative result, not a confirmed mechanism --
  a real test of "does index 2 support row-grammar" would need frame 2 to
  encode a genuine delta (even a trivial "no change") from frame 1, which
  isn't attempted since the delta token grammar itself isn't decoded.

### Known gaps
- Whether row-grammar content works at frame index 2 (or any index beyond
  1) specifically is still untested in a way that isolates it from the
  delta-source confound above.
- The delta/reference-frame hypothesis from 0.5.12 remains unconfirmed.
- The bulk of the entropy coding is otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.12] - 2026-07-29

**"Save to GIF" research, hardware round seven: the row-grammar may be
tied to frame index, not content -- possible delta/reference-frame
scheme.** One more experiment against `save_to_gif_5`: swapping which
frame slot holds the row-grammar content, to test whether the encoding
choice depends on frame position rather than what's actually in the frame.

### Verified
- Frame 1's entire content (sub-header, 528-byte prefix, row data) was
  replaced with a byte-for-byte copy of frame 2's already-proven-working
  red/blue split. TOC's frame-2 offset, both entries' total-size field, and
  the `crc16_modbus` checksum were all updated to match the now-larger
  frame 1; wire transfer padded to avoid needing an unverified CRC_INIT.
- Result: the fallback animation -- the same failure signature as every
  invalid mutation tried so far, despite every byte in the new frame 1
  being bytes that render correctly when they're in frame 2's slot.
- Reverted afterward; confirmed restored.

### Changed
- **New leading hypothesis**: frame *index*, not frame *content*, selects
  which decode routine applies. Frame 0 requires the continuous-run
  encoding solid frames use; frame 1+ can use the row-grammar decoded in
  0.5.8-0.5.11.
- Speculative but consistent with the evidence gathered across this whole
  hardware investigation: frame 0 may serve as a full/reference frame that
  later frames are decoded *relative to* (a delta scheme), which frame 0
  itself can't participate in for lack of a prior frame to reference. This
  reframes `save_to_gif_3`/`4`'s persistent, never-resetting flip (from
  0.5.3/0.5.4): not a per-row flag that should realistically reset, but a
  one-time mode switch -- "same as reference, skip N pixels" until the
  first real difference, then permanently switched to explicit/absolute
  data for the rest of the frame.

### Known gaps
- The delta/reference-frame hypothesis is unconfirmed. This one experiment
  can't rule out some other unidentified field, or an error in
  reconstructing the modified frame, as the real cause of the failure.
- Solid-color frames' byte-level structure (`FF 00` repeated ~600 times, no
  per-row pairing) is only partially explained by this hypothesis.
- The bulk of the entropy coding is otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.11] - 2026-07-29

**"Save to GIF" research, hardware round six: palette confirmed
frame-wide.** One more experiment against `save_to_gif_5`, recoloring the
whole frame via its sub-header instead of touching any row data, confirms
0.5.10's color-index finding applies uniformly, not just to the one row
tested so far.

### Verified
- Sub-header's two RGB565 color fields changed from red/blue
  (`0xF800`/`0x001F`) to green/yellow (`0x07E0`/`0xFFE0`), with **no row
  data touched at all**. TOC `crc16_modbus` recomputed and re-uploaded the
  same way as every prior experiment.
- The entire frame rendered in the new colors -- not just row 240, all 480
  rows correctly resolved the new palette. Confirms the color-index
  mechanism from 0.5.10 is a real, uniformly applied per-frame palette
  read by every row, not something specific to the one row tested so far
  or hardcoded elsewhere.
- Incidentally clarified an earlier observation: the 2-frame animation has
  been alternating with frame 1 (unmodified solid red) throughout every
  experiment in this round -- easy to miss when frame 1's red and frame
  2's red-left half looked similar, obvious once frame 2 turned
  green/yellow and produced a visible "flash" between frames.
- Reverted afterward; confirmed restored.

### Known gaps
- Still open: reconciling the row-token/palette model with
  `save_to_gif_3`/`4`'s persistent, never-resetting flip, and why
  solid-color frames look completely different at the byte level (`FF 00`
  repeated ~600 times, no per-row pairing at all) rather than using this
  same row-token grammar.
- The bulk of the entropy coding is otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.10] - 2026-07-29

**"Save to GIF" research, hardware round five: flag byte confirmed as a
color index.** One more experiment against `save_to_gif_5` -- swapping
rather than replacing row 240's two flag values -- gives the cleanest
result of the whole investigation and revises 0.5.9's "fixed positional
marker" guess.

### Verified
- Row 240's flag bytes swapped (not set to a new value): `(0x9F,0x00)
  (0x9F,0x01) → (0x9F,0x01)(0x9F,0x00)`, same lengths, same 160/160 split.
  Rendered correctly -- not the fallback -- with the boundary in exactly
  the same place as always, but that row's colors visibly swapped.
  Confirmed by photo: a thin horizontal line at row 240 reading inverted
  relative to every row above and below it.
- This directly confirms the flag byte **is** a per-run color index,
  selecting between the sub-header's two RGB565 color slots.

### Changed
- **Revises 0.5.9.** Four data points on this row: `(0,1)` original renders
  normally; `(1,0)` swapped renders correctly with colors inverted; `(0,0)`
  and `(1,1)` (0.5.7's mutations) both fail to the fallback. The real rule
  isn't "must equal a specific value in a specific position" -- it's that a
  row's two runs must use two *different* color indices, one 0 and one 1,
  in either order; the same index twice fails.
- This also reframes 0.5.9's three-run failure: with only two possible flag
  values, three runs can never all differ pairwise from each other -- some
  pair is forced to repeat, which this same rule rejects regardless of
  whether rows can otherwise hold more than two runs. "A row's runs must
  cover each of the frame's colors exactly once" fits all six results to
  date (including the three-run failure) without a separate hardcoded-
  token-count rule. Consistent with a real encoder never emitting two
  consecutive same-colored runs in a row in the first place (it would just
  merge them, or use the continuous-run encoding solid frames use instead).

### Known gaps
- Still open: reconciling any of this with `save_to_gif_3`/`4`'s
  persistent, never-resetting flip, and why solid-color frames look
  completely different at the byte level (`FF 00` repeated ~600 times, no
  per-row pairing) rather than using this same row-token grammar.
- The bulk of the entropy coding is otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.9] - 2026-07-29

**"Save to GIF" research, hardware round four: rows are likely fixed at two
tokens.** Two more experiments against `save_to_gif_5`: one testing whether
a 3-run row can work at all, one a control isolating whether wire padding
was ever a confounding factor. Together they narrow the model further.

### Verified
- **3-run row test.** Row 240 rewritten as three runs (100px red, 100px
  blue, 120px red, still summing to 320) with continuation-style flags
  `(0, 0, 1)`, specifically to distinguish "flag = per-run color index" from
  "flag = continue/last framing bit" -- a distinction a 2-run row can't
  make, since both readings look identical when there are only ever runs 0
  and 1. Grew the row from 4 to 6 bytes; recomputed the frame's size
  fields, both TOC entries, and the checksum; padded the wire transfer to
  the next multiple of 2048 so every packet stayed a plain, already-solved
  `cmd=0x07` write rather than needing an unverified new CRC_INIT entry.
  Result: the fallback animation, same as every flag mutation.
- **Padding control.** The original, unmodified blob, with the same kind of
  trailing zero-padding and nothing else changed, uploaded and rendered
  correctly -- ruling out the padding mechanism itself as the cause of the
  3-run failure.

### Changed
- **Refines the model toward: rows in this encoding are hardcoded to
  exactly two fixed-size sub-tokens, not a flexible run-list a flag
  terminates.** The one successful mutation (0.5.8) changed lengths while
  keeping exactly 2 tokens; every failed one (0.5.7's three flag mutations,
  now plus this round's 3-token attempt) either changed a flag without
  changing token count or changed token count outright, and all fail
  identically. Under this reading the flag bytes may not carry chosen
  per-row information at all -- possibly a fixed per-slot marker (always 0
  for the first run, 1 for the second) that decoding checks strictly, with
  color implied by slot position rather than by the flag's value.
- This would also explain why solid-color frames look nothing like this
  row-token structure at the byte level (`FF 00` repeated ~600 times, no
  per-row pairing) -- possibly a separate, non-row-bounded "single
  continuous run" encoding for flat images entirely, not the same grammar.

### Known gaps
- Still unconfirmed, and still doesn't reconcile with `save_to_gif_3`/`4`'s
  persistent, never-resetting flip within what should, under this theory,
  be many independent solid rows.
- The bulk of the entropy coding is otherwise still undecoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.8] - 2026-07-29

**"Save to GIF" research, hardware round three: first controlled content
change.** A fourth mutation experiment against the `save_to_gif_5` blob
breaks the "all-or-nothing" pattern from 0.5.7 and, for the first time in
this whole investigation, produces a predicted, position-correct change to
what the panel actually renders.

### Verified
- Row-token 240's two length bytes changed from `(159, 159)` (a 160/160
  pixel split) to `(99, 219)` (a 100/220 split) -- still summing to 320, the
  panel width, with the flag bytes left untouched. Recomputed the TOC
  `crc16_modbus` checksum and re-uploaded the same way as every prior
  experiment.
- The panel rendered the normal half-red/half-blue image, **not** the
  fallback animation, with the boundary notched inward for exactly one row.
  Confirmed by photo: the notch sits almost precisely at the panel's
  vertical midpoint, matching row 240 of 480 exactly.
- This directly confirms the run-length-stored-as-length-minus-one reading
  from 0.5.5 (previously inferred from byte patterns in captures, now
  demonstrated by controlling rendered output) and confirms the row-to-token
  mapping is exactly 1:1 with physical panel rows.
- Reverted afterward; confirmed restored (after one retry -- see Known gaps).

### Changed
- **Narrows 0.5.7's "any deviation fails identically" conclusion.** That
  held for three flag-byte mutations, but this length-byte mutation passed
  whatever validation the panel performs and rendered correctly. The
  emerging picture: the validation cares that each row's lengths still sum
  correctly (320 either way, here), not that the bytes are byte-for-byte
  identical to the original upload.

### Known gaps
- What the flag bytes need to satisfy is still unknown -- every flag-only
  edit tried so far has failed regardless of position or direction, now in
  contrast to a succeeding length-only edit.
- One restore attempt after this experiment silently didn't take (panel
  kept showing the previous fallback GIF despite a clean, acked re-upload of
  the known-good blob); an identical second re-upload fixed it. Possibly a
  read/write race if the panel was still mid-loop reading the region being
  overwritten. Not investigated further -- worth retrying a write before
  concluding a change had no effect.
- The bulk of the entropy coding is otherwise still undecoded, and this
  round's result still isn't reconciled with `save_to_gif_3`/`4`'s
  persistent-flip behavior.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.7] - 2026-07-29

**"Save to GIF" research, hardware round two: revises 0.5.6's conclusion.**
Two more single-byte mutation experiments against the same known-good
`save_to_gif_5` blob, both reverted afterward. Together with 0.5.6's first
experiment, the pattern across all three points somewhere different than
0.5.6 concluded.

### Verified
- Same flag-byte flip as 0.5.6, but on row-token 479 of 480 (the very last
  row -- the changed byte is literally the last byte of the whole upload):
  same result as before, the identical different, smaller, centered GIF.
- The opposite edit: row-token 240's *other* sub-token, flipped `0 → 1`
  instead of `1 → 0` (claiming a run stops immediately rather than claiming
  a nonexistent one continues -- the direction that should *shorten* a read
  rather than lengthen it, if the byte governs consumed length). Same
  result again.
- Confirmed directly: the fallback animation is the *exact same* one all
  three times, not three different-looking failures.
- Each mutation was reversible; re-uploading the original blob restored the
  correct half-red/half-blue image every time.

### Changed
- **Revises 0.5.6's leading theory.** Three mutations -- two positions
  (including one with nothing downstream left to run off to), two opposite
  directions -- all producing the identical result is a poor fit for
  "decoder desyncs and reads whatever raw bytes are next in flash" (0.5.6's
  conclusion): that predicts different-looking garbage per attempt, not one
  identical fallback. It fits much better with the panel validating the
  content somehow and falling back to a fixed, previously-cached animation
  on any failure, rather than rendering bad data.

### Known gaps
- Single-byte fuzzing of this stream looks like it won't reveal more on its
  own: the response is all-or-nothing, with no gradient between "slightly
  wrong" and "very wrong" to follow.
- What the content-level validation actually checks is unknown, and it
  still isn't reconciled with `save_to_gif_5`'s clean per-row alternation or
  `save_to_gif_3`/`4`'s persistent flip.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.6] - 2026-07-29

**"Save to GIF" research, first live hardware round.** The panel was plugged
directly into this Linux box, moving from passive capture analysis to
replay-and-mutate testing against real hardware. First result: strong
confirmation of everything so far. Second result: a mutation experiment that
didn't behave as predicted, but revealed something real about the flash and
decoder behavior.

### Verified
- `save_to_gif_5.pcapng`'s reconstructed blob, sent directly to the panel via
  `build_upload()` (all 4 packets acked), rendered the correct half-red/
  half-blue split. This is the first confirmation that our *output* is
  correct, not just that our wire bytes match a Windows capture -- validates
  the TOC/sub-header/checksum understanding built up over rounds 1-5 against
  the actual physical result, not just byte-comparison against captures.
- Flipping one byte in that known-good blob (the blue half's color-index
  byte in row-token 240 of 480) and re-uploading (recomputing the
  `crc16_modbus` TOC checksum to match) did not produce a localized change.
  The panel instead played a completely different, smaller GIF centered on
  screen. Re-uploading the original blob immediately restored the correct
  image, confirming the panel wasn't damaged -- this was a decode-time
  effect of the flipped byte, not a transfer-time failure.
- This is best explained by two things together: the flash write only
  touches the bytes actually sent (4216 in this case), so it doesn't erase
  whatever a previous, larger upload left further into that flash region;
  and the flipped byte likely isn't a simple static per-run color index (a
  plain index wouldn't explain jumping to unrelated, differently-sized
  content) but something that affects how many bytes the decoder consumes,
  so flipping it desynced the read position for everything downstream until
  it ran past this upload's own data and into that leftover content.

### Known gaps
- The three pieces of evidence about that "second byte" -- `save_to_gif_5`'s
  clean per-row alternation, `save_to_gif_3`/`4`'s persistent flip, and this
  round's decoder-desync result -- are not yet reconciled into one model.
- The entropy coding scheme is otherwise still not decoded. A working
  hardware replay-and-mutate loop now exists, though, which should make
  further experiments faster than capture-only analysis.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.5] - 2026-07-29

**"Save to GIF" research notes, round five.** A fifth capture
(`wireshark_dumps/save_to_gif_5.pcapng`: the same red baseline frame, but
frame 2 is a clean 50/50 vertical split -- left half red, right half blue --
instead of a single differing pixel) confirms the 528-byte fixed prefix is
genuinely content-independent, and produces the first real structural read
on the entropy-coded section itself. Still no new command.

### Verified
- `0x04240000` re-confirmed a fifth time; `crc16_modbus()` re-confirmed as
  the TOC checksum a fourth time.
- 7th `cmd`/`CRC_INIT` data point: a 120-byte final chunk predicted
  `cmd=0x7F` before checking, confirmed exact; its CRC init (`0x6F7A`) solved
  and added to `CRC_INIT`.
- **528-byte prefix confirmed genuinely fixed, not content-dependent.** With
  50% of the frame now a different color (vs. one pixel in rounds 3-4), the
  boundary between the fixed prefix and the entropy-coded section is still
  exactly 528 bytes. This was the specific question this capture was
  designed to answer.
- **First real structure decoded in the entropy-coded section.** The
  half-split frame's content is exactly 1920 bytes = 480 rows x 4 bytes, and
  is a single 4-byte unit (`9F 00 9F 01`) repeated identically 480 times.
  `0x9F` = 159 = 160-1, matching each color half's length minus one --
  evidence the first byte of a 2-byte sub-unit is a run length stored as
  length-1. The reference solid-red frame's content (1200 bytes = 600 x
  `FF 00`) fits the same reading: 600 x (255+1) = 153600, exactly the pixel
  count.

### Known gaps
- The second byte of each sub-unit (0/1 for the two color halves here) does
  not obviously reconcile with `save_to_gif_3`/`4`'s behavior, where the
  equivalent byte flips once at the point of divergence and stays flipped
  for hundreds of subsequent bytes across many rows, rather than
  alternating back per row. Whether it's a genuine per-run color index, a
  persistent context flag, or something else that looks like both depending
  on content, is unresolved.
- The rest of the sub-header and entropy coding scheme is still not fully
  decoded.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.4] - 2026-07-29

**"Save to GIF" research notes, round four.** A fourth capture
(`wireshark_dumps/save_to_gif_4.pcapng`: the same red-frame/one-white-pixel
pair as round three, but the white pixel moved from `(0,0)` to `(319,479)` --
the opposite end of raster order) produces the single most informative
result of the investigation so far: where the differing pixel sits controls
*how much* of the frame's encoding changes, not *how much data* the frame
needs. Still no new command.

### Verified
- `0x04240000` re-confirmed a fourth time; `cmd`/CRC-init formula holds again
  (`0xB1`, matching round three exactly since the payload length is
  identical); `crc16_modbus()` re-confirmed as the TOC checksum a third time.
- **Total frame size is independent of where the differing pixel is.** Both
  `save_to_gif_3.pcapng` (diff at top-left) and `save_to_gif_4.pcapng` (diff
  at bottom-right) produce frames of exactly the same two lengths (1728 and
  1730 bytes). The unchanged reference frame is even byte-identical between
  the two captures, confirming the encoder is deterministic.
- **Diff extent is sharply position-dependent.** Diffing each capture's two
  frames directly: the top-left diff (round three) changes 605 bytes, nearly
  the whole frame; the bottom-right diff (this round) changes only 5 bytes,
  clustered at the very end. This is strong, position-controlled evidence
  for a running encode-time context that a "differs from expectation" event
  permanently perturbs from that point in the raster scan onward -- an early
  divergence corrupts everything downstream of it, a late one corrupts
  almost nothing.
- **Color-field pair semantics resolved for these two captures**: one
  sub-header field holds the color of the frame's first pixel in raster
  order, the other holds the "other" color present (if any). Confirmed
  consistent between `save_to_gif_3` and `4` (the fields swap depending on
  whether the diff pixel is first or last), but this still doesn't explain
  `save_to_gif_2`'s solid frames, whose sole color sits in the "other" slot
  instead of the "first pixel" slot.
- The terminal-of-frame encoding for a last-pixel diff isn't a simple
  continuation of the same token-flip pattern seen for a first-pixel diff:
  the tail changes from repeating `...FF 00 FF 00` to `...FE 00 00 01`, a
  distinct pattern rather than one more flipped token.

### Known gaps
- The entropy-coded pixel section is still not decoded. This round narrows
  *where* a change appears; it doesn't yet reveal how a token is built.
- The color-field/`save_to_gif_2` inconsistency above is unresolved --
  possibly tied to `save_to_gif_2`'s much larger content length, not
  confirmed.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.3] - 2026-07-29

**"Save to GIF" research notes, round three.** A third capture
(`wireshark_dumps/save_to_gif_3.pcapng`: two frames, both solid red except
one white pixel at `(0,0)` in frame 2) resolves the TOC's frame-count
ambiguity, adds a sixth confirmed `cmd`/CRC-init data point, and — the main
result — locates a fixed ~528-byte per-frame prefix and pins down exactly
how a single-pixel difference between two otherwise-identical frames shows
up in the byte stream. Still no new command; the entropy-coded pixel data
itself remains undecoded.

### Verified
- `0x04240000` re-confirmed a third, independent time.
- Sixth `cmd`/`CRC_INIT` data point: a 1450-byte final chunk predicted
  `cmd=0xB1` by `final_chunk_cmd()` before checking, confirmed exact; its
  CRC init (`0x9F4E`) was solved and added to `CRC_INIT`. Still no general
  formula relating `CRC_INIT` to length, now checked against 6 points.
- **TOC frame-count ambiguity resolved.** 0.5.1/0.5.2 couldn't tell whether
  TOC-entry byte 12 or byte 13 was the real frame count, since both captures
  used 3-frame animations and both bytes read `3`. This capture uses 2
  frames: byte 12 stayed `3` (a constant format/version tag) and byte 13
  read `2` (the real frame count).
- `crc16_modbus()` over the post-header payload re-confirmed as the TOC's
  per-entry checksum field, byte-exact a second time.
- **Located a fixed ~528-byte per-frame prefix.** Every frame in both the
  second and third captures (5 frames total, 3 different solid colors plus
  the one-pixel-diff pair) has exactly 528 zero bytes right after its
  sub-header, regardless of color — strong evidence of a fixed table (as in
  JPEG's Huffman/quantization tables) independent of image content, with a
  variable-length entropy-coded section following it (whose length is a
  sub-header field, self-consistent with the frame's total size across all
  5 frames).
- **Located the single-pixel-diff signature.** The two frames differ at
  byte 528 itself (`0xFF`→`0x00`) and then, from the very first token after
  that boundary onward, a recurring 2-byte token's second byte is `0x00` in
  frame 1 and `0x01` in frame 2 for the rest of the frame — one flip, never
  reset. The change starting in the first post-prefix token matches `(0,0)`
  being first in raster-scan order. Reads as a running prediction context
  permanently perturbed by a "differs from expectation" event, consistent
  with (but not proof of) the transform/DCT-style coding hypothesis from
  0.5.2.

### Known gaps
- The entropy-coded pixel section itself is still not decoded — this
  capture shows *that* one pixel differing perturbs a running context, not
  *how* to construct that context or the tokens themselves.
- The RGB565-looking color-field pair's exact byte offset isn't consistent
  between captures 2 and 3, so its precise layout is still unclear even
  though the values themselves clearly track real colors.
- Next useful capture: the differing pixel at a different position, to map
  how position affects where in the byte stream the change appears and
  whether the 528-byte boundary is truly fixed or scales with something.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

## [0.5.2] - 2026-07-29

**"Save to GIF" research notes, round two.** A second, deliberately simple
capture (`wireshark_dumps/save_to_gif_2.pcapng`: solid red/green/blue
frames) cracks the final-chunk `cmd` byte, the TOC checksum, and part of the
per-frame sub-header. Still no new command — the bulk of each frame's pixel
payload remains undecoded — but this closes several of 0.5.1's open
questions and fixes a latent bug it left in `build_upload()`.

### Fixed
- `build_upload()` always used the fixed `CMD_FINAL` (`0x12`) for a final
  short chunk, correct only because every image this module has ever built
  is `320x480` and therefore always has the same 11-byte remainder. Any
  other image size would silently send the wrong `cmd` byte (and thus the
  wrong CRC) for its final chunk. Now computed via `final_chunk_cmd()`
  (below), which fails loudly with `ValueError` for a length with no known
  `CRC_INIT` entry instead of silently sending bad data. No behavior change
  for the `320x480` path this module actually uses — verified by re-running
  the byte-for-byte check against both `save_to_bkg_1/2.pcapng` captures.

### Verified
- **The final-chunk `cmd` byte is solved**: `cmd = CMD_WRITE + (payload_len %
  256)`, not a fixed opcode. `CMD_COMMIT` (`0x0B`) and `CMD_FINAL` (`0x12`)
  turn out to be ordinary instances of this formula, not independent
  opcodes — coincidentally constant because commit payloads are always 4
  bytes and this module's images always leave an 11-byte remainder. Checked
  exactly against 5 independent samples across 3 capture files, including
  both GIF captures' final chunks (`0x71` for 1386 bytes, `0x35` for 1582
  bytes) predicted correctly before being checked.
  - No general formula for the matching `CRC_INIT` was found: two
    hypotheses (init as a function of the cmd byte alone, or of the
    magic+lenfield+cmd prefix) were brute-forced against all 5 known
    (cmd, init) pairs and neither held. `CRC_INIT` gained two entries solved
    for the exact lengths seen (`0x71`→`0x1CB0`, `0x35`→`0xD9F1`), not a
    general result.
- **The GIF TOC's per-frame checksum field is solved**: it's
  `crc16_modbus()` — the same function already used for the single-image
  header — over the payload following the header. Verified byte-exact.
- **Two per-frame sub-header fields decoded**, by diffing two of the second
  capture's solid-color frames (byte-identical for ~8800 bytes except one
  4-byte window): the frame's own byte length (self-referential, exact for
  all 6 frames across both captures), and its dominant/fill color in RGB565
  (exactly pure red/blue/green for the three test frames).
- `0x04240000` re-confirmed as the "Save to GIF" address from a second,
  independent capture.

### Known gaps
- Each frame's actual pixel payload is still undecoded: not raw RGB565, not
  zlib/deflate, no JPEG SOI marker. The strongest lead — two solid-color
  frames being byte-identical except for one small window — points toward
  some transform/DCT-style coding rather than simple run-length encoding,
  but this is unconfirmed. Next step: a 2-frame GIF differing by one pixel,
  to isolate how a coefficient or delta is expressed.
- No general `CRC_INIT`-vs-length formula, so the cmd-byte fix above still
  can't extend to arbitrary new upload sizes without a matching capture.
- `0x04200000`, the remaining unidentified flash slot the vendor binary
  references, is still unaccounted for.

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
