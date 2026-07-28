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

`0x04240000` is confirmed as the "Save to GIF" flash address, from
`wireshark_dumps/save_to_gif_1.pcapng` — but there is no `--target gif`,
because the payload format isn't understood well enough to safely construct
one. What's known:

- Same wire protocol/framing as the two targets above (same magic, write/
  commit/CRC-init machinery), except the final short data chunk uses `cmd
  0x71` instead of `0x12` — meaning unconfirmed.
- The blob is a small table-of-contents header (20 bytes per frame: byte
  offset, total payload size, `320x480` dimensions, frame count, a likely
  delay field, and a likely-but-unverified checksum) followed by the frames'
  data. See the comment block above `GIF_FLASH_BASE` in `protocol.py` for the
  full field-by-field breakdown.
- **Each frame's pixel data is not raw RGB565.** It's roughly a third smaller
  than a full `320x480` RGB565 frame, isn't zlib/deflate, and its byte
  distribution looks like a run-length or delta-coded scheme, not pixels.
  Undecoded.

Only one capture exists for this format, so — unlike the CRC inits below,
which were solved from two independent samples — there's no second data
point to cross-check a hypothesis against. Making progress here needs more
targeted captures: e.g. a single solid-color 1-frame GIF (to see the
degenerate case) and a 2-frame GIF differing by one pixel (to isolate how a
run or diff is expressed).

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
