# Screen/keyboard firmware updater disassembly notes

Working notes for a static-analysis thread investigating whether custom code
could be flashed to the touchscreen's LT7689 controller, prompted by the user
asking "is there enough in the firmware to figure out how to run our own code
on the touchscreen?" Purpose: this file exists so the next round doesn't have
to re-derive the address calibration or re-locate the flashing routine from
scratch. No protocol bytes have been extracted yet -- this documents where to
resume, not a finished result.

Two source files are in play, both at `Windows/` (top level, not under
`Windows/AULA L99/`):

- `L99 keyboard Screen reset firmware （Press and hold the FN key, then press
  X, 0, and 6 in sequence to enter screen upgrade mode.).exe` -- 194,946,048
  bytes, PE32 i386. Wrapped in **Enigma Protector** (confirmed via its own
  section table: `.enigma1`/`.enigma2`, ~194MB of packed/encrypted payload
  out of the total). Not unpacked. Almost certainly bundles the actual raw
  MCU firmware images (see filenames below) inside that packed payload.
- `L99 keyboard reset firmware （Double-click to open the keyboard firmware
  and update it）.exe` -- 2,213,280 bytes. Not yet examined; `strings`
  showed no overlap with the screen-specific filenames below, so this is
  very likely a *different* tool (probably the keyboard's own MCU updater,
  separate from the screen path this file is about).

`documentation/Firmware/` holds an **already-unpacked** dump of what appears
to be a small Qt5-based flashing GUI closely related to (possibly an earlier
build of) the first exe above -- raw PE section files (`.text`, `.rdata`,
`.data`, `.idata`, `.eh_fram`, `.bss`, `.CRT`, `.tls`, plus leftover
`.enigma1`/`.enigma2` stub sections from whatever process unpacked it), no
surrounding PE header. This is the actual analysis target; nobody has had to
fight Enigma Protector to get this far -- it was already done before this
session.

## What the tool is

MinGW-w64-built (`GCC: (i686-posix-dwarf-rev0...) 7.3.0`, confirmed via
`.rdata` strings), Qt5 GUI app (`Qt5Core.dll`/`Qt5Gui.dll`/`Qt5Widgets.dll`/
**`Qt5SerialPort.dll`**), i386/32-bit. Window class `MainWindow` with one
button `pushButton_doAll` and a `progressBar`.

Importantly, it does **not** call raw Win32 serial APIs (`CreateFileA`,
`SetCommState`, etc. are absent from `.idata`) -- all serial I/O goes through
`Qt5SerialPort.dll`'s public, well-documented `QSerialPort`/`QSerialPortInfo`
classes (`setBaudRate`/`setDataBits`/`setStopBits`/`setParity`/
`setFlowControl`, `QIODevice::write`/`readAll`). That means the low-level
transport mechanics don't need reverse engineering at all -- only this app's
own framing/protocol logic, built in its own `.text`, needs tracing.

Slot names recovered directly as plaintext strings in `.rdata` (Qt's MOC
embeds these for its string-based signal/slot connections, even in a
stripped release build): `on_pushButton_doAll_clicked`, `serial_receiveData`,
`getDevice`, `Close_SerialPort`, plus the Qt-builtin signals they connect to
(`readyRead()`, `timeout()`).

## Address calibration

No PE header is present in the dump (raw sections only), so the base address
and per-section VAs had to be inferred and then validated against real code,
not just assumed.

**Assumption**: standard MinGW-w64 PE32 defaults -- image base `0x400000`,
section alignment `0x1000`, first section (`.text`) at RVA `0x1000` (VA
`0x401000`), sections then laid out in the same order observed in the sibling
Enigma-wrapped exe's own (unprotected stub) PE header, read directly via `7z
l`: `.text .data .rdata .eh_fram .bss .idata .CRT .tls`.

```python
import math
def align(n, a=0x1000):
    return math.ceil(n/a)*a if n>0 else a
sizes = {'.text':49344,'.data':232,'.rdata':26736,'.eh_fram':7300,
         '.bss':0,'.idata':11800,'.CRT':52,'.tls':8}
order = ['.text','.data','.rdata','.eh_fram','.bss','.idata','.CRT','.tls']
addr = 0x401000
for name in order:
    print(f'{name:10s} VA=0x{addr:08x}')
    addr += align(sizes[name])
```

Result (current sizes as of this session -- re-run if the dump changes):

| Section | VA |
|---|---|
| `.text` | `0x401000` |
| `.data` | `0x40e000` |
| `.rdata` | `0x40f000` |
| `.eh_fram` | `0x416000` |
| `.bss` | `0x418000` |
| `.idata` | `0x419000` |
| `.CRT` | `0x41c000` |
| `.tls` | `0x41d000` |

**Validated**, not just assumed: disassembling `.text` at this base
(`objdump -D -b binary -m i386 -M intel --adjust-vma=0x401000 .text`) turns
up MinGW's own standard startup code checking the module's PE header in
place: `cmp WORD PTR ds:0x400000,0x5a4d` (the `"MZ"` DOS-header magic) and
`cmp DWORD PTR [edx+0x400000],0x4550` (`"PE\0\0"`) -- exactly what CRT
pseudo-relocation init looks like, and only correct if `0x400000` really is
the load base. Separately, 94 distinct absolute-address operands in `.text`
land inside the computed `0x40f000`-`0x415fff` `.rdata` range, and every
protocol-relevant string (see below) resolves to a real, correctly-landing
cross-reference -- multiple independent confirmations, not one coincidence.

## Tooling

```bash
FW=tools/../documentation/Firmware   # documentation/Firmware/ from repo root

# Disassemble .text at the calibrated base
objdump -D -b binary -m i386 -M intel --adjust-vma=0x401000 "$FW/.text" > text_disasm.txt

# Strings with byte offsets, to compute each string's VA (rdata_base=0x40f000 + offset)
strings -n 4 -t x "$FW/.rdata"

# Find where a given string's VA is referenced (loaded as an immediate) in the disassembly
grep -n "0x<va>" text_disasm.txt
```

## Findings: it's a two-phase sequential flash, CRC-checked only (no signing seen)

Cross-referencing every protocol-relevant string back to its `.text`
reference:

| String | VA | Referenced from (`.text` VA) |
|---|---|---|
| `Please open the port!` | `0x40f317` | `0x40702e`, `0x407c05`, `0x4082eb`, `0x408a12` |
| `Fail to Connect a mcu device` | `0x40f37a` | `0x406fce`, `0x406ffe` |
| `Mcu code, CRC = ` | `0x40f39c` | `0x40733d` |
| `/Flash.ini` | `0x40f3b4` | `0x407d7e` |
| `Fail to Connect a 268x device` | `0x40f3c7` | `0x40899d`, `0x408a3f` |
| `The file is over than the flash ic's size` | `0x40f3e8` | `0x408839` |
| `Please input flash code file` | `0x40f412` | `0x409388` |
| `Flash code, FileCRC = ` | `0x40f42f` | `0x408ca4`, `0x4090e5` |
| `  FlashCRC = ` | `0x40f446` | `0x409188` |
| `Update flash is OK!!!!!!` | `0x40f465` | `0x408e27` |
| `Update flash is fail.....` | `0x40f47e` | `0x408fd5` |
| `/HFD_Code_V2.3.bin` | `0x40f4b9` | `0x4096e3`, `0x409cf7` |
| `/HFD_Code_V2.2.bin` | `0x40f4cc` | `0x409a73`, `0x409b36` |
| `/UartTFT-II_Flash.bin` | `0x40f4df` | `0x4097aa`, `0x409bf7` |

This pins the entire update routine to one ~11.5KB span, `0x406fce`-
`0x409cf7` (almost certainly `on_pushButton_doAll_clicked` plus whatever
helpers it inlines/calls).

**Two distinct phases**, confirmed by two different device-connect error
strings used in clearly separate code blocks, not just repeated text:
- Phase 1 (~`0x406fce`-`0x408899`ish): `"Fail to Connect a mcu device"`,
  reads `HFD_Code_V2.2.bin`/`V2.3.bin` (tries both versions). "mcu" is
  presumably the keyboard's own controller or a bridge chip, not the display
  controller itself.
- Phase 2 (~`0x40899d` onward): `"Fail to Connect a 268x device"`, reads
  `/UartTFT-II_Flash.bin`. "268x" is almost certainly shorthand for the
  LT768x display-controller family the LT7689 belongs to (see
  `documentation/LT7689_DS_V13_ENG.pdf`) -- this is the phase that actually
  targets the touchscreen.

Every integrity check found so far is a **CRC** (`Mcu code, CRC =`, `Flash
code, FileCRC =`, `FlashCRC =`) -- no signature/RSA/AES-related string
anywhere in this binary's own logic (the "certificate signature" strings
found separately in the big Enigma-wrapped exe's raw `strings` dump are
generic Windows crypto-library text, not something this app's own code
path references -- not evidence of firmware signing). Consistent with a
corruption check only, not an authenticity/signing barrier.

## What's NOT done yet (pick up here)

- The ~11.5KB `0x406fce`-`0x409cf7` span has been *located*, not *read*.
  The actual wire framing (what bytes precede/follow the file's raw content
  when handed to `QIODevice::write`) hasn't been extracted -- that needs
  either (a) resolving the `QSerialPort`/`QIODevice`/`QFile`/`QDataStream`
  import addresses from `.idata` properly (a real PE import-directory parse,
  not just `strings`) so calls into them are identifiable in the
  disassembly, then reading the buffer-construction code before each
  `write()` call by hand, or (b) capturing real USB/serial traffic during an
  actual firmware update on real hardware and reading the wire format
  directly -- much faster and more reliable than (a), matching how the
  keyboard's and touchscreen's *existing* protocols in this repo were both
  originally reverse-engineered (from captures, not static disassembly).
- The big 194MB Enigma-wrapped exe hasn't been unpacked. It's the most
  likely place the actual raw `HFD_Code_V2.x.bin`/`UartTFT-II_Flash.bin`
  firmware images are bundled -- getting past Enigma Protector on it (or
  finding another already-unpacked source) is the path to the actual
  Cortex-M4 machine code, separate from and beyond this PC-side tool's own
  x86 logic.
- `Windows/AULA L99/firmware/` (present in the installed app tree) is an
  empty directory in this checkout -- worth checking whether a real install
  populates it with exactly these `.bin` files before assuming they only
  exist inside the big installer.
- The 2.2MB "keyboard reset firmware" exe is a separate, unexamined tool --
  no string overlap found with this one, so it's presumably a different
  protocol entirely (the keyboard's own MCU, not the screen).
