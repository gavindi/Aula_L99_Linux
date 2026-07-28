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
from five captures: `wireshark_dumps/save_to_gif_1.pcapng` (a real photo
GIF), `save_to_gif_2.pcapng` (3 solid red/green/blue frames),
`save_to_gif_3.pcapng` (2 frames, both solid red except one white pixel at
`(0,0)` — top-left), `save_to_gif_4.pcapng` (the same pair, white pixel moved
to `(319,479)` — bottom-right), and `save_to_gif_5.pcapng` (the same red
frame 1, but frame 2 is a clean 50/50 vertical split — left half red, right
half blue). There is still no `--target gif`, because the pixel payload
format isn't understood well enough to safely construct one, though this
round made the first real crack in it. What's known:

- Same wire protocol/framing as the other two targets. The final short data
  chunk's `cmd` byte, previously a mystery, is solved: `cmd = CMD_WRITE +
  (payload_len % 256)`, not a fixed opcode — confirmed against 5 distinct
  GIF final-chunk lengths (`0x71`, `0x35`, `0xB1` twice, `0x7F`) plus the
  three previously-known values. There's no known general formula for the
  matching CRC init, though, so this doesn't unlock arbitrary upload sizes —
  see `final_chunk_cmd()` in `protocol.py`.
- The blob is a small table-of-contents header (20 bytes per frame). Its
  per-entry checksum field is **solved**: `crc16_modbus()`, the same function
  already used for the single-image header, confirmed byte-exact in four of
  the five captures. `save_to_gif_3` resolved an earlier ambiguity: byte 12
  is a constant format/version tag, byte 13 is the real frame count.
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

Together this points toward rows in this encoding being hardcoded to
exactly two fixed-size sub-tokens, not a flexible run-list a flag
terminates: the one successful experiment changed lengths while keeping
exactly 2 tokens; every failed one either changed a flag without changing
token count, or changed token count outright — and all fail identically.
That reframes the flag bytes as possibly not carrying chosen information at
all: maybe a fixed per-slot marker (always 0 for the first run, 1 for the
second) that the decoder checks strictly, with color implied purely by slot
position rather than by the flag's value. That would also explain why
solid-color frames look completely different at the byte level (`FF 00`
repeated ~600 times with no row structure at all) — possibly a separate,
non-row-bounded "single continuous run" encoding for flat images, not the
same per-row grammar. Unconfirmed, and still doesn't reconcile with
`save_to_gif_3`/`4`'s persistent flip within what should, by this theory,
be many independent solid rows.

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
