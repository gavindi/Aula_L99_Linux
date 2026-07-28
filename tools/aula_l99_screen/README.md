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
from four captures: `wireshark_dumps/save_to_gif_1.pcapng` (a real photo
GIF), `save_to_gif_2.pcapng` (3 solid red/green/blue frames),
`save_to_gif_3.pcapng` (2 frames, both solid red except one white pixel at
`(0,0)` — top-left — in frame 2), and `save_to_gif_4.pcapng` (the same pair,
but the white pixel moved to `(319,479)` — bottom-right, the last pixel in
raster order). The last three were captured specifically to make further
progress, which they did. There is still no `--target gif`, because the
pixel payload format isn't understood well enough to safely construct one.
What's known:

- Same wire protocol/framing as the two targets above. The final short data
  chunk's `cmd` byte, previously a mystery, is solved: `cmd = CMD_WRITE +
  (payload_len % 256)`, not a fixed opcode — confirmed against all four GIF
  captures' final chunks (`0x71`, `0x35`, `0xB1` twice) plus the three
  previously-known values. There's no known general formula for the matching
  CRC init, though, so this doesn't unlock arbitrary upload sizes — see
  `final_chunk_cmd()` in `protocol.py`.
- The blob is a small table-of-contents header (20 bytes per frame: byte
  offset, total payload size, `320x480` dimensions, a format tag, frame
  count, a likely delay field). Its per-entry checksum field is **solved**:
  it's `crc16_modbus()` — the same function already used for the
  single-image header — confirmed byte-exact in three of the four captures.
  `save_to_gif_3` also resolved an ambiguity from the first two: byte 12 is a
  constant format/version tag (always 3), byte 13 is the real frame count
  (3, 3, 2, 2) — the first two captures happened to share the same value in
  both bytes.
- Each frame also has its own ~24-byte sub-header, including the
  self-referential frame byte length (confirmed exact in all 10 frames
  across all four captures) and a pair of RGB565-looking color fields.
  `save_to_gif_3` vs. `4` pinned these down: one field holds the color of the
  frame's first pixel in raster order, the other holds the "other" color
  present, if any (`0x0000` for a single flat color). Consistent within both
  captures, but doesn't explain `save_to_gif_2`'s solid frames, whose single
  color sits in the "other" slot instead — unexplained.
- **The strongest new lead**: every frame in captures 2–4 has exactly
  **528 bytes of zero** right after its sub-header, regardless of color —
  consistent with a fixed table (Huffman/quantization-style, as in JPEG)
  that doesn't depend on content, followed by a variable-length
  entropy-coded section.
- **The most informative single result**: moving the one differing pixel
  from `(0,0)` (`save_to_gif_3`) to `(319,479)` (`save_to_gif_4`) shrinks the
  byte-level diff from **605 bytes** (nearly the entire frame) down to just
  **5**, clustered at the very end — while the total frame length stays
  identical either way. Position doesn't change how much data is needed,
  only how much of the frame is affected by an early vs. late divergence.
  That reads as a running prediction context that a "differs from
  expectation" event permanently perturbs from that point onward — an early
  divergence corrupts everything downstream, a late one corrupts almost
  nothing — support for the transform/DCT-style coding hypothesis, but the
  actual bitstream algorithm is still not decoded. Full detail in the
  comment block above `GIF_FLASH_BASE` in `protocol.py`.

Making further progress from here is a harder problem than the last few
rounds: the "where" question (which this round answered cleanly) doesn't by
itself reveal "how" a token is constructed. Likely needs either more
captures targeting specific hypotheses (e.g. isolating whether 528 bytes is
truly fixed independent of image size) or literally decoding the entropy
coding by hand from the byte patterns already in hand.

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
