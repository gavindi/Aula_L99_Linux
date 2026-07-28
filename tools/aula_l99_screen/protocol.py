"""Image format for the AULA L99's touchscreen (EEEF:268A).

This is a *different device* from the keyboard's vendor HID channel: the panel
is a CDC-ACM USB-serial device appearing as /dev/ttyACMn, so none of the
`04 xx` command framing in aula_l99_hacky applies here.

The format was derived from the vendor's own converter, `Image2Bin.exe`
(shipped in `qt-tool/` alongside the Windows app), by feeding it known images
and decoding what it wrote:

    bytes 00..03   uint32 LE   payload size in bytes (width * height * 2)
    bytes 04..05   uint16 LE   width
    bytes 06..07   uint16 LE   height
    byte  08       0x00        constant in every sample
    bytes 09..10   uint16 LE   CRC16/MODBUS over the pixel data
    bytes 11..     pixels      RGB565, little-endian, row-major

Verified rather than assumed:
  - Pixel encoding checked against a known test image: its first pixel came
    back as 0x05BF, exactly RGB565 for the cyan (0,180,255) line drawn at y=0,
    and its last as 0x0845 for the (10,10,40) background.
  - The dimension fields are real, not constants: a 200x100 input produced a
    40011-byte file with width=200, height=100.
  - The checksum is CRC16/MODBUS little-endian, matching four samples across
    two image sizes. CRC16/ARC, CCITT, XMODEM, Kermit and plain byte/word sums
    were all tested and none matched.

An earlier version of this module implemented a JPEG-based format taken from
third-party documentation of this panel. That format belongs to a different
device entirely (see the wire-protocol note below), which is why images sent
with it never appeared.

The payload above is what gets written to flash; see build_upload() for how it
is framed and chunked on the wire.
"""
from __future__ import annotations

import struct

HEADER_SIZE = 11
OFF_SIZE = 0
OFF_WIDTH = 4
OFF_HEIGHT = 6
OFF_CONSTANT = 8
OFF_CRC = 9

BYTES_PER_PIXEL = 2

# The panel is 320x480 (width x height).
PANEL_WIDTH = 320
PANEL_HEIGHT = 480

# Byte 8 was 0x00 in every sample from the vendor converter.
CONSTANT_BYTE = 0x00


def crc16_modbus(data: bytes) -> int:
    """CRC16/MODBUS: reflected poly 0x8005 (0xA001), init 0xFFFF, no final xor."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def rgb_to_rgb565(r: int, g: int, b: int) -> int:
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def encode_pixels(rgb_rows: bytes, width: int, height: int) -> bytes:
    """Pack raw RGB888 bytes (len == width*height*3) into little-endian RGB565."""
    expected = width * height * 3
    if len(rgb_rows) != expected:
        raise ValueError(f"expected {expected} bytes of RGB888, got {len(rgb_rows)}")

    out = bytearray(width * height * BYTES_PER_PIXEL)
    for i in range(width * height):
        r = rgb_rows[i * 3]
        g = rgb_rows[i * 3 + 1]
        b = rgb_rows[i * 3 + 2]
        struct.pack_into("<H", out, i * BYTES_PER_PIXEL, rgb_to_rgb565(r, g, b))
    return bytes(out)


def build_header(pixels: bytes, width: int, height: int) -> bytes:
    if width <= 0 or height <= 0:
        raise ValueError(f"bad dimensions: {width}x{height}")
    expected = width * height * BYTES_PER_PIXEL
    if len(pixels) != expected:
        raise ValueError(f"expected {expected} bytes of RGB565, got {len(pixels)}")

    header = bytearray(HEADER_SIZE)
    struct.pack_into("<I", header, OFF_SIZE, len(pixels))
    struct.pack_into("<H", header, OFF_WIDTH, width)
    struct.pack_into("<H", header, OFF_HEIGHT, height)
    header[OFF_CONSTANT] = CONSTANT_BYTE
    struct.pack_into("<H", header, OFF_CRC, crc16_modbus(pixels))
    return bytes(header)


def build_image_file(rgb_rows: bytes, width: int = PANEL_WIDTH,
                     height: int = PANEL_HEIGHT) -> bytes:
    """The complete .bin, byte-identical to what Image2Bin.exe produces."""
    pixels = encode_pixels(rgb_rows, width, height)
    return build_header(pixels, width, height) + pixels


# --- wire protocol -----------------------------------------------------------
# Decoded from the upstream project's USB captures. Note those captures are
# mis-attributed upstream: their `12 34 56 78` JPEG traffic goes to a different
# device (87ad:70db), while the AULA panel (eeef:268a) speaks this protocol on
# bulk endpoints 0x03 out / 0x82 in.
#
#     5a a5              magic
#     <len/256>          uint16 BE, payload bytes / 256 (8 for a 2048 chunk)
#     <cmd>              0x07 write chunk, 0x12 final partial, 0x0b commit
#     <const>            0x64 for data, 0x66 for commit
#     <address>          uint32 BE, flash address
#     <payload>
#     <crc>              uint16 LE, poly 0xA001 reflected, init per command
#
# The device acks every packet with ASCII "OK".
TRANSFER_MAGIC = bytes([0x5A, 0xA5])
CMD_WRITE = 0x07
CMD_FINAL = 0x12
CMD_COMMIT = 0x0B
CONST_DATA = 0x64
CONST_COMMIT = 0x66

# Each command uses its own CRC init. Verified against all 308 packets in both
# upstream captures; a single init does not fit all three.
CRC_INIT = {CMD_WRITE: 0xF104, CMD_COMMIT: 0xEEC4, CMD_FINAL: 0xD141}

# wireshark_dumps/save_to_gif_1.pcapng's final short data chunk uses cmd
# 0x71, not CMD_FINAL (0x12), for otherwise identical const/framing. Meaning
# unconfirmed (only one capture, no second sample to cross-check); not used
# by build_upload(), which only ever emits CMD_FINAL.

CHUNK_SIZE = 2048
REGION_SIZE = 0x20000          # 128 KiB; a commit follows each filled region

# The vendor app has three distinct upload destinations, per its own string
# table (Windows/AULA L99/language/1033.lan #866-868): "Save to GIF", "Save
# to BKG" and "Save to photo frame". The first two reuse this exact wire
# protocol and image format, differing only in flash base address.
PHOTO_FRAME_FLASH_BASE = 0x041E0000    # "Save to photo frame"
BACKGROUND_FLASH_BASE = 0x04180000     # "Save to BKG", confirmed from
                                        # wireshark_dumps/save_to_bkg_1/2.pcapng:
                                        # both captures' 154 write/commit
                                        # packets are reproduced byte-for-byte
                                        # by build_packet() at this address.

# "Save to GIF", confirmed from wireshark_dumps/save_to_gif_1.pcapng: its 157
# write/commit packets are also reproduced byte-for-byte by build_packet() at
# this address (resolving one of the two undocumented slots the vendor binary
# references -- 0x04200000 remains unidentified). Address only: there is no
# builder for this format. The bytes written there are NOT build_image_file()
# output -- see the GIF container notes below.
GIF_FLASH_BASE = 0x04240000

# GIF container format (from the single save_to_gif_1.pcapng capture --
# NOT cross-checked against a second sample, unlike the CRC inits above).
# The blob written to GIF_FLASH_BASE is a header of N * 20-byte entries (one
# per frame; N=3 in the capture, comfortably under the vendor's own
# gif_maxframes="200" and gif_headlength="256" in layouts/rgb-keyboard.xml),
# followed by the frames' payload data. Per-entry layout, little-endian:
#
#     [0:4]   uint32   this frame's absolute byte offset into the blob
#                       (confirmed against the actual write-chunk addresses)
#     [4:8]   uint32   total payload size after the header (same value
#                       repeated in every entry, not truly per-frame)
#     [8:10]  uint16   width (320 in the capture)
#     [10:12] uint16   height (480 in the capture)
#     [12]    u8       frame count (3)
#     [13]    u8       unidentified (also 3 -- coincidence or real field is
#                       unclear from one sample)
#     [14:16] u16      0x0000, unidentified/reserved
#     [16:18] u16      50 -- plausibly a delay, unit unconfirmed (likely
#                       centiseconds, matching GIF's own convention)
#     [18:20] u16      0xdb63, identical in every entry -- plausibly a
#                       checksum over the whole post-header payload
#                       (parallel to crc16_modbus() below) but unverified
#
# Each frame's own payload is NOT raw RGB565: at 101548-106996 bytes it's
# well under 320*480*2 = 307200, its byte histogram is heavily skewed toward
# small values (0x00 dominates, then 1-4, 28, 30), and it is neither zlib nor
# raw-deflate. Some custom compressed or delta-coded scheme -- not decoded.
# Cracking it needs targeted follow-up captures (e.g. a solid-color 1-frame
# GIF, then a 2-frame GIF differing by one pixel) that aren't available yet.

# Write and final chunks are acked with a 19-byte reply ending in ASCII "OK".
# Commits get a 21-byte reply instead, carrying a 4-byte checksum of the region
# just written -- so it is image-dependent and must not be compared literally.
ACK = b"OK"
REPLY_MIN = 19


def is_ack(cmd: int, reply: bytes) -> bool:
    """Did the panel accept this packet?"""
    if len(reply) < REPLY_MIN or reply[:2] != TRANSFER_MAGIC:
        return False
    if cmd == CMD_COMMIT:
        # the reply embeds a second message echoing the command byte
        return reply.find(TRANSFER_MAGIC, 2) != -1 and CMD_COMMIT in reply[7:10]
    return ACK in reply


def crc16_packet(cmd: int, body: bytes) -> int:
    """Packet checksum: reflected poly 0xA001 with a per-command init."""
    if cmd not in CRC_INIT:
        raise ValueError(f"unknown command 0x{cmd:02x}")
    crc = CRC_INIT[cmd]
    for byte in body:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_packet(cmd: int, const: int, address: int, payload: bytes) -> bytes:
    body = bytearray()
    body += TRANSFER_MAGIC
    body += struct.pack(">H", len(payload) // 256)
    body.append(cmd)
    body.append(const)
    body += struct.pack(">I", address)
    body += payload
    return bytes(body) + struct.pack("<H", crc16_packet(cmd, bytes(body)))


def build_upload(blob: bytes, base: int = PHOTO_FRAME_FLASH_BASE) -> list[bytes]:
    """The full packet sequence for one image, in the vendor's own order.

    Full 2048-byte chunks are written until a 128 KiB region is filled, then a
    commit for that region carrying the byte count written to it. Any remainder
    goes out as a final short packet before the last commit.
    """
    packets: list[bytes] = []
    offset = 0
    region_start = base
    region_bytes = 0

    while offset < len(blob):
        take = min(CHUNK_SIZE, len(blob) - offset)
        address = base + offset
        chunk = blob[offset:offset + take]
        if take == CHUNK_SIZE:
            packets.append(build_packet(CMD_WRITE, CONST_DATA, address, chunk))
        else:
            packets.append(build_packet(CMD_FINAL, CONST_DATA, address, chunk))
        offset += take
        region_bytes += take

        at_region_end = (base + offset) - region_start >= REGION_SIZE
        if at_region_end or offset >= len(blob):
            packets.append(build_packet(CMD_COMMIT, CONST_COMMIT, region_start,
                                        struct.pack(">I", region_bytes)))
            region_start = base + offset
            region_bytes = 0
    return packets


def describe(blob: bytes) -> str:
    """Decode a .bin header, for checking ours against the vendor's."""
    if len(blob) < HEADER_SIZE:
        raise ValueError(f"short file: {len(blob)} bytes")
    size = struct.unpack_from("<I", blob, OFF_SIZE)[0]
    width = struct.unpack_from("<H", blob, OFF_WIDTH)[0]
    height = struct.unpack_from("<H", blob, OFF_HEIGHT)[0]
    crc = struct.unpack_from("<H", blob, OFF_CRC)[0]
    actual = crc16_modbus(blob[HEADER_SIZE:])
    return (f"{width}x{height} payload={size} crc={crc:#06x} "
            f"({'ok' if actual == crc else f'MISMATCH, computed {actual:#06x}'})")
