# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.7] - 2026-07-30

**"Save to GIF": 0.8.6's raw-bitmap self-padding fix confirmed working on
real hardware by the user.** Closes out the two biggest open "unvalidated
on real hardware" caveats from this whole dithering/raw-bitmap-mode arc:
a from-scratch raw-bitmap-mode frame (not an edit to an existing capture)
renders correctly, and trailing filler bytes appended past the decoder's
declared `width*height` read window are correctly ignored rather than
tripping the content validator or anything else.

### Changed
- Updated docstrings/help text across `protocol.py` (`build_gif_blob`,
  `dither_frame_floyd_steinberg`), `cli.py` (`--dither` help, module
  docstring), and `screen_tab.py` (dither checkbox label, warning message)
  from "unvalidated"/"experimental" to "confirmed working on real
  hardware" for: dithering itself, from-scratch raw-bitmap-mode encoding,
  and the raw-bitmap filler-padding mechanism.

### Known gaps
- Still open, not addressed by this round: the exact device-side dithering
  algorithm remains unknown (this encoder uses its own approximation, not
  a reproduction -- see 0.8.2), the 528-byte prefix's exact purpose, the G
  ramp's off-by-one, and `mode_flag`'s exact overrun mechanics. None of
  these affect the now-confirmed working behavior above.

## [0.8.6] - 2026-07-30

**"Save to GIF": fixed a regression from 0.8.5 -- raw-bitmap mode's own fix
introduced a new failure ("every frame is using raw-bitmap mode, no
run-based content to pad") that the user hit on "very small" GIFs. Root
cause: any single full-panel frame with detail/color everywhere (no flat
region) forces raw-bitmap mode, which was entirely excluded from the
CRC-length-tuning padding trick -- leaving nothing to pad with.**

### Fixed
- Raw-bitmap frames now pad themselves with harmless trailing filler bytes
  when the CRC-length-tuning pass needs to nudge the total upload length
  onto an already-solved `CRC_INIT` entry -- the raw-bitmap decoder is
  confirmed to always read exactly `width*height` bytes and ignore
  anything after, so appended filler is invisible to the renderer, the
  same principle as the existing RLE run-splitting trick, just applied
  differently. Unlike RLE padding (2 bytes/piece, capped by a run's
  length), filler costs exactly 1 byte each with no capacity limit, so it
  always succeeds whenever at least one frame is raw-bitmap mode --
  fixing the exact case that broke, since that's precisely when the old
  RLE-only mechanism had nothing eligible left to use.
- `build_all()` gained a `raw_pad=(frame_index, filler_byte_count)`
  parameter, applied alongside the existing `split_at` mechanism. The
  CRC-tuning pass now prefers a raw-bitmap donor whenever one exists, and
  only falls back to the original RLE run-splitting logic (unchanged,
  including its even-delta and run-capacity constraints) when every frame
  is RLE-mode -- the one case where a raw-bitmap donor isn't available.

### Added
- Tests: a direct regression test reproducing the reported bug (single
  full-panel gradient frame, dithered, no donor frame -- previously raised
  `ValueError`, now succeeds), a test confirming the padded blob's length
  actually lands on a valid chunk-size remainder (not just that it didn't
  raise), and a test confirming a raw-bitmap frame is preferred as the
  padding donor over an available RLE frame with a large run.

### Known gaps
- **New hardware-untested assumption, additive to 0.8.5's**: whether
  anything past the raw-bitmap decoder's confirmed `width*height`-byte
  read window is inspected by some other, still poorly-understood
  mechanism (e.g. the never-fully-decoded content validator) is unknown.
  Recommend a hardware smoke test of a raw-bitmap frame with actual
  appended filler bytes, alongside the still-outstanding raw-bitmap-mode
  smoke test from 0.8.5.

## [0.8.5] - 2026-07-30

**"Save to GIF": fixed a real hardware bug the user hit -- GIFs over ~100KB
uploaded and partially rendered (correct content up top, scrambled green
noise below). Root cause: a silent 16-bit content-length field overflow,
already flagged but never fixed; the real fix is automatic raw-bitmap-mode
encoding for oversized frames, not just a guard rail.**

### Fixed
- `build_gif_blob`'s per-frame header has a 16-bit content-length field
  (`header[12:14]`) that silently wrapped for RLE content over 65,535
  bytes. Dithering makes this easy to hit -- RLE costs 2 bytes per run,
  and dithered pixels alternate constantly, so busy dithered regions
  produce far more RLE bytes than flat safe-color content ever did. This
  matches a directly analogous hardware test already on record (forcing a
  frame's real content past its declared length produced the exact same
  symptom: correct rendering up to the wrong/short boundary, garbled
  content after).
- Any frame whose RLE content would exceed 65,535 bytes is now
  automatically encoded as raw-bitmap mode (`mode_flag = 0x0002`) instead:
  one palette-index byte per pixel, always exactly `width*height` bytes.
  Confirmed by a real hardware capture (`save_to_gif_13`) that the
  raw-bitmap decoder ignores the declared content-length field entirely
  and always reads exactly `width*height` bytes based on the frame's own
  width/height fields -- sidestepping the overflow regardless of size.
  This is a correctness fix, not an opt-in feature: it only activates when
  RLE content would otherwise have produced guaranteed-corrupt output, so
  anything that already worked (safe-color and lightly-dithered content)
  is unaffected and keeps using RLE exactly as before.

### Added
- `GIF_MODE_RLE`/`GIF_MODE_RAW_BITMAP` named constants and
  `_gif_raw_bitmap_content()`. `_gif_largest_run()` gained an `eligible`
  parameter so the CRC-length-tuning padding pass never targets a
  raw-bitmap-mode frame (its content is fixed-size -- there are no tokens
  to pad). A final safety-net check verifies no frame's actual content
  exceeds the 16-bit field after all padding, raising a clear error
  instead of ever silently producing wraparound-corrupted output again.
- Tests: forcing raw-bitmap mode via an all-single-pixel-run image,
  round-tripping raw-bitmap content back to the original pixels via the
  palette, confirming small/existing content still uses RLE unchanged,
  and confirming `_gif_largest_run`'s eligible-filtering works both in
  isolation and through the full `build_gif_blob` path with mixed-mode
  frames.

### Known gaps
- **New, less-tested territory beyond the general "unvalidated on real
  hardware" caveat**: every prior raw-bitmap hardware test was a small
  edit to an already-working captured frame, never a frame built from
  scratch by this encoder. A real hardware smoke test of a large/colorful
  image that actually forces this path is recommended -- ideally a small
  forced-raw-bitmap test image before retrying the user's original
  failing GIF.
- The raw-bitmap-mode-specific "content validator" (row transition/run-
  structure check, never fully decoded) was only ever exercised via edits
  to existing captures, not scratch-built content -- natural dithering
  produced a coherent gradient in every real capture examined, which is
  the kind of content that passed, but this genuinely hasn't been tested
  for this encoder's own output.

## [0.8.4] - 2026-07-30

**"Save to GIF": sped up dithering and CRC computation -- a 10-frame,
full-panel `dither=True` GIF went from 6.3s to 3.1s (~51% faster), after
profiling showed the previous release's dithering was slow enough to
notice in practice.**

### Changed
- `nearest_ramp_value()`'s linear scan (comparing a diffused float against
  each ramp rung via `abs()`) was ~44% of total conversion time by itself.
  Replaced with `RAMP_R_LUT`/`RAMP_G_LUT`/`RAMP_B_LUT`, precomputed 256-entry
  tables built from `nearest_ramp_value()` at import time, turning the hot
  per-pixel quantize step into an O(1) lookup. `nearest_ramp_value()` itself
  is unchanged and still used to build the tables.
- `crc16_modbus()` rewritten table-driven instead of bit-by-bit (~12% of
  total conversion time); verified byte-for-byte equivalent against the old
  formulation on 20 random inputs before replacing it -- same polynomial,
  same output, just faster.

### Investigated but not adopted
- The user asked whether numpy (installed on their system) would help.
  Benchmarked directly rather than assumed: a naive numpy port of the same
  per-pixel-sequential algorithm was **5x slower** (1.6s vs 0.3s/frame) --
  numpy's per-element access overhead loses to plain Python list/tuple
  indexing for this kind of tight, unavoidably sequential loop. A fully
  vectorized numpy rewrite *is* possible (~0.06s/frame, ~5x faster than
  today) but requires switching from Floyd-Steinberg error diffusion to
  ordered/Bayer dithering, trading the current noise-like look for a fixed
  repeating pattern -- decided against, to keep today's dithering algorithm
  and dependency footprint unchanged. Revisit if raw speed ever matters
  more than the visual trade-off.

### Known gaps
- Floyd-Steinberg is a sequential process where each pixel's error depends
  on the ones before it, so this release's lookup-table quantization
  produces a *different* (not byte-identical) dithered pattern than 0.8.3's
  exact-float linear search -- a single rounding-boundary difference
  cascades through the whole diffusion chain. Still always ramp-legal and
  visually equivalent; noted in `dither_frame_floyd_steinberg()`'s
  docstring so a future refactor producing "different but equally valid"
  output again isn't a surprise.
- Still unvalidated on real hardware, unchanged from 0.8.3.

## [0.8.3] - 2026-07-30

**"Save to GIF": added opt-in Floyd-Steinberg dithering, lifting the encoder's
safe-colors-only restriction -- the first practical payoff of the ramp
characterization and pic_scan.dll disassembly work from 0.7.2-0.8.2.**

### Added
- `protocol.py`: `RAMP_R`/`RAMP_G`/`RAMP_B` (the fixed dither ramp, now real
  constants instead of only comment-block prose), `nearest_ramp_value()`,
  `is_ramp_legal_color()` (a strict superset of `is_safe_gif_color()` --
  every safe color is also ramp-legal), and `dither_frame_floyd_steinberg()`
  -- classic raster-order Floyd-Steinberg, per-channel independent,
  quantizing onto the known ramp. This is our own approximation, not a
  reproduction of AULA's still-undiscovered device-side algorithm -- since
  0.8.2 confirmed that algorithm isn't in `pic_scan.dll` at all, and the
  display chip has no dithering of its own, the panel just deterministically
  shows whatever ramp-legal value it's given, so any error-diffusion pattern
  that lands on ramp rungs should look correct on hardware.
- `build_gif_blob(..., dither: bool = False)`: opt-in, purely additive.
  When true, dithers each frame before the existing color gate (now
  `is_ramp_legal_color` instead of `is_safe_gif_color`); when false
  (default), behavior is byte-for-byte unchanged from before this release.
- `--dither` CLI flag (`cli.py`) and a "Dither (experimental)" checkbox
  (`screen_tab.py`), both defaulting off. The GUI's existing pre-upload
  safe-color check is skipped when the checkbox is checked (it would
  otherwise reject almost any image before dithering ever runs).
- `tools/aula_l99_screen/tests/`: the repo's first automated test suite
  (pytest), covering ramp math, dithered-output legality, and a
  before/after regression check that `dither=False` is unchanged.

### Known gaps
- **Unvalidated on real hardware** -- explicitly stated in the CLI help
  text, GUI checkbox label, and `build_gif_blob()`'s docstring. A real
  panel smoke test (upload a small dithered image, confirm it renders
  as a reasonable approximation rather than triggering the fallback
  animation) is recommended before trusting this path.
- Fully-dithered images with no flat/solid region anywhere can starve the
  pre-existing CRC_INIT-length-tuning pass of a long enough run to pad
  onto a valid chunk length, raising the (pre-existing, unrelated) "no
  large enough solid/uniform run" error -- noted in `build_gif_blob()`'s
  docstring; keeping at least one sizable flat region (e.g. a solid
  border) avoids it.
- The device's own dithering algorithm is still not known -- this releases
  a workable approximation, not a reproduction.

## [0.8.2] - 2026-07-30

**"Save to GIF": traced the last untraced GIF-relevant export in
`pic_scan.dll` -- confirmed the dithering decision is not anywhere in
this DLL at all, not just not in `Gif_to_data_LT7689`.**

### Verified
- **`Gif_to_data`** (the non-`_LT7689` sibling export) is functionally
  identical to `Gif_to_data_LT7689` for pixel processing: same direct
  calls (`Scan_aRGB8565`/`Scan_aRGB8888`/`SaveMode16`/`SaveMode24`/flash
  writers), same register-indirect calls resolving to the same `QImage`/
  `QString` accessor set. The one difference is a single extra call into
  a previously-unnoticed unexported helper.
- That helper (VA `0x6a9c17f0`) reads a file in 2KB chunks and computes a
  running checksum via two 256-byte lookup tables. Dumped both tables
  directly from the PE image's `.rdata` section and diffed them
  byte-for-byte against a from-scratch table for the reflected polynomial
  `0xA001` -- the same polynomial this repo's own `crc16_packet()` already
  uses for the wire protocol -- exact match, confirmed standard
  **CRC-16/ARC**. This is a file-integrity checksum (almost certainly
  verifying a freshly-written flash-blob file), unrelated to pixel
  dithering.

### Changed
- **Every exported GIF-relevant function in `pic_scan.dll`, and
  everything reachable from any of them, has now been examined.** Both
  top-level GIF export entry points (`Gif_to_data` and
  `Gif_to_data_LT7689`) are ruled out, closing off the DLL entirely as a
  location for the dithering decision.
- The one remaining candidate is code in the qt-tool app's own `.exe`
  itself (not yet disassembled at all) -- e.g. a
  `QImage::convertToFormat()` call with an explicit dithering flag,
  executed by the app before ever calling into `pic_scan.dll`, which
  would be invisible no matter how thoroughly this DLL is traced.

### Known gaps
- The actual dithering decision algorithm is still not located --
  `pic_scan.dll` is now fully exhausted as a search space; the qt-tool
  `.exe` itself is the only remaining lead for continuing this
  particular thread.
- Same longstanding open items otherwise: the 528-byte prefix's exact
  purpose, the exact diffusion coefficients/direction, the G ramp's
  off-by-one, `mode_flag`'s exact overrun mechanics, `save_to_gif_2`'s
  inefficiency.

## [0.8.1] - 2026-07-30

**"Save to GIF": resumed the 0.7.7 static-analysis pivot and closed it
out -- traced two previously-unexamined `pic_scan.dll` exports
(`SaveMode16`/`SaveMode24`), confirmed the entire `Gif_to_data_LT7689`
call graph is now exhaustively free of dithering logic, and checked in a
persisted RE artifact so this doesn't have to be re-derived again.**

### Verified
- **`SaveMode16`** (VA `0x6a9c24f0`, never examined in 0.7.7) dispatches
  on a mode parameter: modes `{2,5}` pack ARGB4444, modes `{1,4}` pack
  RGB565, and all other modes take a "default" path that also just does
  RGB565 truncation -- all three are **plain bit-truncation, no
  dithering** (one mode has an unrelated special case remapping opaque
  pure-black to `0x0021` so `0x0000` stays a usable transparency
  sentinel). Modes `{3,4,5}` then call onward into exactly the chain
  traced in 0.7.7 -- `Scan_ColorTB_Data` -> `Scan_ColorTB_from_image_data`
  -> `Image_u16Data_to_colorTBu8Data` -> `ColorTB_u8Data_to_zipU8Data` --
  which **closes the GIF pipeline end-to-end for the first time**:
  `Gif_to_data_LT7689` calls `SaveMode16` directly, resolving 0.7.7's
  open question of how its four traced functions are actually reached.
- **`SaveMode24`** (VA `0x6a9c3290`, also unexamined) confirmed as the
  trivial 24bpp sibling -- lossless 8-bit passthrough, no quantization
  possible at that depth, not a dithering candidate.
- **`Scan_ColorTB_Data`** (VA `0x6a9c2420`, 208 bytes) fully traced: pure
  per-chunk orchestration, looping up to 255 times over
  `Scan_ColorTB_from_image_data`. Clarifies that the well-known
  "chained in <=256px pieces" cap most likely originates in **this**
  chunk-count limit, not the RLE token format's separately-identical
  256-run cap in `ColorTB_u8Data_to_zipU8Data`.
- **`Scan_ColorTB_from_image_data`** (VA `0x6a9c14d0`, 192 bytes) fully
  traced: confirmed **exact-match palette dedup** on already-16-bit
  RGB565 words via linear search, zero per-channel math of any kind.
- **`ColorTB_u8Data_to_zipU8Data`** and **`Scan_aRGB8888`** (Checkpoints
  A/B for this round) fully traced and confirmed as previously
  characterized: pure RLE encoder (with a per-row raw-copy overflow
  fallback) and a plain 32-bit raw-copy sibling of `Scan_aRGB8565`,
  respectively. No dithering in either.
- All ~55 register-indirect calls inside `Gif_to_data_LT7689` traced back
  to their register loads: every one resolves to `QImage`
  width/height/pixel/destructor, `QString`/`QCoreApplication` string and
  event-loop housekeeping, or memory alloc/free/refcount boilerplate.

### Changed
- **`Gif_to_data_LT7689`'s entire reachable call graph -- direct and
  indirect -- is now exhaustively traced**, not "partially traced,
  banked" as in 0.7.7. Every step in the confirmed chain (raw pixel scan
  -> RGB565 truncation -> palette dedup -> exact-match quantize -> RLE)
  is a stateless, per-pixel-independent operation: no ramp constant
  appears as an immediate anywhere, and no per-channel accumulator is
  carried across loop iterations.
- Since the wire-capture evidence (0.6.1-0.6.9) already proved dithered
  patterns exist in the bytes actually transmitted, the dithering must
  happen somewhere in the PC-side pipeline before upload -- just
  demonstrably not anywhere `Gif_to_data_LT7689` reaches. Two untested
  leads remain for a future round: the sibling export `Gif_to_data`
  (non-`_LT7689`, never actually traced despite a similar call-target
  profile), and code in the qt-tool app itself, outside `pic_scan.dll`
  entirely (e.g. a `QImage::convertToFormat()` call with an explicit
  dithering flag).

### Added
- `tools/aula_l99_screen/re_notes/pic_scan_dll.md`: the disassembly
  transcript 0.7.7 was missing -- exact `objdump`/export-table commands,
  the full ordinal/RVA/VA/name export table, relevant IAT import
  resolutions, and per-function findings for every function traced this
  round and in 0.7.7. Exists so the next round doesn't have to re-derive
  RVAs and re-slice the disassembly from scratch.

### Known gaps
- The actual dithering decision algorithm is still not located -- this
  round *ruled out* the previously-most-likely location rather than
  finding it. `Gif_to_data` (non-`_LT7689`) and the qt-tool app's own
  code outside `pic_scan.dll` are the two remaining candidates.
- Same longstanding open items otherwise: the 528-byte prefix's exact
  purpose (though `ColorTB_u8Data_to_zipU8Data` and `Scan_ColorTB_Data`
  both independently touch a `0x204`/516-byte-strided region this round,
  reinforcing but not proving the existing palette-table suspicion), the
  exact diffusion coefficients/direction, the G ramp's off-by-one,
  `mode_flag`'s exact overrun mechanics, `save_to_gif_2`'s inefficiency.

## [0.8.0] - 2026-07-30

**New tool: `aula_l99_gui`, a PySide6 GUI wrapping both `aula_l99_hacky`
(keyboard) and `aula_l99_screen` (touchscreen) so their core features can be
driven without CLI flags.** First GUI in the repo; imports both tools'
`protocol.py`/`device.py` directly rather than shelling out to their CLIs.

### Added
- `tools/aula_l99_gui/`: a two-tab app (`main_window.py`, `keyboard_tab.py`,
  `screen_tab.py`) covering a curated subset of each CLI, not full parity.
  Keyboard tab: device list/refresh, handshake test, per-key color, built-in
  effects (dropdown tagged confirmed/untested from `EFFECT_CONFIRMED`) with
  speed/brightness, and RTC set -- cable path only, same as the CLI. Screen
  tab: single-image upload to `photo-frame`/`background`, and GIF upload
  from a folder, multiple files, or an animated `.gif`, with a pre-upload
  safe-color check (`is_safe_gif_color`) that lists offending colors instead
  of sending something the from-scratch encoder can't build.
- `workers.py`: background `QThread` workers reimplementing each CLI's
  device-I/O loop (`aula_l99_hacky/cli.py`'s `_run_cable`/`_run_sequence`,
  `aula_l99_screen/cli.py`'s `cmd_upload` packet loop) against the public
  `protocol.py`/`device.py` API, emitting Qt signals for live progress
  instead of printing -- keeps the UI responsive during a handshake or
  upload.
- `tools/aula_l99_gui/README.md`: install/run instructions and a feature
  summary.

### Fixed
- A `QThread` teardown crash ("QThread: Destroyed while thread ... is still
  running", then a segfault) hit on first real hardware use, right after a
  successful screen upload. Root cause: the "operation finished" UI update
  was gated on the *worker's* `finished` signal, which fires before the
  underlying `QThread` has actually stopped -- reassigning or nulling
  `self._worker`/`self._thread` at that point could drop Python's last
  reference to a `QThread` that was still alive. A first fix attempt (adding
  `deleteLater()` alongside the manual nulling) traded that bug for a
  double-free race between Qt's deferred deletion and Python's
  refcount-triggered one. Final fix: gate re-enabling the UI (and thus
  allowing a new worker/thread to be created) on `QThread.finished`, not
  `Worker.finished`, and never explicitly null the references -- the next
  run's reassignment (or normal object teardown) drops them safely once
  `deleteLater()` has already made the underlying C++ object releasable.
  Verified with an offline threaded regression test simulating rapid
  consecutive uploads that reproduced both crash variants before the fix and
  passed cleanly after.
- `main_window.py` now blocks closing the window while a keyboard
  transaction or screen upload is in flight (`closeEvent` checks each tab's
  `is_busy`), since interrupting a screen upload partway through can freeze
  the panel.

### Known gaps
- Curated feature set only: no raw-hex-send, `--convert`/`--describe`,
  `--address` override, `--ignore-nak`, or video-file GIF frame extraction
  -- use the CLIs directly for those.
- GIF upload always applies one uniform delay to every frame regardless of
  source, rather than reading a source `.gif`'s own embedded per-frame
  delays -- sidesteps the delay-uniformity constraint from 0.7.6 entirely
  rather than surfacing it.
- Not tested against the dongle path (disabled in the UI, same as the CLI).

## [0.7.7] - 2026-07-30

**"Save to GIF": identified the underlying display chip and confirmed the
compression/dithering format is AULA's own bespoke engineering, then
disassembled key functions in `pic_scan.dll` (the vendor's own encoder)
to trace the real pipeline -- a real methodology shift (static binary
analysis instead of hardware experiments), banked partway through.**

### Verified
- **Chip identified**: `pic_scan.dll` exports two GIF encoder functions,
  `Gif_to_data` and `Gif_to_data_LT7689` -- the panel is built on
  Levetop's **LT7689**, a Cortex-M4 serial UART TFT graphics controller.
  Its public datasheet and application notes were checked in detail and
  document only a generic serial playback command (`Display GIF`, opcode
  `0x88` -- "start playing file N," not a format spec) and a companion
  tool (`LT_IMAGE_TOOL.exe`) whose own output format is confirmed to be
  plain, uncompressed 16bpp/24bpp RGB with no palette and no RLE.
  Confirms our entire RLE/8-slot-dithering/528-byte-prefix scheme is
  AULA's own bespoke compression layer, not a documented chip-vendor
  format -- it exists nowhere except inside this DLL and our own
  reverse-engineering.
- Recovered full demangled C++ export names from `pic_scan.dll` (not
  fully stripped) and disassembled the GIF-relevant ones (32-bit x86,
  `objdump -d -M intel`, RVAs resolved via the PE export table, image
  base `0x6a9c0000`):
  - `Scan_aRGB8565`: confirmed to be **plain bit-truncation** ARGB->RGB565
    (`R>>3`-style masking, no rounding, no dithering whatsoever). Almost
    certainly the simple photo-frame/background converter, not the GIF
    path -- consistent with that format's already-confirmed simplicity.
  - `Scan_ColorTB_Data`: divides a frame's pixels into up to 255 chunks,
    each a 0x204-byte (516-byte) substructure -- matching the same
    "0x204 bytes per iteration" stride independently inferred from
    `Image_u16Data_to_colorTBu8Data`'s loop structure.
  - `Scan_ColorTB_from_image_data`: builds each chunk's local palette via
    **exact-match, first-appearance-order deduplication** -- directly
    matching our own reverse-engineered "palette in first-appearance
    order" model.
  - `Image_u16Data_to_colorTBu8Data`: converts pixels to palette indices
    via a **simple linear search** (up to 256 entries) for an EXACT
    match against the chunk's table. If no exact match is found, no
    output byte is written at all -- no fallback, no on-the-fly
    quantization.
  - The zero-initialized table `Scan_ColorTB_from_image_data` builds
    (516 bytes / 258 u16 entries, at struct offsets `0x430`-`0x634`) is
    structurally very close to our long-mysterious 528-byte prefix
    (same role: fixed-size, mostly-zero, holds RGB565 palette entries).
    Not proven byte-for-byte identical (off by a small, plausibly
    explainable amount), but strong circumstantial support for what that
    region fundamentally is.

### Changed
- The critical implication of point 4 above: since an unmatched pixel is
  silently skipped (not quantized in place), whatever decides *which*
  colors need dithering and rewrites source pixels into the correct
  alternating ramp-representable sequence must run **before** any of
  these four functions -- it isn't in any of the GIF-related exports
  checked. Most likely inlined inside `Gif_to_data_LT7689` (a large
  orchestrator function handling file I/O and memory allocation, only
  partially traced) or in a private, unexported helper with no symbol
  name to search for.

### Known gaps
- The actual dithering decision algorithm (which ramp levels, what
  spatial/duty-cycle pattern) was NOT located. Finding it would mean
  methodically stepping through `Gif_to_data_LT7689`'s full call graph
  rather than checking named exports -- a genuinely larger effort than
  this round, banked here rather than pursued further for now.
- The 528-byte-prefix/table correspondence is suggestive, not proven
  exact.
- Same longstanding open items otherwise: the exact dithering diffusion
  algorithm, `mode_flag`'s exact overrun mechanics, `save_to_gif_2`'s
  inefficiency.

## [0.7.6] - 2026-07-30

**"Save to GIF": `--upload` now accepts a single animated `.gif` or a
video file directly, auto-generating frames -- and this immediately
surfaced a real, previously-untested constraint: all frames in one
upload must share the SAME delay value, not just any valid value.**

### Added
- `cli.py`'s `--upload` now accepts, for `--target gif`: one or more
  images (unchanged), a single animated `.gif` (all frames used, each
  keeping its own embedded delay by default), or a single video file
  (`.mp4`/`.mov`/`.avi`/`.mkv`/`.webm`/`.m4v`, frames extracted via
  ffmpeg, requiring `--fps` and/or `--max-frames` -- no silent default
  frame count). New `--fps` and `--max-frames` flags. `--gif-delay`, when
  explicitly given, now overrides every frame's delay uniformly
  (including a source GIF's own embedded delays or a video's computed
  one); its default changed from `50` to `None` so this override
  distinction is possible.
- `protocol.build_gif_blob()`'s `delay` parameter now accepts a list (one
  value per frame) as well as a single int, matching the TOC's actual
  per-entry field structure.

### Verified
- End-to-end real-CLI test (not a script bypassing it): a synthetic
  2-frame GIF (solid red 300ms, solid blue 700ms) run through
  `python3 -m aula_l99_screen.cli --upload test_anim.gif --target gif`
  extracted both frames correctly (delays 30/70 centiseconds, matching
  the 300ms/700ms source via the established ms/10 conversion) and
  uploaded -- but the panel showed the FALLBACK animation, not the
  intended content.
- Isolated the cause directly: the identical red/blue content re-uploaded
  with a uniform `delay=50` for both frames rendered correctly. The same
  content again with a uniform `delay=30` (still not 50, but the same
  value for every frame) ALSO rendered correctly. Only the non-uniform
  `[30, 70]` case fell back. Confirms the constraint is about delay
  values matching ACROSS frames within one upload, not about hitting any
  particular value -- something never tested before, since every capture
  and every hand-built test prior to this always used the same delay
  (usually 50) for every frame.
- The video-extraction path was verified mechanically (both `--fps` and
  `--max-frames`-derives-fps modes correctly produce the right frame
  count and per-frame delay), though not yet tested end-to-end on
  hardware, since a real/synthetic video's colors failed the existing
  safe-color check first (see Known gaps).

### Changed
- The delay field join a growing pattern: several TOC/sub-header fields
  turn out to have real validation behind them beyond just "what does
  this field mean" (the 528-byte prefix's 8-byte tolerance, the
  transition/run-structure content check, and now delay uniformity).
- This directly affects the new `.gif`-import feature's practical
  usefulness: many real animated GIFs vary per-frame delay (e.g. holding
  the last frame longer), and using each frame's own embedded delay by
  default -- the behavior just added -- will silently produce a
  non-working upload whenever those delays differ. Not yet fixed or
  guarded against; see Known gaps.

### Known gaps
- `cli.py` does not yet warn or error when a source GIF's extracted
  per-frame delays are non-uniform -- it will currently build and upload
  a blob that's confirmed to fail on real hardware. Needs a decision:
  hard error, automatic normalization (e.g. use the first/max/most-common
  delay for all frames) with a clear warning, or something else.
- Whether the constraint is "all frames exactly equal" or something
  looser (e.g. "monotonic," "within some tolerance") is untested -- only
  one non-uniform pair (30 vs. 70) and two uniform cases (30, 50) have
  been tried.
- Real compressed video (even a flat single-color source through
  ffmpeg's default YUV handling) reliably fails the existing safe-color
  check by 1-2 units (e.g. red renders as `(253,0,0)` instead of
  `(255,0,0)`) -- an inherent property of how ffmpeg/most video codecs
  represent color, not a bug in the new extraction code. Practically
  limits video input to synthetic/exact-color sources under the current
  encoder scope.
- Same longstanding open items otherwise: the 528-byte prefix's true
  purpose, the exact dithering diffusion algorithm, `save_to_gif_2`'s
  inefficiency.

## [0.7.5] - 2026-07-30

**"Save to GIF": `mode_flag` confirmed as a real, functional RLE-vs-raw-
bitmap decoder switch -- forcing a mismatch produces garbled, structured
content, not the usual fallback animation.** First direct hardware test
of `mode_flag`'s role, in both directions, on `save_to_gif_13`.

### Verified
- Frame 0 (solid red, real `mode_flag=0x0100`/RLE, content untouched)
  flipped to `mode_flag=0x0002`/raw-bitmap: all 79 packets acked. The
  panel rendered a complex, clearly non-fallback
  bands including a light-gray-like region, a red/black staticky "noise"
  band, and clean red regions, repeating a few times vertically. This is
  NOT the fallback animation and is NOT simply garbage -- the visible
  structure (colors and rough layout resembling frame 1's real 3-stripe
  content) is consistent with the raw-bitmap decoder reading a full
  width*height=153600-byte window starting right after frame 0's 528-byte
  prefix regardless of frame 0's own much smaller declared size, likely
  running past frame 0's real boundary into frame 1's actual header and
  content bytes in flash -- though the exact byte-level correspondence
  wasn't rigorously confirmed, only the qualitative shape of the result.
- Frame 1 (the real raw-bitmap 3-stripe frame, `mode_flag=0x0002`,
  content untouched) flipped to `mode_flag=0x0100`/RLE: all 79 packets
  acked. The panel showed a garbled, staggered scanline pattern confined
  to roughly the top 25% of the screen, with the remaining ~75%
  unchanged solid red -- a partial, incomplete render, not the fallback
  either.
- Neither direction triggered the panel's usual cached fallback
  animation -- notably different from every other content-validation
  failure in this whole investigation (the transition/run-structure
  violations, the 528-byte-prefix threshold violations), which always
  fell back to the same generic animation. Both restores this round
  acked and took immediately, confirmed back to the original
  solid-red/3-stripe alternation.

### Changed
- Confirms `mode_flag` is a genuine, functional field selecting between
  two different decoders, not a passive/descriptive tag -- forcing a
  mismatch doesn't get validated-and-rejected the way most content edits
  in this investigation have been; it just gets decoded wrong, producing
  visibly structured (not random) garbage. This suggests whatever
  structural validation exists (the transition/run-structure check, the
  528-byte-prefix count threshold) is checked WITHIN each decoder's own
  path, not by a separate universal content check applied regardless of
  mode -- a mismatched mode_flag bypasses the checks that would normally
  catch a malformed frame in its own format, because the bytes are being
  fed to the wrong decoder entirely rather than being malformed input to
  the right one.

### Known gaps
- The exact byte-level mechanics of the raw-bitmap overrun (whether it
  really reads into frame 1's real flash bytes, the precise mapping of
  visible bands to specific byte ranges) aren't confirmed -- only the
  qualitative "garbled but structured, resembling neighboring frame
  content" result.
- Why the RLE-misinterpretation case fills only ~25% of the screen before
  stopping isn't explained precisely (plausible: interpreting bytes as
  length/flag pairs instead of raw indices roughly halves how many
  content bytes correspond to one pixel of coverage, so the declared
  content-length in bytes runs out before covering all 153600 pixels --
  not verified with an exact token-count calculation against the photo).
- Only tested on save_to_gif_13's two frames; whether this generalizes to
  other content is untested.
- Same open items otherwise: the 528-byte prefix's true purpose, the
  exact dithering diffusion algorithm, `save_to_gif_2`'s inefficiency.

## [0.7.4] - 2026-07-30

**"Save to GIF": linear interpolation between bracket rungs is a good
approximation of the per-channel duty cycle, but not an exact formula --
consistent with error diffusion, not a precise closed-form computation.**
Offline re-analysis of `save_to_gif_14.pcapng` (no new hardware), now
possible because 0.7.2/0.7.3 nailed down the exact ramp.

### Verified
- For every column/channel needing two-rung dithering (960 data points
  across the 320-column rainbow), computed the naive "linear
  interpolation between the two bracketing ramp rungs" predicted duty
  cycle and compared it to the actual observed duty cycle (from real
  pixel counts). Mean absolute deviation: 3.4 percentage points. Mean
  *signed* deviation: 0.002 -- effectively zero, meaning there's no
  systematic bias toward either rung; deviations are roughly balanced
  (357 columns observed-high, 212 observed-low, 391 close enough to call
  exact).
- The worst individual mismatches (up to 26 percentage points) cluster
  near ramp segments close to 0 (e.g. the `{0,40}` G bracket), not
  uniformly across the whole range.

### Changed
- Confirms linear interpolation is the right first-order model for
  *what* duty cycle each dithered channel is aiming for, but the actual
  per-column result isn't a precise closed-form computation -- it has
  real, non-negligible variance (well above simple integer-rounding noise
  at 480 samples, which would be under 0.3 percentage points). This is
  more consistent with an error-diffusion-style algorithm, which
  approximates the correct long-run ratio well but doesn't hit it exactly
  in a finite sample, than with an exact ordered-dither formula.

### Known gaps
- The actual diffusion algorithm (coefficients, propagation direction,
  whether it resets per column/row or runs continuously across the whole
  raster) is still not decoded -- this round confirms the *character* of
  the deviation (unbiased, real variance, concentrated near certain
  bracket segments) without identifying the mechanism.
- Same open items otherwise: the G ramp's off-by-one, the 528-byte
  prefix's true purpose, `mode_flag`'s general meaning, `save_to_gif_2`'s
  inefficiency.

## [0.7.3] - 2026-07-30

**"Save to GIF": the dither ramp extends all the way to each channel's
native maximum -- closing 0.7.2's open question about higher rungs.**
`save_to_gif_15.pcapng` -- the same hue sweep as `save_to_gif_14`, but at
95% brightness instead of 70% (targets up to 242, much closer to the
255 ceiling) -- was captured specifically to probe for rungs above the
ones seen before.

### Verified
- Two new top rungs appear that 0.7.2's dimmer test never triggered: R/B
  index 31 (= 255) and G index 63 (= 255). Combined with the previously
  known rungs, the full ramps are now: R and B, 6 levels -- `{0, 6, 12,
  19, 25, 31}` (8-bit: 0, 49, 99, 156, 206, 255); G, 7 levels -- `{0, 10,
  21, 32, 42, 53, 63}` (8-bit: 0, 40, 85, 130, 170, 215, 255).
- The R/B ramp is an *exact* even 6-way split of the full 0-31 native
  range (`round(i*31/5)` for i=0..5 reproduces `{0,6,12,19,25,31}`
  precisely). The G ramp is very close to but not quite an exact even
  7-way split of 0-63 -- it differs from the naive rounding of `i*63/6`
  by exactly 1 at a single point (53 vs. an evenly-rounded 52); every
  other level matches exactly. Reported honestly as "very close, not
  exact" rather than forcing a clean formula that doesn't quite fit.
- Weighted-average color per column again matches the intended target
  hue closely across all 320 columns at this brighter setting: mean error
  ~3.8/255, max ~10.5/255 -- consistent with 0.7.2's dimmer test, now
  confirmed at a second, much brighter setting.
- Both frames again `mode_flag=0x0002` raw-bitmap, byte-identical to each
  other, content exactly 153600 bytes -- same structural confirmations as
  every prior raw-bitmap capture.

### Changed
- The dither ramp is now fully characterized end-to-end: it spans each
  channel's ENTIRE native range (0 to 31 for 5-bit R/B, 0 to 63 for 6-bit
  G), not capped below the maximum as 0.7.2 left open. The apparent "cap"
  in that round was purely because neither test image's targets were
  bright enough to need the top rung -- not a real property of the ramp.

### Known gaps
- The G ramp's single off-by-one deviation from a naive even split is
  unexplained -- worth keeping in mind if it recurs or resolves with more
  data.
- Same open items as 0.7.2 otherwise: the exact snap-vs-dither selection
  rule and duty-cycle algorithm, the per-row variation's mechanism, the
  528-byte prefix's true purpose, `mode_flag`'s general meaning,
  `save_to_gif_2`'s inefficiency.

## [0.7.2] - 2026-07-30

**"Save to GIF": found the dithering ramp -- a FIXED, shared set of RGB565
quantization levels, reused verbatim across totally different images.**
`save_to_gif_14.pcapng` -- a dimmed rainbow (full hue sweep, ~70%
brightness, so every one of 320 columns needs dithering) -- gives by far
the richest dithering dataset yet, and it resolves the open question of
whether dither-pair colors are computed per-image or drawn from something
fixed.

### Verified
- Both frames (identical source images, as designed) are `mode_flag=0x0002`
  raw-bitmap, byte-for-byte identical to each other -- consistent with
  every prior finding (deterministic, content-driven encoding; raw bitmap
  for busy/richly-dithered content).
- Weighted-average color per column (using actual per-pixel flag
  frequencies and the real palette) matches the intended target hue
  closely across all 320 columns: mean error ~4/255, max ~11.5/255. This
  is the broadest confirmation yet that the dithering genuinely
  reconstructs the intended color on average, not just for the 1-2 colors
  tested before.
- The palette (46 entries) decomposes, in RGB565's native per-channel
  index terms, into two small FIXED sets: R and B indices are only ever
  one of {0, 6, 12, 19, 25} (of 0-31 possible); G indices are only ever
  one of {0, 10, 21, 32, 42, 53} (of 0-63 possible) -- a 5-level ramp for
  the 5-bit channels and a 6-level ramp for the 6-bit channel, each
  roughly evenly spaced from 0 up to their top rung (206/255 for R and B,
  215/255 for G).
- Cross-checked directly against `save_to_gif_13`'s completely different
  image (light gray + dark red stripes): every one of its dithered
  palette entries' per-channel indices falls within this SAME ramp. The
  one exception (R index 31, i.e. 255) is the clean, undithered reference
  red -- not part of the dither ramp at all, consistent with 255 already
  being a direct-slot "safe" value needing no dithering.
- Confirmed rows are NOT identical within a column (row 0 != row 240 !=
  row 479 for the same target color) -- the per-row variation seen in
  `save_to_gif_13`'s light-gray stripe is pervasive across this whole
  image, not a minor addendum to an otherwise-static pattern.

### Changed
- Refines the model significantly: dithering doesn't compute a bespoke
  pair of nearby colors per target -- it snaps each channel independently
  to the nearest rung(s) of this SAME fixed 5-level/6-level ramp,
  dithering between two adjacent rungs when the target falls between them
  and just using a single rung directly (no dithering for that channel)
  when it's already close enough. Different pixels use anywhere from 2 to
  4 distinct palette entries depending on how many of the 3 channels
  actually need bracketing for that specific target -- not always the
  full 8-corner combinatorial scheme seen for `save_to_gif_13`'s one
  richly-dithered color.
- This is very likely a genuine, image-independent hardware/firmware
  lookup table, not something computed fresh per upload -- the same exact
  rung values appearing byte-for-byte in two unrelated captures is strong
  evidence against per-image computation.

### Known gaps
- Whether the ramp has MORE/higher rungs than observed (n=25/53 might just
  be the highest rung our two test images ever needed, since neither
  reached the very top of the brightness range) is untested -- would need
  a brighter test image (targets approaching 255) to check for rungs above
  the ones seen so far.
- The exact rule for choosing single-rung-snap vs. two-rung-dither per
  channel, and the exact duty-cycle-selection algorithm between two rungs,
  is still not decoded -- only the SET of available rungs is now known.
- The per-row variation's exact mechanism (still hypothesized as error
  diffusion, not confirmed) has much richer data to work with now but
  hasn't been re-analyzed against this larger dataset yet.
- Same longstanding open items otherwise: the 528-byte prefix's true
  purpose, `mode_flag`'s general meaning, `save_to_gif_2`'s inefficiency.

## [0.7.1] - 2026-07-30

**"Save to GIF": `--target gif` is now a real CLI feature, confirmed
working end-to-end on hardware.** Wires up 0.7.0's proof-of-concept
encoder into `protocol.py`/`cli.py` properly, rather than leaving it a
standalone script.

### Added
- `protocol.build_gif_blob(frames_pixels, width, height, delay=50)`: the
  from-scratch encoder from 0.7.0, generalized -- takes any number of
  frames, validates every pixel's color up front and raises a `ValueError`
  listing every offending color and its pixel count if any need dithering,
  and raises a clear `ValueError` (naming the largest run found and the
  capacity needed) if no frame has a large enough solid/uniform region for
  the `CRC_INIT`-length-matching trick to work. Re-verified byte-for-byte
  identical to 0.7.0's hand-built, hardware-confirmed blob.
- `cli.py`: `--upload` now takes one or more image paths (`nargs="+"`).
  `--target gif` builds a multi-frame GIF from them (one image per frame);
  every other target still requires exactly one image, erroring clearly
  otherwise. New `--gif-delay` flag (default 50, matching every capture).

### Verified
- Real end-to-end test: two fresh PNGs (solid blue, a 16x16 red/white
  checkerboard) written via PIL, uploaded with the actual
  `python3 -m aula_l99_screen.cli --upload frame0.png frame1.png --target
  gif` command -- not a script bypassing the CLI. All 12 packets acked,
  and the user confirmed the panel showed the intended animation.
- The full pipeline (image loading through `cli.py`'s new
  `_encode_gif_frame_pixels()`, then `protocol.build_gif_blob()`) produces
  a blob byte-for-byte identical to 0.7.0's manually-verified one.

### Fixed
- `Image.getdata()` is deprecated in Pillow >=12 (removal slated for
  Pillow 14, 2027-10-15); `cli.py` now prefers `get_flattened_data()` when
  available, falling back for older Pillow versions.

### Known gaps
- Same scope limits as 0.7.0: RLE-mode, non-dithered ("safe") colors only.
  Photos, the raw-bitmap format, and dithering are still out of reach for
  an encoder.
- Not stress-tested with more than 2 frames, larger palettes, or images
  without a large solid region (the error path is implemented and unit
  tested, but not exercised against a real user image that hits it).

## [0.7.0] - 2026-07-30

**"Save to GIF": the first fully from-scratch GIF -- not derived from any
capture -- rendered correctly on hardware.** Every success before this
round was a small edit to already-valid captured content; this is the
first proof the RLE model is complete enough to actually build new
working uploads, not just decode and mutate existing ones.

### Verified
- Hand-built a 2-frame, 320x480 blob purely from the confirmed model: a
  TOC of 20-byte entries, each frame a 528-byte fixed prefix (copying the
  two still-unexplained-but-always-constant magic byte pairs verbatim,
  writing width/height/size32/content-length/mode_flag/palette from
  scratch) followed by continuous-raster-order RLE content (palette
  built in first-appearance order, runs chained in <=256px pieces,
  restricted to "safe" colors -- max(R,G,B) in {0,255} -- so no dithering
  needs to be solved). Content: frame 0 solid blue, frame 1 a 16x16 red/
  white checkerboard -- new content, never captured or mutated from one.
- Solved the practical `CRC_INIT` obstacle without any new brute-force:
  since a solid run can be split into any number of chained same-flag
  tokens without changing the rendered image (each split costs exactly 2
  bytes), the blob's total length was tuned by padding frame 0's single
  run into more pieces until the wire packetization's final chunk landed
  on an already-solved length (1080 bytes, from `save_to_gif_12`) with no
  new CRC_INIT value needed and no external padding bytes.
- Self-verified before upload: TOC `crc16_modbus` matches, both frames'
  RLE content sums to exactly 153600 pixels, packetizes to 12 packets with
  no exceptions.
- Uploaded to the panel: all 12 packets acked, and the panel showed
  exactly the intended animation -- solid blue alternating with the red/
  white checkerboard -- confirmed by the user, not the fallback.

### Changed
- This is the strongest evidence yet that the GIF format's RLE encoding,
  TOC/sub-header layout, and packetization are genuinely fully understood
  for the "safe colors, no dithering" case -- not just consistent with
  every capture examined, but sufficient to construct new, independently
  verified working uploads.
- Scope: this specific success is for `mode_flag=0x0100` RLE-encoded
  content only, using colors that don't need dithering. Photos, the
  raw-bitmap format, and any color requiring dithering are still out of
  scope for an encoder -- the palette/dithering assignment algorithm
  (0.6.6-0.6.9, 0.6.18) isn't solved well enough to build correct
  dithered content from scratch yet.

### Known gaps
- Not yet wired into `cli.py` as a real `--target gif` option -- this was
  a standalone proof-of-concept script, not integrated tooling.
- The `CRC_INIT`-length-matching trick (splitting a solid run to hit an
  already-known final-chunk length) only works when some frame has a
  large enough solid/uniform region to split -- a general encoder needs a
  fallback or a clear error for images that don't have one.
- No multi-frame (>2), non-solid-reference-frame, or larger/more complex
  from-scratch content has been tried yet.
- Same longstanding open items otherwise: the 528-byte prefix's true
  purpose, the dithering algorithm, `mode_flag`'s general meaning, the
  delay field's unit, `save_to_gif_2`'s inefficiency.

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
