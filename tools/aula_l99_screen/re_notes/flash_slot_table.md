# The panel's flash slot table

How much flash the GIF slot gets, recovered from the firmware images embedded in the
vendor's updater executables. Prompted by the question "if we disassemble the Windows
binary, can we see how much memory gets allocated to the gif area?" — the answer turned out
to be yes, but not from the binary that question implies.

Result up front, in two parts:

1. **Found:** six flash bases on a uniform `0x60000` (393,216 byte) stride, three of which
   match bases already derived from wire captures, exactly. Real, and it confirms the two
   slots whose size was already known by subtraction.
2. **Does not follow:** that the GIF slot is also `0x60000`. `SLOT_CAPACITY` was briefly
   changed to that and has been changed back. GIF is the *last* table entry, so the stride
   cannot be checked there by subtraction, and the vendor's own shipped assets rule the
   figure out outright — see "Why the GIF slot is not one stride" below. That section is the
   most important one in this file.

## The host binaries have nothing

Worth recording as a dead end so it isn't re-walked. Searched for the three known bases
(`0x04180000` BKG, `0x041E0000` photo-frame, `0x04240000` GIF) as 4-byte little-endian
immediates:

| Binary | Hits |
|---|---|
| `qt-tool/pic_scan.dll` | none |
| `qt-tool/Image2Bin.exe` | none |
| `qt-tool/SerialPortTool.exe` | none |
| `DeviceDriver.exe` | 2, both false |

`DeviceDriver.exe`'s two apparent hits are at file offsets `0x18832a` and `0x188332`, inside
this run:

```
00188320  ff ff ff ff 10 04 56 00 00 00 00 00 18 04 56 00
00188330  01 00 00 00 20 04 56 00 22 05 93 19 02 00 00 00
```

Those are misaligned reads straddling `(pointer, int)` pairs in an MFC table — reading four
bytes from `0x18832a` picks up `00 00 18 04` from the tail of one field and the head of the
next. Not constants. `0x041E0000` does not appear in `DeviceDriver.exe` at all, which is the
tell: a binary that held the flash map would have all three, not two-thirds of them by
accident.

The host software never knows the map. It is handed addresses.

## Where the table actually is

Both firmware updaters carry it, twice each:

| File | Size | 5-entry run at | second copy at |
|---|---|---|---|
| `Windows/AULA L99/firmware/L99 ISP V1.23.exe` | 67,359,136 | `0x398f42` | `0x3e57e2` |
| `Windows/L99 keyboard Screen reset firmware （...).exe` | 194,946,048 | `0x398fb2` | `0x3e5aee` |

The two files' offsets differ by a constant `0x70`, so these are the same payload with a
different wrapper — the 194MB one is Enigma-packed (see `screen_firmware_updater.md`), but
this region is not encrypted in either. The content is not i386; it is the panel-side
firmware, which is why it has the map when the PC-side code doesn't.

## The table

At `0x398f42` in `L99 ISP V1.23.exe`:

```
00398f40  81 00 00 00 06 04 00 00 0c 04 00 00 12 04 00 00
00398f50  18 04 00 00 1e 04 e8 33 81 00 e4 85 03 60 d0 2a
00398f60  81 00 30 89 03 60 d8 33 81 00 00 00 24 04 dc 52
```

Five contiguous little-endian dwords starting at `0x398f42`, then the sixth `0x28` bytes
further on at `0x398f6a`:

| # | Value | Known as | Delta from previous |
|---|---|---|---|
| 1 | `0x04060000` | — | — |
| 2 | `0x040C0000` | — | `0x60000` |
| 3 | `0x04120000` | — | `0x60000` |
| 4 | `0x04180000` | `BACKGROUND_FLASH_BASE` | `0x60000` |
| 5 | `0x041E0000` | `PHOTO_FRAME_FLASH_BASE` | `0x60000` |
| 6 | `0x04240000` | `GIF_FLASH_BASE` | `0x60000` |

Entries 4, 5 and 6 are the three bases this project already derived from captures, in order,
on the lattice. That is what makes entries 1-3 and the stride worth believing rather than
being a coincidence of six aligned numbers.

Immediately after the five contiguous entries comes a parallel run of dwords in a different
range, in the second copy most clearly:

```
003e57e0  81 00 00 00 06 04 00 00 0c 04 00 00 12 04 00 00
003e57f0  18 04 00 00 1e 04 0c 35 81 00 10 35 81 00 14 35
003e5800  81 00 18 35 81 00 1c 35 81 00 d4 08 80 00 6e 95
003e5810  01 60 00 04 04 60 f4 2b 81 00 4c 07 04 60 fc 34
003e5820  81 00 00 00 24 04 10 94 01 60 20 35 81 00 16 60
```

`0x0081350C`, `0x00813510`, `0x00813514`, `0x00813518`, `0x0081351C` — five addresses at a
4-byte stride, one per flash slot — and then `0x00813520`, the sixth, sitting right next to
the GIF base at `0x3e5822`. A per-slot descriptor or handle array in RAM. Not chased further.

The gap between the fifth entry and the GIF base differs between the two copies (`0x28` vs
`0x40` in the ISP file, `0x28` vs `0x44` in the screen one), so this is not a single static
array in both places — one of the copies has intervening instructions. The stride and the
membership are what the two copies agree on.

## `0x04200000` is still not a boundary

Ruled out again, on new grounds. It is not on the `0x60000` lattice at all (the lattice
runs `...0x041E0000, 0x04240000`, straight past it), which is a stronger reason to stop
treating it as a slot base than the previous one (that ordinary photo-frame writes overlap
it). Still unidentified.

## Why the GIF slot is not one stride

The table gives entries 1-5 a size by subtraction from the next base. Entry 6 (GIF) has no
next base, so its size was taken to be the stride by inference. That inference is wrong, and
the way it was reached is worth recording because it looked well-supported at the time.

The vendor's own stock animations, shipped in `Windows/AULA L99/gif/`:

| Asset | Frames | Size |
|---|---|---|
| `AULA L99/0.gif` | 214 | 320x480 |
| `用户动画(1)/1.gif` … `6.gif` | 200 each | 320x480 |
| `AULA L99J/0.gif` | 128 | 320x480 |

Fitting 214 frames into 393,216 bytes requires **1,837 bytes per frame**. The only captures
that ever got that low are the flat solid-colour test patterns (`save_to_gif_3`: 2,048).
Real content does not come close — `save_to_gif_1`, an actual photo GIF, took **105,131
bytes per frame**, which puts a 214-frame asset at roughly 22 MB. Even the most
optimistic real-content rate leaves the vendor's own assets an order of magnitude over.

`gif_maxframes="200"` in `layouts/rgb-keyboard.xml` is the vendor telling us it intends to
upload 200-frame animations. The format is built for it: a 16-bit per-frame content length
times 200 frames is the 13.2 MB of `VENDOR_MAX_GIF_BLOB_BYTES`. A 393,216-byte slot would
make almost the whole format unusable and the vendor's own assets unsendable.

### The reasoning error

"No capture exceeds 393,216 bytes" was presented as independent corroboration. It is not
evidence of anything. Every capture is 2-3 frames:

| Capture | Frames (TOC `[13]`) | Blob | Bytes/frame |
|---|---|---|---|
| `save_to_gif_1` | 3 | 315,392 | 105,131 |
| `save_to_gif_14/15` | 2 | 309,248 | 154,624 |
| `save_to_gif_13` | 2 | 157,696 | 78,848 |
| `save_to_gif_10/11` | 2 | 49,152 | 24,576 |
| `save_to_gif_2` | 3 | 22,528 | 7,509 |
| `save_to_gif_3/4` | 2 | 4,096 | 2,048 |

The vendor was **never once observed uploading a real animation** — every capture is a
hand-made two- or three-frame test. So the maximum across them describes the sample, not
the hardware. Reading it as a ceiling was reading a small sample as a bound, and it happened
to sit just under the stride by coincidence, which is what made the two look like agreement.

Extract the frame count from any capture with:

```python
import struct
# hdr = payload of the packet whose address == GIF_FLASH_BASE
off, total, w, h, tag, nframes = struct.unpack_from("<IIHHBB", hdr, 0)
```

### What the sixth entry probably is

Unresolved. The most likely readings, none tested:

- the GIF region is simply larger than one stride, and the table lists *starts* only;
- the table covers fixed-size single-image slots, with GIF last because it is the one
  variable-size region and takes everything above it;
- entries 1-3 (`0x04060000`, `0x040C0000`, `0x04120000`) are more single-image slots, which
  would make the table "five image slots plus the animation area".

## Cross-check against the captures

Parsed the maximum write address in every `save_to_gif_*.pcapng`, anchored on the `5A A5`
packet magic — `magic | BE16 len/256 | cmd | const | BE32 address` — and filtered to
`const == 0x64` with an address in the GIF slot. A raw byte search for `04 24 xx xx` does
*not* work here: it matches inside pixel payloads and inflates the result past 0x60000,
which is exactly the false positive that would have made this look disproved.

| Capture | writes | highest address | blob bytes (upper bound) |
|---|---|---|---|
| `save_to_gif_1` | 154 | `0x0428C800` | 315,392 |
| `save_to_gif_14` | 151 | `0x0428B000` | 309,248 |
| `save_to_gif_15` | 151 | `0x0428B000` | 309,248 |
| `save_to_gif_13` | 77 | `0x04266000` | 157,696 |
| `save_to_gif_10/11` | 24 | `0x0424B800` | 49,152 |
| `save_to_gif_9` | 19 | `0x04249000` | 38,912 |
| `save_to_gif_2` | 11 | `0x04245000` | 22,528 |
| `save_to_gif_3/4/5/6/7/8/12` | 2-4 | ≤ `0x04241800` | ≤ 8,192 |

(`save_to_gif_16/17/18` produced no matching headers — not investigated; they were captured
for a different question.)

No capture crosses `0x60000` — but see above for why that establishes nothing about the
hardware. It is recorded here as the per-capture extents, which are useful in themselves,
not as a bound.

## The flash chip: BOM options from the new schematic, and why NAND is the only one that fits

Resolves the "flash chip's own size" item from "Where to look next" below (kept in place,
struck through in spirit rather than deleted, since the reasoning that led here is worth
keeping). Prompted by new material added to `documentation/` after this file was mostly
written: the touchscreen's own schematic (`documentation/Schematics/SCH_LT168/`) and the
correct LT168 datasheets — the chip was previously misidentified as an LT7689; see the
correction in this same file's intro and in `re_notes/pic_scan_dll.md`.

**The schematic's own BOM is a footprint-compatible either/or**, printed on every
`SCH_LT168B_Demo_V1.x` page that shows the external flash, sitting on the QSPI0 bus:

| Type | Part numbers | Capacity |
|---|---|---|
| NOR | GD25Q128E / XT25F128B | 128Mbit = **16 MB** |
| NAND | GD5F1G / W25N01G | 1Gbit = **128 MB** |

The datasheet's own §4.2 address map (LT168's CPU/AHB bus map: registers at `0x4000_0000`,
QSPI0/1/2 flash *windows* at `0x6000_0000`/`0x7000_0000`/`0x8000_0000`) does not help decide
between them directly — none of this file's slot addresses (`0x0406_0000`...`0x0424_0000`)
fall inside any labeled region of it, confirming (again) that the wire protocol's address
field is a separate, vendor-invented logical address, not a raw LT168 bus address.

**The arithmetic decides it anyway.** `GIF_FLASH_BASE = 0x04240000` is ≈66.25 MB — already
bigger than the 16 MB NOR option's entire capacity, and bigger than every NOR part in the
ISP tool's own embedded JEDEC auto-detect table (found separately in `L99 ISP V1.23.exe`;
that table's NOR entries top out at 64 MB, its NAND entries run 128 MB-1 GB). If the
protocol's "address" field is a flat byte offset into the flash chip — the working
assumption this whole file already rests on, and the only one that makes the `0x60000`
stride coherent — then the 16 MB NOR option is **physically incapable** of being addressed
that high at all. Only the 128 MB NAND option (GD5F1G/W25N01G) can reach `0x04240000` with
room to spare. This isn't a coin flip between two BOM choices; one of them is ruled out by
an address this project already has real captures writing to.

**Independent structural evidence this is NAND, not NOR.** `protocol.py`'s own
`CHUNK_SIZE = 2048` matches the standard NAND page size (visible directly in the JEDEC
table's own entries, e.g. `W25N02GV: page=2048`), and `REGION_SIZE = 0x20000` (128 KiB) is
exactly 64 pages — a completely ordinary NAND erase-block size. `SLOT_STRIDE = 0x60000` is
exactly 3 erase blocks per slot. The "commit" packet sent after each filled 128 KiB region
reads naturally as a NAND block-program/mark-valid step, not an arbitrary chunking choice.
Nobody lands on these exact numbers by accident designing for NOR, where erase granularity
is usually 4-64KB sectors with no fixed page-size concept at all; this is what a
NAND-flash-native protocol looks like.

**The vendor's own assets corroborate needing a large chip.** The stock animations shipped
in `Windows/AULA L99/gif/` are 9-18 MB as *standard, LZW-compressed* `.gif` files —
`AULA L99/0.gif` (214 frames) is 15,423,564 bytes, `用户动画(1)/1.gif` (200 frames) is
18,315,694 bytes. These are the source files, not panel-format blobs, and standard GIF's
LZW compression is presumably tighter than the panel's own simple RLE/dither format — so
these are a floor, not an estimate, on the re-encoded size. Already well above the format's
own `VENDOR_MAX_GIF_BLOB_BYTES` stand-in (13.2 MB) before any re-encoding, and a 16 MB NOR
chip could not hold even one such asset alongside the five other fixed slots.

**The calculation**, given the 128 MB NAND option, and treating `0x04000000` as
approximately the chip's own byte 0 (reasonable since slot 1 sits just `0x60000` past it —
reading naturally as "first slot starts right after a small reserved/config region," not as
an arbitrary large offset with unaccounted space below it):

```
chip capacity           = 0x08000000  (128 MB, GD5F1G / W25N01G)
GIF_FLASH_BASE           = 0x04240000  (~66.25 MB)
remaining GIF capacity   = 0x08000000 - 0x04240000 = 0x03DC0000  (~61.75 MB)
```

**This is a real, hardware-backed estimate — but still an inference chain**, weaker than
the BKG/PHOTO_FRAME slot sizes above (confirmed twice over: base-subtraction *and*
firmware-table agreement). It rests on two assumptions: the schematic's NAND BOM option is
the one actually populated (plausible, but not read off a real unit's JEDEC ID), and
`0x04000000` is close to the chip's true byte 0 (plausible from the partition layout's
shape, not independently confirmed). Treat `0x03DC0000` as the best current estimate, not a
hardware-measured fact — the same distinction this file has drawn throughout.

## What this does and doesn't establish

Establishes: the panel's firmware holds a six-entry list of flash bases on a uniform
`0x60000` stride; the background and photo-frame slots are `0x60000` each, now confirmed
twice over (base subtraction and the table agreeing); the vendor's PC-side software
contains no flash map at all; and the flash chip is a 128 MB NAND part (GD5F1G/W25N01G),
per the schematic's BOM and the arithmetic above ruling out every NOR alternative.

Does not establish, with full certainty: the GIF slot's exact extent. It is bounded below
by roughly 22 MB if the vendor's own 214-frame asset is uploadable through this path at
real-content rates, and now has a reasoned upper estimate of `0x03DC0000` (~61.75 MB) from
the NAND capacity calculation above — an inference chain, not a direct measurement.
`SLOT_CAPACITY[GIF_FLASH_BASE]` in `protocol.py` now enforces this estimate in place of the
older `VENDOR_MAX_GIF_BLOB_BYTES` (13.2 MB) format-derived stand-in, which remains
documented for reference as a separate, distinctly-weaker figure.

No seventh table entry was found: `0x042A0000` occurs 74 times across the file and
`0x04300000` 299 times, both in the noise band for arbitrary 64KB-aligned values, and
neither appears adjacent to the table.

Also unidentified: slots 1-3 (`0x04060000`, `0x040C0000`, `0x04120000`).

## Where to look next

The flash-chip-size angle above is now resolved to a reasoned estimate; two ways to firm it
up further remain open:

- The **erase-sector loop** in the same firmware: whatever it erases before writing an
  animation is the slot, stated directly rather than inferred from a base list or a BOM
  capacity figure.
- A capture of the **vendor uploading one of its own stock GIFs**. There is still no such
  capture — every one in `wireshark_dumps/` is a 2-3 frame hand-made test — and it would
  settle both the real per-frame rate and the true maximum in one shot. This is the cheapest
  and most decisive of the two, and would also confirm or refute the `0x04000000`≈byte-0
  assumption the capacity estimate above rests on.

## Reproducing

```bash
cd "Windows/AULA L99/firmware"
python3 - <<'EOF'
d = open("L99 ISP V1.23.exe", "rb").read()
pat = b"".join(v.to_bytes(4, "little")
               for v in (0x04060000, 0x040C0000, 0x04120000, 0x04180000, 0x041E0000))
i = d.find(pat)
while i >= 0:
    g = d.find((0x04240000).to_bytes(4, "little"), i, i + 0x200)
    print(f"table @ {i:#x}, GIF base @ {g:#x} (+{g-i:#x})")
    i = d.find(pat, i + 1)
EOF
```
