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

## What's not confirmed: clean isolation of a single standalone image

- No per-product directory/index was found. Searched for adjacent chip-name labels near
  the found content (`LT168A`/`LT168B`/`LT7689`/`LT776`/`LT268A-D`) -- all eight names
  appear together, twice, as one combo-box-style list (at file offsets `0xcab2`-`0xcaea`
  and again at `0x40c324`-`0x40c35c`), not as individual per-blob labels. This rules out
  "the string right before offset X names which chip that blob is for" as a shortcut.
- The second occurrence of that same chip list (at `~0x40c000`) sits inside the *same*
  unbroken data span as the first (`0x364000`-`0x800000`+, no zero gap between them) --
  so it isn't obviously a different bundled product either; it may be a second, mostly
  duplicate copy of shared UI/string resources rather than a boundary marker. Not
  resolved.
- The two copies of the six-entry table (`0x398f42`, `0x3e57e2`, ~313KB apart) most
  likely correspond to the two firmware-version files the PC-side updater tries
  (`HFD_Code_V2.2.bin` / `HFD_Code_V2.3.bin`, per `screen_firmware_updater.md`), each
  with the table compiled in as a constant -- plausible, not proven.

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

`0x364000`-`0x412000` of `L99 ISP V1.23.exe` (712,704 bytes) was carved out and saved to
the session scratchpad (not committed to this repo, since its exact boundaries and full
contents aren't confirmed) for any follow-up work. Re-derive it with:

```python
d = open("Windows/AULA L99/firmware/L99 ISP V1.23.exe", "rb").read()
candidate = d[0x364000:0x412000]
```

Treat this as "a region confirmed to contain real, cleartext LT168 firmware content,"
not "the complete, isolated `MCU_Code.bin`/`UartTFT-II_Flash.bin` equivalents" -- the
outer edges likely include adjacent, unrelated bundled data given no clean end boundary
was found.

## Where to look next

- Map the full extent of the `0x364000`-`0x800000`+ span properly (continue the zero-run
  scan further, and look for the actual end of *this* project's content specifically --
  e.g. bisecting on where the six-entry table's constants stop being referenceable, or
  diffing the two ~313KB regions around each table copy against each other to find where
  they stop matching).
- Try treating the candidate extract as if it starts at a fixed load address (the same
  calibration approach `screen_firmware_updater.md` used for the Qt5 updater tool) and
  check whether any absolute-address-looking 32-bit words inside it point at plausible
  in-range offsets -- would help confirm real code vs. false positive.
- No public disassembler for LT168's actual ISA was found this round; identifying it
  properly (vendor CPU IP core name, e.g. by searching for any toolchain/compiler
  version strings elsewhere in this file) would be the highest-leverage next step for
  actually reading this candidate's code, not just its strings.
