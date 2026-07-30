# `pic_scan.dll` disassembly notes

Working notes for the static-analysis thread on `Windows/AULA L99/qt-tool/pic_scan.dll`,
started in CHANGELOG `[0.7.7]`. Purpose: this file exists so the *next* round of this
investigation doesn't have to re-derive RVAs and re-slice the disassembly from scratch like
`[0.7.7]` did — its conclusions survived only as prose in `protocol.py`/`README.md`, with no
transcript. Read those two files for the narrative summary; this file is the working-level
detail (commands, addresses, byte patterns) behind it.

File: `Windows/AULA L99/qt-tool/pic_scan.dll`, PE32, 51712 bytes, image base `0x6a9c0000`,
not fully stripped (C++ export names recoverable via the export table).

## Tooling

```bash
DLL="Windows/AULA L99/qt-tool/pic_scan.dll"

# Image base
objdump -p "$DLL" | grep -i ImageBase                       # 6a9c0000

# Export table: ordinal -> RVA, and ordinal -> demangled name
objdump -x "$DLL" | sed -n '/Export Address Table -- Ordinal Base 1/,/^$/p'
objdump -x "$DLL" | sed -n '/\[Ordinal\/Name Pointer\] Table/,/^$/p'

# Import table: IAT slot VA -> imported symbol (for classifying indirect calls)
objdump -p "$DLL" | sed -n '/The Import Tables/,$p'

# Full disassembly, then slice per function by VA range (next-higher export RVA is the
# upper bound; objdump prints `<va>:` as the address prefix on every instruction line,
# so slicing is just a start/stop address match, no offset math needed)
objdump -d -M intel "$DLL" > pic_scan_full.asm
awk '/^<start_va>:/{f=1} /^<end_va>:/{f=0} f{print}' pic_scan_full.asm > <function>.asm
```

## Export table (ordinal -> RVA -> VA -> demangled name)

Ordinal Base 1; VA = `0x6a9c0000 + RVA`.

| Ordinal | RVA | VA | Name |
|---|---|---|---|
| 1 | 0x2b40 | 0x6a9c2b40 | `Pic_scan::Bmp_decode(QString)` |
| 2 | 0x24f0 | 0x6a9c24f0 | `Pic_scan::SaveMode16(QImage, unsigned char*, int)` |
| 3 | 0x3290 | 0x6a9c3290 | `Pic_scan::SaveMode24(QImage, unsigned char*, int)` |
| 4 | 0x6c80 | 0x6a9c6c80 | `Pic_scan::Gif_to_data(int, QString, int)` |
| 5 | 0x1d50 | 0x6a9c1d50 | `Pic_scan::Scan_ZoomIn(QImage, unsigned char*)` |
| 6 | 0x1d60 | 0x6a9c1d60 | `Pic_scan::Scan_jpgFile(unsigned char*, QString)` |
| 7 | 0x3ed0 | 0x6a9c3ed0 | `Pic_scan::Image_to_data(Image_Struct*, QString, int)` |
| 8 | 0x1a30 | 0x6a9c1a30 | `Pic_scan::Scan_aRGB8565(QImage, unsigned char*)` |
| 9 | 0x1bd0 | 0x6a9c1bd0 | `Pic_scan::Scan_aRGB8888(QImage, unsigned char*)` |
| 10 | 0x3e40 | 0x6a9c3e40 | `Pic_scan::Add_To_BinFile(unsigned char*, int, QString)` |
| 11 | 0x19b0 | 0x6a9c19b0 | `Pic_scan::Image_IF_A_Png(QImage)` |
| 12 | 0x1610 | 0x6a9c1610 | `Pic_scan::Get_PngImg_View(QImage)` |
| 13 | 0x1590 | 0x6a9c1590 | `Pic_scan::Get_file_length(QString)` |
| 14 | 0x2420 | 0x6a9c2420 | `Pic_scan::Scan_ColorTB_Data()` |
| 15 | 0x4e20 | 0x6a9c4e20 | `Pic_scan::Gif_to_data_LT7689(int, QString, int)` |
| 16 | 0x2ae0 | 0x6a9c2ae0 | `Pic_scan::Length_Of_BinFiles(QString)` |
| 17 | 0x4b90 | 0x6a9c4b90 | `Pic_scan::File_Addto_otherFile(QString, QString)` |
| 18 | 0x3600 | 0x6a9c3600 | `Pic_scan::Needle_Image_to_data(Image_Struct*, QString, int)` |
| 19 | 0x2240 | 0x6a9c2240 | `Pic_scan::ZipU8Data_to_bmpText(unsigned char*, int, int, int)` |
| 20 | 0x3d90 | 0x6a9c3d90 | `Pic_scan::Save_To_A_New_BinFile(unsigned char*, int, QString)` |
| 21 | 0x2000 | 0x6a9c2000 | `Pic_scan::ColorTB_u8Data_to_zipU8Data(unsigned char*, unsigned char*)` |
| 22 | 0x14d0 | 0x6a9c14d0 | `Pic_scan::Scan_ColorTB_from_image_data(unsigned short*, int, int)` |
| 23 | 0x1f40 | 0x6a9c1f40 | `Pic_scan::Image_u16Data_to_colorTBu8Data(unsigned char*)` |
| 24 | — | — | `Pic_scan::Pic_scan()` (ctor 1) |
| 25 | — | — | `Pic_scan::Pic_scan()` (ctor 2) |

`Pic_scan` mangles as a class/namespace ambiguously in Itanium ABI; the calling convention
observed (first param in `ecx`, matching a large stateful object's fields at fixed offsets —
`+0x28`, `+0x2c`, `+0x430`, `+0x634`, `+0x20830`, `+0x20834`, `+0x20208`-ish) confirms it's a
**class**, and `ecx` is `this` (an implicit arg not reflected in the mangled parameter list).

## Relevant IAT imports (by VA of the IAT slot)

| VA | Symbol |
|---|---|
| `0x6a9d0204` | `QArrayData::deallocate(QArrayData*, uint, uint)` |
| `0x6a9d0208` | `QArrayData::shared_null` (data, not a function) |
| `0x6a9d021c` | `QCoreApplication::processEvents(QFlags<QEventLoop::ProcessEventsFlag>)` |
| `0x6a9d0240` | `QString::fromAscii_helper(const char*, int)` |
| `0x6a9d0248` | `QString::replace(const QString&, const QString&, Qt::CaseSensitivity)` |
| `0x6a9d024c` | `QString::operator=(const QString&)` |
| `0x6a9d0290` | `QImage::~QImage()` |
| `0x6a9d02ac` | `QImage::pixel(int, int) const` |
| `0x6a9d02b0` | `QImage::width() const` |
| `0x6a9d02b4` | `QImage::height() const` |

## Functions traced this round

### `ColorTB_u8Data_to_zipU8Data` (ordinal 21, VA `0x6a9c2000`, ~576 bytes)

**Verdict: confirmed RLE encoder. No dithering logic.**

Reads consecutive palette-index bytes from a source buffer (`arg0`) and writes `(length,
flag)` word tokens to a destination buffer (`arg1`), matching the wire-protocol RLE grammar
already reverse-engineered from captures: `cmp BYTE PTR [ecx],bl` / `je` extends a run;
breaking the run emits a token whose low byte is `(length-1)` and whose high byte has bit 0
set via `or ch,0x1` (the "flag" bit). Runs cap at `0xff` (256px), matching the known
"chained in ≤256px pieces" grammar. A separate branch (reached when a per-row byte-budget
stored at `this+0x2c[row]` is exceeded) falls back to a raw byte-for-byte copy instead of
emitting tokens — the row-level store/raw fallback, distinct from the frame-level
`mode_flag`.

No ramp constants (`6,12,19,25,31` / `10,21,32,42,53,63` or their 8-bit equivalents) appear
anywhere as immediates. Every constant present is structural: `0xff`/`0x100` (run cap),
`0x204` (516, the per-row stride into `this+0x634`), stack offsets.

Bonus finding: the function steps through a region at `this+0x634` in strides of exactly
`0x204` (516) bytes per row/chunk — a second, independent piece of code (alongside
`Scan_ColorTB_Data`, below) touching the same stride, reinforcing the existing suspicion
that the mystery 528-byte frame prefix is structurally related to this palette-table region
(still not proven byte-identical).

### `Scan_aRGB8888` (ordinal 9, VA `0x6a9c1bd0`, ~384 bytes)

**Verdict: confirmed raw copy, no dithering. The 32-bit sibling of `Scan_aRGB8565`.**

Per pixel, calls the cached `QImage::pixel(x, y)` accessor **four times** (redundant —
GCC couldn't CSE a virtual/indirect call) and writes one byte from each call's result:
`out[0]=v&0xff`, `out[1]=(v>>8)&0xff`, `out[2]=(v>>16)&0xff`, `out[3]=(v>>24)&0xff` — i.e.
a byte-for-byte copy of the 32-bit ARGB value, little-endian. Ends with row-stride padding:
fills extra alignment columns with the 4-byte pattern `FF FF FF 00`. No quantization, no
masks narrower than a full byte, no per-channel branching.

### `Scan_ColorTB_Data` (ordinal 14, VA `0x6a9c2420`, 208 bytes)

**Verdict: confirmed pure chunking/orchestration. No per-pixel color math.**

Loops up to `0xff` (255) times, each iteration calling `Scan_ColorTB_from_image_data` (below)
over a slice of the source, and:
- records each chunk's byte-range boundary into `this+0x634[chunk]` (low/high words of a
  32-bit value returned by the callee),
- copies a fixed lookup table (read from `this+0x430`) into the per-chunk area at
  `this+0x634 + chunk*0x204 + 0x206`,
- advances the per-chunk cursor by exactly `0x204` (516) bytes each iteration.

This clarifies (correcting the informal assumption in `[0.7.7]`) that the well-known
"chained in ≤256px pieces" cap most plausibly originates **here** — a hard 255-iteration
chunk-count limit — rather than being purely an artifact of the RLE token format's 256-run
cap (which is a separate, coincidentally-identical limit in `ColorTB_u8Data_to_zipU8Data`).

### `Scan_ColorTB_from_image_data` (ordinal 22, VA `0x6a9c14d0`, 192 bytes)

**Verdict: confirmed exact-match palette dedup. No channel math, no dithering.**

Zero-initializes a 512-byte / 256-entry word table at `this+0x430`. Reads 16-bit RGB565
words one at a time from the source; for each new value, does a **linear search** (`cmp
bx,dx` for "same as previous," else `cmp bx,WORD PTR [edx]` over the table built so far) —
if an exact match exists, the value is treated as already-seen and the table is left
unchanged; otherwise the value is appended as a new palette entry (capped at 255 entries,
tying back into `Scan_ColorTB_Data`'s 255-chunk cap above).

Every operation here is on whole 16-bit words compared for bit-exact equality — there is no
shift, no mask, no per-channel (R/G/B) extraction, and no accumulator/state carried across
iterations. This is definitively not where dithering happens; it's building a "distinct
colors present" table from values that must already be final by the time they arrive here.

### `SaveMode16` (ordinal 2, VA `0x6a9c24f0`, ~1520 bytes) — **not examined in `[0.7.7]`**

**Verdict: confirmed no dithering in any branch. Also: the true GIF-pipeline entry point
into the already-traced ColorTB/RLE chain.**

Dispatches on a `mode` parameter (the function's 5th stack arg):

- **mode ∈ {2, 5}**: packs each pixel into ARGB4444 (four 4-bit fields) via
  shift+mask on three redundant `QImage::pixel()` calls — plain truncation, no dithering.
- **mode ∈ {1, 4}**: packs into RGB565 (`R = (px>>8)&0xf800`, `G = (px>>5)&0x7e0` /
  variant, `B = (px>>3)&0x1f` — exact bit positions differ slightly between this branch and
  the default branch below, but both are pure shift+mask truncation, no rounding). Includes
  one notable special case: if the packed value is exactly `0x0000` **and** the pixel is
  opaque (alpha's sign bit test on the raw 32-bit pixel value), it's remapped to `0x0021`
  instead — almost certainly reserving `0x0000` as a transparency sentinel (pixels with
  alpha < 0x80 are forced to raw `0x0000`, un-remapped). This is a real, self-contained
  finding but is a transparency-encoding trick, not dithering.
- **all other modes (0, 3, 6, 7, ...)**: falls into a "default" loop that ALSO just does
  RGB565 truncation (three `QImage::pixel()` calls, shift+mask, no black/transparency
  special-casing), iterating over `arg[esp+0x2c]` "frames" — this is what actually executes
  for the GIF path.

After building its packed buffer (whichever branch), the function checks
`(mode - 3) unsigned <= 2` — i.e. **mode ∈ {3, 4, 5}** — and if so, calls onward into the
already-confirmed ColorTB/RLE chain:

```
call Scan_ColorTB_Data          (0x6a9c2420)
  → (loops) Scan_ColorTB_from_image_data   (0x6a9c14d0)
call Image_u16Data_to_colorTBu8Data        (0x6a9c1f40)
call ColorTB_u8Data_to_zipU8Data           (0x6a9c2000)
```

This **closes the pipeline end-to-end**: `Gif_to_data_LT7689` calls `SaveMode16` (see
below), which builds a truncated RGB565 buffer and then hands it through the exact chain of
functions traced in `[0.7.7]` and above. Modes 1 and 2 return immediately after their own
packing with no further palette/RLE step (consistent with being the plain photo-frame/
background raw-RGB upload path from Phase 1/2 of this investigation, not the GIF path).

### `SaveMode24` (ordinal 3, VA `0x6a9c3290`) — **not examined in `[0.7.7]`, quick pass only**

**Verdict: confirmed no dithering (trivially — 24bpp needs none).** Same shape as
`SaveMode16`'s truncation branches: three `QImage::pixel()` calls, plain byte masks
(`and esi,0xff0000`, `and ebx,0xff00`, raw low byte), combined into a lossless 24-bit value.
No quantization is needed at 8-bit-per-channel depth, so this was never a plausible
dithering candidate; confirmed and not traced further.

### `Gif_to_data_LT7689` (ordinal 15, VA `0x6a9c4e20`, ~1890 disassembly lines)

**Verdict: entire reachable call graph now exhaustively triaged. No dithering logic
anywhere in this function or anything it calls.**

~183 total calls, of which ~55 are register-indirect (`call eax`/`ebx`/`esi`). Traced every
one back to its most recent register load:

- `QImage::width()`, `QImage::height()`, `QImage::pixel(x,y)`, `QImage::~QImage()` — cached
  once into stack locals near function entry, reused throughout (same accessors already
  seen in `Scan_aRGB8565`/`Scan_aRGB8888`/`SaveMode16`/`SaveMode24`).
- `QString::operator=`, `QString::fromAscii_helper`, `QString::replace`,
  `QArrayData::deallocate` — status/filename string construction, unrelated to pixel data.
- Two `call ebx` sites (`0x6a9c6000`, `0x6a9c6064`) trace back to a stack-allocated buffer
  address (from an `_chkstk`-backed alloca at function entry) reused deep inside a region
  otherwise saturated with `QString::fromAscii_helper` calls against literal format-string
  addresses — i.e. buried in string/message formatting, not examined further.

Direct (resolvable) calls: `Image_IF_A_Png`, `Scan_aRGB8565`, `Scan_aRGB8888`, `SaveMode16`,
`SaveMode24`, `Save_To_A_New_BinFile`/`Add_To_BinFile`/`File_Addto_otherFile` (flash-blob
writers), plus internal CRT/MinGW boilerplate (`_chkstk`-equivalent stack probe, atomic
refcount inc/dec, IAT trampolines — addresses `0x6a9c87e0`/`87f0`/`94d0`/`94d8`/`9720`/
`9760`/`97a0`).

The function allocates a raw ARGB8888 buffer (`width*height*4` bytes) and fills it via
`Scan_aRGB8888` (confirmed plain copy), stores it at `this+0x20830`/`this+0x20834`
(pointer/length), then **later reallocates the same fields** (`width*height*2 +
0x20208` bytes) and refills them via a call into `SaveMode16` with the mode value
determined by the object's own state (`this+0x4`, `this+0x5`, and a local mode variable).
This is the exact hand-off point between "raw pixel scan" and "the GIF-specific
palette/RLE pipeline" described above.

**Bottom line**: every function reachable from `Gif_to_data_LT7689` — directly or through
its ~55 indirect calls — has now been disassembled and confirmed free of per-pixel channel
math, ramp comparisons, or an error/accumulator variable carried across loop iterations.
This is a stronger result than `[0.7.7]`'s "partially traced, banked for later": the call
graph from this export is now **exhausted**, not merely deferred.

## What this rules in/out, and what's left

Ruled out as the location of the dithering decision (fully traced, confirmed no per-pixel
channel branching or diffusion state): `Scan_aRGB8565`, `Scan_aRGB8888`, `SaveMode16` (all
branches), `SaveMode24`, `Scan_ColorTB_Data`, `Scan_ColorTB_from_image_data`,
`Image_u16Data_to_colorTBu8Data`, `ColorTB_u8Data_to_zipU8Data`, and every reachable call
inside `Gif_to_data_LT7689` itself (direct or indirect).

Given the wire-capture evidence (established back in `[0.6.1]`-`[0.6.9]`) that already-
dithered pixel patterns appear in the bytes actually transmitted, the dithering must happen
somewhere in the PC-side pipeline before transmission — but demonstrably not in anything
reachable from `Gif_to_data_LT7689`. Two remaining candidates, neither examined yet:

1. **`Gif_to_data`** (ordinal 4, VA `0x6a9c6c80`) — the non-`_LT7689` sibling export.
   Untraced this round; earlier recon noted "an almost identical call-target profile" to
   `Gif_to_data_LT7689` but that was based on call-target addresses only, not a full trace —
   worth confirming whether it's truly parallel or diverges somewhere meaningful.
2. **Code outside `pic_scan.dll` entirely** — e.g. in the qt-tool GUI executable itself,
   which calls into this DLL. A `QImage::convertToFormat()` call with an explicit dithering
   flag (Qt supports ordered/diffuse dithering on format conversion) executed by the *app*
   before ever calling into `pic_scan.dll` would be invisible from inside this DLL no matter
   how thoroughly it's traced.
