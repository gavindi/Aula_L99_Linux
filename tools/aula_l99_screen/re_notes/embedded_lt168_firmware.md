# Embedded LT168 firmware inside `L99 ISP V1.23.exe`

Prompted directly by the user asking whether the LT7689->LT168B chip correction (see
`screen_firmware_updater.md`'s intro and `pic_scan_dll.md`) means firmware can now be
extracted from the device. Short answer worked out in that conversation: running custom
code is *harder* now (proprietary 32-bit RISC core, no public toolchain), and there's no
readback/dump command anywhere in the documented wire protocol -- but a third reading,
"recover the firmware images that get *written* to the panel," turned out to be
genuinely promising, and this file is the result of chasing it.

## Where: `Windows/AULA L99/firmware/L99 ISP V1.23.exe`

This 67,359,136-byte PE32 exe is the same file `flash_slot_table.md` already identified
as containing the panel's six-entry flash base-address table (`0x04060000` ...
`0x04240000`) -- twice, at file offsets `0x398f42` and `0x3e57e2`. **Correction to this
repo's own prior notes**: `screen_firmware_updater.md` previously said
`Windows/AULA L99/firmware/` was "an empty directory in this checkout" -- it is not; it
holds this file plus `L99 ENV1.03.exe` (2.2MB, a separate, still-unexamined tool).

## The file's own structure

`objdump -h` shows only ~10 small declared PE sections (`.text` through `.idata`/`.CRT`/
`.tls`), totalling roughly `0x19400` bytes, followed by `.enigma1`/`.enigma2` (confirming
this exe, like the 194MB "Screen reset firmware" one, is Enigma-Protector-wrapped) --
but `.enigma2`'s own *file offset* is `0x3ffa400` (~67MB), right near the very end of the
file. That leaves a **huge span, `0x19400`-`0x3ffa400` (~63MB), covered by no declared PE
section at all.**

A zero-byte scan of that span (`scan_runs` over 0x400-byte blocks) found:

```
0x340000 - 0x353400  data
0x353400 - 0x364000  ZERO   (~68KB of padding)
0x364000 - 0x800000  data   (continuous, no 2KB+ zero gap for at least 4.6MB)
```

So `0x364000` is a real, clean structural boundary (padding immediately before it), but
the data that follows does **not** end cleanly nearby -- it runs on on for megabytes with
no further padding gap, meaning this is not "one small isolated firmware blob with clean
boundaries on both sides." There is no discovered directory/index structure (searched for
per-product name markers -- see below) that would delimit exactly where one bundled
product's data ends and another's begins.

## What's confirmed: genuine, cleartext LT168 firmware content

Starting at file offset `0x36f0c0`, in the clear (no encryption, plain ASCII), sits a
string table containing:

```
COMP0_Rising_Edge
COMP0_Falling_Edge
COMP0_Test
Update Flash
Flash Model:
File size exceeds Flash capacity
Checking CRC
Result: / Failed
1: UartTFT-II_Flash.bin
0:/UartTFT_Flash/UartTFT-II_Flash.bin
0:/UartTFT_Flash_No_CRC/UartTFT-II_Flash.bin
OK / 100% / None. / NG: CRC error / NG: BBM error / Fail
Remove the SD card to enter the main program
```

**`COMP0_Rising_Edge`/`COMP0_Falling_Edge`/`COMP0_Test` are debug strings naming the
exact `COMP0` (Analog Comparator 0) peripheral from the LT168 register map**
(`documentation/LT168_BRFDS_V21_Eng.pdf` Table 4-1, base `0x400A_0000`) -- this is not
installer boilerplate, it's a string table baked into actual LT168-target firmware. The
surrounding text (`Update Flash`, `Flash Model:`, the JEDEC chip-name list, SD-card
upgrade messages) matches this repo's own AP-note-derived understanding of the LT168's
ISP/bootloader firmware (`LT_VCOM_GUI`/`LT_Uart_GUI`/SD-card upgrade flow, section 1.4 of
`LT_UartTFT_AP Note_V10_ENG.pdf`) almost exactly. Immediately following the string table
(from file offset ~`0x36f680`) is dense binary data consistent with compiled machine
code (mid-to-high entropy, not the near-8.0 bits/byte of compressed/encrypted data).

Because this region also contains the *exact* six-entry base-address table this project
already confirmed empirically from real wire captures (`0x04060000`...`0x04240000`,
`re_notes/flash_slot_table.md`), this isn't generic unrelated sample firmware for some
other Levetop customer -- it's a build sharing the identical partition layout real AULA
L99 hardware uses.

## Refined: two firmware images identified, each carved out

Confirms the "plausible, not proven" guess below (kept for its reasoning) with real
evidence. Searched for every occurrence of the string-table's most distinctive strings
across the whole file:

| String | Occurrences | Offsets |
|---|---|---|
| `COMP0_Rising_Edge` | 2 | `0x36f0be`, `0x3b9b46` |
| `Update Flash` | 4 (2 pairs) | `0x36f166`/`0x36f17a`, `0x3b9c36`/`0x3b9c4a` |
| `Heap and stack collision` | 2 | `0x36f4c6`, `0x3b9de2` |

Two occurrences each, roughly `0x4aa88`-`0x4aad0` (~305KB) apart -- **this is two
separate firmware images, not one**, each with its own copy of the string table and (per
`flash_slot_table.md`) its own copy of the six-entry base-address table. Almost certainly
the two version files the PC-side updater tries in sequence (`HFD_Code_V2.2.bin` and
`HFD_Code_V2.3.bin`, per `screen_firmware_updater.md`'s phase-1 finding). The two string
tables are *not* byte-identical: the second copy (at `0x3b9b46`) additionally has
`DMA Configuration Error` and `i:%d    %x` strings the first doesn't, consistent with it
being the newer of the two versions.

Using each string-table location and its own copy of the six-entry table as anchors
(each table's exact local offset inside the carved bytes was independently verified),
carved three pieces to the session scratchpad:

| File | Byte range | Size | Contains |
|---|---|---|---|
| `candidate_isp_fw_image_A_0x364000-0x3b9000.bin` | `0x364000`-`0x3b9000` | 348,160 | Table copy 1 (`0x398f42`, local `0x34f42`); string table at local `0xb0be` |
| `candidate_isp_fw_image_B_0x3b9000-0x400000.bin` | `0x3b9000`-`0x400000` | 290,816 | Table copy 2 (`0x3e57e2`, local `0x2c7e2`); string table at local `0xb46` |
| `candidate_unidentified_tail_0x400000-0x40c000.bin` | `0x400000`-`0x40c000` | 49,152 | Neither table nor string table found -- unidentified, FF-byte-heavy (up to 11%), kept separate rather than folded into image B |

**Confidence**: high that these are two real, distinct LT168 firmware builds (the
duplicated-with-variation string table plus per-image table copy is strong, converging
evidence). Lower confidence on the *exact* byte boundaries -- no clean all-zero or other
unambiguous separator was found between image A and image B (a fine-grained scan of
`0x3a0000`-`0x3ba000` for zero runs found only small, scattered gaps of 64-875 bytes, not
one clear boundary), so the split point (`0x3b9000`) was chosen close to where image B's
own string table begins minus a lead-in comparable to image A's (`0xb0be` bytes of
code/data before its own string table) -- reasonable, not certain. The boundaries could
be off by some small amount in either direction.

## What's still not confirmed

- No per-product directory/index was found. Searched for adjacent chip-name labels near
  the found content (`LT168A`/`LT168B`/`LT7689`/`LT776`/`LT268A-D`) -- all eight names
  appear together, twice, as one combo-box-style list (at file offsets `0xcab2`-`0xcaea`
  and again at `0x40c324`-`0x40c35c`), not as individual per-blob labels. This rules out
  "the string right before offset X names which chip that blob is for" as a shortcut.
- `L99 ISP V1.23.exe`'s own small legitimate `.text` section (`0x401000`-`0x40d0b0`) was
  disassembled and searched for immediate operands matching plausible file offsets into
  this region -- none found. The loader logic that actually reads this overlay data isn't
  in this tool's own compiled code, at least not as literal offset constants; it's most
  likely handled opaquely by Enigma Protector's own runtime (its "Virtual Box" embedded
  virtual-filesystem feature is a plausible match for the `0:/UartTFT_Flash/...`-style FAT
  drive-letter path strings found earlier), which this session had no tooling to unpack.
- No FAT/MBR boot signature, and no ZIP/RAR/7z/GZIP/CAB magic bytes, were found anywhere
  near this region (checked `0x300000`-`0x420000` specifically) -- whatever container
  format holds these two images, if any, isn't a standard one recognizable by signature.
  Moderate (not near-8.0-bits/byte) entropy throughout suggests the images themselves are
  stored uncompressed, consistent with treating the carved ranges directly as candidate
  firmware bytes rather than needing further decompression.
- The `0x400000`-`0x40c000` tail chunk remains unidentified -- notable for higher `0xFF`
  byte density (up to 11%, vs. under 1% in images A/B) but that alone doesn't confirm it's
  a `UartTFT-II_Flash.bin`-equivalent asset image; no positive evidence ties it to that
  specifically.

## Attempted: identifying the actual instruction set

The LT168 datasheet describes "a 32-bits load/store reduced instruction set computer
(RISC) architecture with fixed 16-bits instruction" (`documentation/LT168_BRFDS_V21_Eng.pdf`
S1.3.1) -- a uniformly-fixed 16-bit-wide encoding, notably *unlike* RISC-V (which mixes
16-bit compressed and 32-bit standard instructions) or classic ARM/MIPS (32-bit fixed).
Tried anyway, cheaply: disassembling a code-like chunk (offset `0x36f680` onward) with
`capstone`'s RV32GC decoder failed almost immediately (2 instructions decoded before an
illegal opcode, out of a 1024-byte test window) -- consistent with this not being RISC-V,
not strong proof on its own. No public disassembler for whatever the real ISA is was
found or attempted further this round.

## Candidate extract

Three files, carved from `L99 ISP V1.23.exe` and saved to the session scratchpad (not
committed to this repo -- the two firmware images' boundaries are a reasoned estimate, not
a confirmed cut, and the tail chunk is unidentified). Re-derive with:

```python
d = open("Windows/AULA L99/firmware/L99 ISP V1.23.exe", "rb").read()
image_a = d[0x364000:0x3b9000]   # candidate HFD_Code_V2.2-equivalent
image_b = d[0x3b9000:0x400000]   # candidate HFD_Code_V2.3-equivalent
tail    = d[0x400000:0x40c000]   # unidentified
```

Treat images A and B as "high confidence this is real, distinct LT168 firmware content,
each containing this project's own flash partition table" but "medium confidence on the
exact byte boundaries" (see the reasoning above) -- not a certified byte-exact
`HFD_Code_V2.2.bin`/`HFD_Code_V2.3.bin`.

## Where to look next

- Firm up the image A/B boundary: diff the two images against each other (accounting for
  the size difference) to see how much of their non-string-table content also matches,
  which would narrow down exactly where each one's real content starts and ends versus
  where the carve boundary was merely a reasonable guess.
- Identify the `0x400000`-`0x40c000` tail chunk's purpose (or rule it out as unrelated).
- No public disassembler for LT168's actual ISA was found this round; identifying it
  properly (vendor CPU IP core name, e.g. by searching for any toolchain/compiler
  version strings elsewhere in this file) would be the highest-leverage next step for
  actually reading this candidate's code, not just its strings.
