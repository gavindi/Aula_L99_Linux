# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
