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
import time

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


def _build_crc16_table() -> tuple[int, ...]:
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        table.append(crc)
    return tuple(table)


_CRC16_TABLE = _build_crc16_table()


def crc16_modbus(data: bytes) -> int:
    """CRC16/MODBUS: reflected poly 0x8005 (0xA001), init 0xFFFF, no final xor.
    Table-driven (see _build_crc16_table) -- same math as the classic
    bit-by-bit formulation, just faster.
    """
    crc = 0xFFFF
    for byte in data:
        crc = (crc >> 8) ^ _CRC16_TABLE[(crc ^ byte) & 0xFF]
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
CMD_FINAL = 0x12       # = final_chunk_cmd(11); the value for an 11-byte final
                        # chunk specifically, not a general "final" opcode --
                        # see final_chunk_cmd() below.
CMD_COMMIT = 0x0B      # = final_chunk_cmd(4); commit payloads are always the
                        # 4-byte region byte count, so this is always what
                        # the formula gives -- not an independent opcode.
CONST_DATA = 0x64
CONST_COMMIT = 0x66


def final_chunk_cmd(payload_len: int) -> int:
    """cmd byte for a non-full write chunk, as a function of its payload length.

    Not a fixed opcode: cmd = CMD_WRITE + (payload_len % 256), wrapping at a
    byte. Confirmed against 14 independent samples across 12 capture files:
    2048-byte chunks (len%256=0 -> cmd=0x07=CMD_WRITE), commits (always a
    4-byte payload -> cmd=0x0B=CMD_COMMIT), the photo-frame/background final
    chunk (11 bytes -> cmd=0x12=CMD_FINAL), and wireshark_dumps/
    save_to_gif_1/2/3/5/6/7/8/9/10/12/13.pcapng final chunks (1386 bytes ->
    0x71, 1582 bytes -> 0x35, 1450 bytes -> 0xB1, 120 bytes -> 0x7F, 540
    bytes -> 0x23, 122 bytes -> 0x81, 2040 bytes -> 0xFF, 1492 bytes -> 0xDB,
    312 bytes -> 0x3F, 1080 bytes -> 0x3F, 248 bytes -> 0xFF -- every one
    predicted exactly by this formula before being checked; save_to_gif_4
    .pcapng repeats save_to_gif_3's 1450-byte/0xB1 case rather than adding a
    new one).

    IMPORTANT: cmd = (CMD_WRITE + payload_len) % 256 is many-to-one -- many
    different lengths share a cmd byte (e.g. 312 and 1080 both give 0x3F;
    248 and 2040 both give 0xFF, confirmed by save_to_gif_10 vs. 12 and
    save_to_gif_8 vs. 13 respectively). CRC_INIT is keyed by the actual
    payload length, NOT by this cmd byte, for exactly this reason -- see
    CRC_INIT below.
    """
    return (CMD_WRITE + payload_len) % 256


# Each length uses its own CRC init. Originally modeled as being keyed by
# the cmd byte (a natural first guess, since cmd IS a function of length),
# but save_to_gif_12/13.pcapng proved that wrong: their final chunks (1080
# and 248 bytes) collide with save_to_gif_10's (312 bytes) and
# save_to_gif_8's (2040 bytes) on cmd (0x3F and 0xFF respectively, since
# cmd only depends on length % 256) but need DIFFERENT inits. So this is
# keyed by the real payload length; crc16_packet() derives that from the
# body it's given rather than trusting the caller's cmd. Verified against
# all 308 packets in both upstream photo-frame captures, plus every GIF
# capture's write/commit/final chunks -- not a general formula, since no
# relationship between length and init was found (see final_chunk_cmd()).
CRC_INIT = {
    2048: 0xF104,   # CMD_WRITE, full chunks -- every photo-frame/bkg/GIF capture
    4: 0xEEC4,      # CMD_COMMIT, always a 4-byte region-count payload
    11: 0xD141,     # CMD_FINAL, the photo-frame/background final chunk
    1386: 0x1CB0,   # save_to_gif_1.pcapng final chunk
    1582: 0xD9F1,   # save_to_gif_2.pcapng final chunk
    1450: 0x9F4E,   # save_to_gif_3/4.pcapng final chunk
    120: 0x6F7A,    # save_to_gif_5.pcapng final chunk
    540: 0xA9BB,    # save_to_gif_6.pcapng final chunk
    122: 0x13B0,    # save_to_gif_7.pcapng final chunk
    2040: 0xD9D1,   # save_to_gif_8.pcapng final chunk
    1492: 0x1E90,   # save_to_gif_9.pcapng final chunk
    312: 0x922E,    # save_to_gif_10/11.pcapng final chunk
    1080: 0x9E2E,   # save_to_gif_12.pcapng final chunk -- same cmd (0x3F) as 312, different init
    248: 0x522F,    # save_to_gif_13.pcapng final chunk -- same cmd (0xFF) as 2040, different init
}

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

# "Save to GIF", confirmed from six independent captures --
# wireshark_dumps/save_to_gif_1/2/3/4/5/6.pcapng: every capture's write/commit
# packets are reproduced byte-for-byte by build_packet() at this address
# (resolving one of the two undocumented slots the vendor binary references
# -- 0x04200000 remains unidentified). Address only: there is no builder for
# this format. The bytes written there are NOT build_image_file() output --
# see the GIF container notes below.
GIF_FLASH_BASE = 0x04240000

# GIF container format, from six captures: save_to_gif_1.pcapng (a real
# multi-frame photo GIF), save_to_gif_2.pcapng (a 3-frame solid
# red/green/blue test GIF), save_to_gif_3.pcapng (a 2-frame test GIF, both
# frames solid red except one white pixel at (0,0) -- top-left corner -- in
# frame 2), and save_to_gif_4.pcapng (identical to save_to_gif_3.pcapng
# except the white pixel is at (319,479) -- bottom-right corner -- instead)
# -- the last three captured specifically to make further progress here,
# which they did. The blob written to GIF_FLASH_BASE is a header of N *
# 20-byte entries
# (one per frame; N=3, 3 and 2 respectively across the three captures,
# comfortably under the vendor's own gif_maxframes="200" and
# gif_headlength="256" in layouts/rgb-keyboard.xml), followed by the frames'
# payload data. Per-entry layout, little-endian:
#
#     [0:4]   uint32   this frame's absolute byte offset into the blob
#                       (confirmed against the actual write-chunk addresses,
#                       in all three captures)
#     [4:8]   uint32   total payload size after the header (same value
#                       repeated in every entry, not truly per-frame;
#                       confirmed in all three captures)
#     [8:10]  uint16   width (320 in all three captures)
#     [10:12] uint16   height (480 in all three captures)
#     [12]    u8       SOLVED: a constant format/version tag, not frame
#                       count -- it's 3 in all three captures even though
#                       save_to_gif_3.pcapng only has 2 frames, which is what
#                       separated it from [13] below
#     [13]    u8       SOLVED: actual frame count -- 3, 3 and 2, matching
#                       each capture exactly (save_to_gif_3.pcapng is what
#                       distinguished this from [12], which stayed 3)
#     [14:16] u16      0x0000, unidentified/reserved
#     [16:18] u16      SOLVED: the inter-frame delay. 50 in every capture
#                       taken so far (all 15), which looked like it could
#                       just be the vendor UI's shared default -- confirmed
#                       otherwise: the user explicitly set the frame speed
#                       to 50 in the Windows app when generating
#                       save_to_gif_13.pcapng, and the wire value is
#                       literally 50, so this is a real, user-controlled
#                       field, not a coincidental constant. Unit still
#                       unconfirmed (likely centiseconds, matching GIF's
#                       own convention, i.e. 50 = 0.5s) -- no capture with
#                       a different speed setting exists yet to nail down
#                       the scale factor.
#     [18:20] u16      SOLVED: crc16_modbus() -- the same CRC16/MODBUS
#                       function already used for the single-image header
#                       above -- computed over the payload following this
#                       header. Verified byte-exact in save_to_gif_2.pcapng
#                       and save_to_gif_3.pcapng. Identical in every entry
#                       within one capture (it's a whole-payload field, not
#                       truly per-frame) but differs between captures, as
#                       expected for a real checksum.
#
# Each frame has its own ~24-byte sub-header (offsets relative to the frame's
# own start, i.e. blob[frame_offset:]), decoded by diffing frames that are
# otherwise identical -- save_to_gif_2's three solid-color frames (identical
# for ~8800 bytes except one small window), and save_to_gif_3's two
# single-pixel-different frames (identical except ~605 bytes, almost all
# following one clean pattern -- see below):
#
#     [8:12]  uint32   this frame's own byte length, self-referential --
#                       confirmed exact for all 8 frames across all three
#                       captures
#     [12:14] u16      the byte length of a variable-length section at the
#                       end of the frame (see "fixed prefix" below):
#                       size32 - this field is exactly 528 for all 5 frames
#                       across save_to_gif_2/3 (the "simple" captures);
#                       doesn't hold for save_to_gif_1's real-photo frames,
#                       which also differ at [14:16] below -- so this looks
#                       mode-dependent, not a universal constant
#     [14:16] u16      0x0100 in save_to_gif_2/3, 0x0101 in save_to_gif_1 --
#                       plausibly a mode/complexity flag distinguishing
#                       "flat" test content from a real photo's, unconfirmed
#     [16:18] u16      the color of this frame's first pixel in raster
#                       order, RGB565. Confirmed by save_to_gif_3 vs. 4: the
#                       differing pixel is white and everything else is red;
#                       when the diff is at (0,0) (save_to_gif_3, frame 2)
#                       this field is white (0xFFFF); when the diff is at
#                       (319,479) instead (save_to_gif_4, frame 2) this field
#                       is red (0xF800), i.e. it tracks whichever color pixel
#                       (0,0) actually is in each case.
#     [18:20] u16      SOLVED (see save_to_gif_8 below): palette slot 1,
#                       RGB565. Not just "the other color" -- this is slot 1
#                       of an extensible palette that continues at [20:22]
#                       (slot 2), [22:24] (slot 3), etc., one slot per
#                       distinct color the frame's runs reference. 0x0000
#                       when the frame only uses slot 0 (a single flat
#                       color). Still doesn't explain save_to_gif_2's three
#                       frames, whose sole color sits at [18:20] with
#                       [16:18]=0 -- the reverse of what a "slot 0 is always
#                       populated first" rule predicts. Unexplained.
#
# The "fixed prefix" hypothesis: every frame in save_to_gif_2/3/4 has exactly
# 528 bytes of zero immediately after its sub-header, byte-identical
# regardless of the frame's color -- consistent with a fixed table (Huffman
# or quantization-style, as in JPEG) that doesn't depend on image content,
# followed by a variable-length entropy-coded section (the [12:14] bytes
# above) that does. Not confirmed, but the exact-528 match across 7
# differently-colored frames from 3 separate captures is a strong signal.
#
# The single-pixel diff in save_to_gif_3 (frame 2 has one white pixel at
# (0,0), everything else red) shows up as a precise, repeatable pattern:
# frame 1 and frame 2 diverge at byte 528 (the byte right after the fixed
# prefix: 0xFF in frame 1, 0x00 in frame 2), and from there on every
# following occurrence of a recurring "0xFF 0x00" 2-byte token in frame 1
# becomes "0xFF 0x01" in frame 2 -- the second byte flips once, at the very
# first token, and never flips back for the rest of the frame (605 bytes
# differ in total, essentially the whole frame from byte 528 to the end).
# That the change starts in the very first token (immediately after the
# fixed prefix) matches (0,0) being the first pixel in raster-scan order.
#
# save_to_gif_4 moves the same one-pixel diff to the opposite extreme --
# (319,479), the LAST pixel in raster order -- and this is the single most
# informative result of the four captures: only **5 bytes** differ between
# that frame and its all-red counterpart (vs. 605 for the (0,0) case), all
# of them clustered at the very end of the frame (plus the two size-field
# bytes at [8] and [12], expected since the frame is 2 bytes longer). Total
# frame length is unaffected by where the diff pixel is (1728/1730 bytes in
# both captures) -- only the LOCAL EXTENT of the diff changes, from "nearly
# the whole frame" to "nearly nothing," depending on how early the differing
# pixel occurs in raster order. This is strong, position-controlled evidence
# for a running state or context that a "differs from prediction" event
# permanently perturbs from that point onward: an early divergence corrupts
# everything downstream of it (hence the huge save_to_gif_3 diff), a late
# one corrupts almost nothing (hence save_to_gif_4's tiny one) -- consistent
# with the transform/DCT-style coding hypothesis (a DC predictor context
# that never resets mid-frame), but the actual bitstream algorithm is still
# not decoded. The terminal encoding also isn't a simple continuation of the
# same 0x00->0x01 token flip: save_to_gif_4's tail changes from repeating
# "...FF 00 FF 00" to "...FE 00 00 01", a distinct pattern rather than one
# more flipped token, suggesting special handling at the very end of a frame.
#
# save_to_gif_5.pcapng is the first real crack in the entropy-coded content
# itself. It reuses save_to_gif_3/4's solid-red frame 1 as a reference and
# replaces frame 2 with a clean 50/50 vertical split (left half red, right
# half blue -- 76800 of 153600 pixels different, vs. one single pixel in the
# earlier captures), specifically to test whether the 528-byte fixed prefix
# actually is fixed, independent of how much of the frame differs.
#
#   - 528 CONFIRMED FIXED even at 50% of the frame different: frame 2's
#     content section is still exactly (its own size32) - 528 bytes, same as
#     every earlier sample, now checked against something far more complex
#     than a single pixel.
#   - Frame 2's content section is exactly 1920 bytes = 480 rows * 4 bytes,
#     and is a single 4-byte unit (b'\x9f\x00\x9f\x01') repeated all 480
#     times, byte-for-byte identical every repeat (every row has the
#     identical red/blue split, so this is consistent with the content being
#     genuinely periodic per row rather than evidence of a literal per-row
#     reset).
#   - 0x9F = 159 = 160 - 1, exactly the length of each color half (160
#     pixels) minus one. Strong evidence that (at least) the first byte of
#     each 2-byte sub-unit is a run length, stored as length-1.
#   - The second byte of each sub-unit is 0x00 for the red (first-pixel-
#     color) half and 0x01 for the blue ("other" color) half -- consistent
#     with indexing into the two-slot color palette described above (color
#     0 = [16:18]'s color, color 1 = [18:20]'s). But this does NOT obviously
#     reconcile with save_to_gif_3/4's behavior: there, the equivalent byte
#     flips from 0x00 to 0x01 ONCE, at the point of divergence, and then
#     stays 0x01 for hundreds of subsequent bytes spanning many rows, rather
#     than alternating back to 0x00 for each new row the way a true
#     per-run color index would. Whether that's a different code path for a
#     single-pixel run vs. a half-frame run, or the byte means something
#     else entirely that happens to look like a color index here, is not
#     resolved.
#   - The reference frame's own content section, now cross-checked precisely:
#     1200 bytes = 600 repeats of b'\xff\x00' for 320x480 = 153600 solid-red
#     pixels (previously only the repeating pattern was known, not the exact
#     count) -- 600 tokens for 153600 pixels doesn't factor into a clean
#     per-token pixel count either (153600 / 600 = 256, but the visible
#     length byte is 0xFF = 255, not 256 -- off by one from the naive
#     reading, same "length-1" convention as the 0x9F finding above would
#     actually predict: 255+1=256 pixels per full token, 600*256=153600
#     exactly).
#
# Live hardware experiments (no capture file -- the panel was plugged into
# this Linux box directly, via aula_l99_screen.device.SerialTransport):
#
#   1. save_to_gif_5.pcapng's reconstructed blob was sent to GIF_FLASH_BASE
#      with build_upload(), all 4 packets acked, and the panel correctly
#      displayed the half-red/half-blue split. This is the first time any of
#      our own code -- not just a passively observed Windows capture -- wrote
#      to this address and had the *result* (not just the wire bytes)
#      confirmed correct: real proof the TOC/sub-header/checksum
#      understanding above is complete and correct, not just self-consistent
#      with captures.
#   2. One byte was then flipped in that known-good blob: the second byte of
#      row-token 240 of 480 in frame 2's content, b'\x9f\x00\x9f\x01' ->
#      b'\x9f\x00\x9f\x00' (the byte read above as the blue-half's color
#      index/second-run flag). TOC crc16_modbus recomputed and updated to
#      match; re-uploaded the same way -- all 4 packets acked again, so
#      nothing about the wire transfer itself failed.
#   3. The panel did NOT show a localized change (e.g. row 240's right half
#      turning red). It played a completely different, smaller GIF, centered
#      on screen.
#   4. Same edit position, but flipping row-token 479 of 480 instead -- the
#      very LAST row, whose changed byte is literally the last byte of the
#      whole upload. If the effect were "wrong byte count consumed, runs off
#      the end of our own data and into whatever flash holds next," this
#      position should have had nowhere left to run off to. Same result as
#      step 3 anyway: the identical different, smaller, centered GIF.
#   5. A third edit, same row 240 position as step 2 but the OPPOSITE flag
#      (the FIRST sub-token's byte, 0x00 -> 0x01 -- claiming that run stops
#      immediately rather than claiming a nonexistent one continues). If the
#      byte's role were "how many more bytes to consume," this direction
#      should *shorten* the read for that row rather than lengthen it, and
#      should stay safely inside our own 4216-byte upload. Same result
#      again: the identical different, smaller, centered GIF, confirmed to
#      be the *exact same* animation each of the three times, not three
#      different glitches.
#   Every one of these was reversible: re-uploading the original unmodified
#   blob immediately restored the correct half-red/half-blue image each
#   time, confirming the panel itself was never damaged by any of this.
#
# Three single-byte mutations, two different byte positions, two opposite
# edit directions, and all three produced the exact same result -- not
# three different-looking failures. That's a poor fit for "wrong byte count
# consumed, decoder desyncs and reads whatever raw bytes happen to be next
# in flash" (step 5 in particular shouldn't have anywhere to run off to, and
# a raw overread landing on different offsets each time would more plausibly
# look different per attempt, not identical). It fits much better with: the
# panel validates the uploaded content in some way (a checksum over the
# decoded data, a consistency check on the run structure, or similar) that
# is not the TOC-level crc16_modbus (that one was recomputed correctly each
# time and the transfer still acked normally), and on failure falls back to
# a fixed, previously-cached animation rather than rendering the bad data or
# erroring visibly.
#
# A fourth experiment, changing a length instead of a flag, broke that
# pattern -- and rendered real, position-correct new content. Row-token 240's
# two length bytes were changed from (159, 159) -- a 160/160 pixel split --
# to (99, 219) -- a 100/220 split, i.e. still summing to 320 (the panel
# width), same flags (0x00, 0x01) untouched, same crc16_modbus recompute and
# re-upload as every other experiment. This time the panel did NOT fall
# back: it rendered the normal half-red/half-blue image with the red/blue
# boundary visibly notched inward at exactly row 240 of 480 (confirmed:
# photographed at almost exactly the panel's vertical midpoint, matching the
# edited row precisely) -- a one-row-tall protrusion of blue into red
# territory, consistent with a 100px-red/220px-blue split for that single
# row and unchanged 160/160 everywhere else. This is the first controlled,
# predicted, position-correct change to rendered content in the whole
# investigation, and confirms the run-length-stored-as-length-minus-one
# reading directly rather than by inference from byte patterns.
#
# Combined with the three failed flag mutations, the emerging picture is
# that the panel's content validation cares about the length bytes summing
# correctly per row (100 + 220 = 320, same as 160 + 160, so this edit passed)
# rather than rejecting any deviation whatsoever -- narrower and more
# specific than 0.5.7's "any change fails" reading. What exactly the flag
# bytes need to satisfy remains open, since every flag-only edit tried so
# far has failed regardless of position or direction.
#
# (Operationally: one restore attempt after this experiment silently didn't
# take -- the panel kept showing the previous fallback GIF despite a clean
# ack'd re-upload of the known-good blob -- and a second identical re-upload
# fixed it. Possibly a read/write race if the panel was still mid-loop
# reading the flash region it was simultaneously being written to. Not
# investigated further; worth retrying a write before concluding a change
# had no effect.)
#
# A fifth experiment tried to discriminate two readings of the flag byte
# that a 2-run row can't distinguish (a per-run color index and a
# continue/last framing bit happen to look identical when there are only
# ever 2 runs, indices 0 and 1). Row 240 was rewritten as THREE runs --
# 100px red, 100px blue, 120px red, still summing to 320 -- with
# continuation-style flags (0, 0, 1). This grows the row from 4 to 6 bytes,
# so the frame's self-referential size32/content-length fields, both TOC
# entries' total-size field, and the crc16_modbus checksum were all
# recomputed to match, and the wire transfer was padded with zero bytes to
# the next multiple of 2048 so every chunk stayed a plain 2048-byte cmd=0x07
# write (avoiding the need for an unverified CRC_INIT entry for a new final-
# chunk length). Result: the fallback animation, same as every flag
# mutation. A control upload of the ORIGINAL, unmodified blob with the same
# kind of trailing zero-padding (nothing else changed) rendered correctly,
# ruling out the padding itself as the cause.
#
# A sixth experiment resolved this cleanly: row 240's two flag bytes were
# SWAPPED rather than set to a new value -- (0x9F,0x00)(0x9F,0x01) ->
# (0x9F,0x01)(0x9F,0x00), same lengths, same 160/160 split, just the two
# flags exchanged. This rendered correctly -- not the fallback -- with the
# boundary at exactly the same position as always, but the COLORS for that
# one row visibly swapped (confirmed by photo: a thin horizontal line at
# row 240 where left-of-boundary reads as the "other" color and
# right-of-boundary reads as the frame's first-pixel color, i.e. inverted
# relative to every row above and below it). This directly confirms the
# flag byte IS a per-run color index after all (selecting between the two
# RGB565 slots in the sub-header, [16:18] and [18:20]) -- contradicting the
# "fixed positional marker" reading above.
#
# Four data points on this row now: (0,1) [original] renders normally;
# (1,0) [swapped, this experiment] renders correctly with that row's colors
# inverted; (0,0) and (1,1) [0.5.7's two same-value mutations] both fail to
# the fallback animation. The pattern isn't "must equal a specific value in
# a specific position" -- it's that a row's two runs must use two DIFFERENT
# color indices, one 0 and one 1, in EITHER order; using the same index
# twice fails. That also reframes the three-run failure above: with only
# two possible flag values (0 and 1), a three-run row can never have each
# run use a different index from the other two -- some pair is forced to
# repeat, which this same rule would reject regardless of whether rows are
# otherwise capable of holding 3+ runs. So the earlier "rows are hardcoded
# to exactly two tokens" reading may not be the real constraint either; "a
# row's runs must cover each of the frame's colors exactly once" fits all
# six data points at once, including the failed three-run attempt, without
# needing a separate hardcoded-token-count rule. Consistent with a real
# encoder simply never emitting two consecutive same-colored runs in one
# row (it would merge them, or use the continuous-run encoding solid frames
# use instead) -- so the decoder may never have been built to tolerate it.
#
# A seventh experiment confirmed the palette reading comprehensively: with
# NO row data touched at all, the sub-header's two RGB565 color fields
# ([16:18], [18:20]) were changed from red/blue (0xF800/0x001F) to
# green/yellow (0x07E0/0xFFE0). The whole frame rendered in the new colors
# -- not just row 240, every one of the 480 rows correctly resolved the new
# palette -- confirming the color-index mechanism is a real, uniformly
# applied per-frame palette, not something specific to one row or
# hardcoded elsewhere. (Incidentally this also made obvious that the
# 2-frame animation had been alternating with frame 1, unmodified solid
# red, all along -- easy to miss when frame 1's red and frame 2's red-left
# half looked similar, obvious once frame 2 turned green/yellow.)
#
# An eighth experiment (frame 1's content byte-for-byte replaced with frame
# 2's proven split, TOC updated to match) and a ninth (a hand-built 3-frame
# blob: solid red, split, split again via an exact copy) both produced the
# fallback animation, and were initially read as evidence for frame index
# selecting the decode routine, and/or a sequential delta encoding between
# frames -- see CHANGELOG 0.5.12/0.5.13 for that reasoning in full. Both
# experiments padded the wire transfer with trailing zero bytes to reach a
# round multiple of 2048, specifically to avoid needing an unsolved
# CRC_INIT entry for a new final-chunk length.
#
# save_to_gif_6.pcapng (a real, vendor-generated 3-frame capture: solid
# red, split, split again UNCHANGED -- built to directly test what a real
# "no visible change between frames" looks like) refutes that reading. Its
# frame 1 and frame 2 are BYTE-FOR-BYTE IDENTICAL -- confirmed directly --
# meaning the real encoder simply re-emits a frame's full content verbatim
# when nothing changes; there is no delta or no-op token to find. Its own
# frame 1 is also byte-identical to save_to_gif_5's frame 1 (the same
# split, independently captured), confirming the encoder is deterministic
# and content-driven, not context- or position-dependent. And the
# reconstructed blob from the NINTH experiment above -- built by hand,
# before this capture existed -- turned out to be byte-for-byte identical
# to what save_to_gif_6.pcapng actually contains, proven by direct
# comparison. The only difference was packetization: the real capture ends
# in a genuine 540-byte final chunk (cmd 0x23, solved above), while the
# experiment padded to avoid needing that unsolved value. The user
# confirmed save_to_gif_6's capture renders correctly on the panel.
#
# CONFIRMED directly: re-sent as a proper, unpadded upload (3 full 2048-byte
# writes + the real 540-byte final chunk at cmd 0x23 + commit -- literally
# the same 5 packets as save_to_gif_6.pcapng, byte-for-byte) the exact same
# content that failed padded in experiment 9 rendered correctly: the full
# 3-frame animation played as expected. Same bytes, only the packetization
# differed, and that alone was the difference between the fallback and a
# correct render. Padding -- not frame index, not a delta requirement -- was
# the cause of experiment 9's failure (and by the same logic, likely
# experiment 8's too, which used the identical technique).
#
# This makes padding's status genuinely inconsistent rather than simply
# "unsafe": the seventh experiment's padding-only control (padding the
# working 2-frame blob with no other change) rendered correctly, while this
# padded 3-frame content did not, despite both using the same "round up to
# the next multiple of 2048" technique. Padding is not reliably safe to use
# for further experiments -- prefer real captures or exact, unpadded
# packetization (solving the needed CRC_INIT entry from a genuine capture)
# over padding when a test's total length doesn't land on an
# already-verified final-chunk length.
#
# This also removes the basis for reframing save_to_gif_3/4's persistent
# flip as a delta-mode switch (0.5.12); that observation still stands, but
# its explanation is open again. 0.5.9's 3-stripe row-count experiment used
# the same padding technique and should be distrusted pending a re-test
# without it -- not yet done, since it would need a new CRC_INIT entry
# (for a 122-byte final chunk) that no capture has provided.
#
# === RESOLVED: the "row-grammar" is a continuous, row-boundary-crossing
# === run-length encoding. save_to_gif_7.pcapng supplied exactly that
# === 122-byte-final-chunk capture (a red/blue/red vertical triple stripe,
# === 100/120/100 px, same proportions as the earlier failed hand-built
# === attempt) and, decoded in full, replaces every "row token" theory
# === above with a complete, simple model that fits all prior evidence:
#
#   - The frame's pixel content is walked in raster order (row-major, left
#     to right, top to bottom) as ONE continuous sequence -- NOT reset or
#     re-paired at row boundaries. Confirmed exactly: this stripe frame's
#     content decodes as 961 (length, flag) tokens whose lengths sum to
#     exactly 153600 (320*480), and whose runs are NOT "2 (or 3) per row" --
#     a run's trailing pixels on one row merge with the next row's leading
#     pixels whenever they're the same color, since raster order visits them
#     back-to-back with nothing in between. Token sequence: (100,flag0),
#     then (120,flag1),(200,flag0) repeated 479 times, then a final
#     (100,flag0) -- exactly what merging predicts: 100 (row 0's leading
#     red) + 120 (its blue middle) + [100 (row 0's trailing red) fused with
#     100 (row 1's leading red) = 200] + 120 (row 1's blue) + 200 (fused
#     row1/row2 red) + ... + a final unfused 100 (row 479's trailing red,
#     nothing after it to merge with).
#   - Each token is (length-1, flag), as established earlier (0.5.5, 0.5.8).
#     A run longer than 256 px (the 1-byte length field's max) is split into
#     multiple consecutive tokens that all share the SAME flag -- confirmed
#     against save_to_gif_3/4/5's clean solid-red frame: exactly 600 tokens,
#     ALL (255, flag=0), sum 600*256=153600. These are chained pieces of one
#     giant run, not 600 independent runs.
#   - flag is a color index into the sub-header's palette, as established in
#     0.5.10/0.5.11. It only changes when the actual pixel color changes to
#     a genuinely new run; chained continuation pieces of the same run keep
#     the same flag (hence "all (255,0)" for a solid frame, not alternating).
#
# This also finally reconciles save_to_gif_3/4's persistent, never-resetting
# flip (0.5.3/0.5.4, unexplained again as of 0.5.14/0.5.15): a solid-red
# image with one white pixel decodes as one tiny run (the white pixel,
# flag0) followed by one enormous red run (nearly the whole image, flag1),
# chained into ~600 consecutive same-flag pieces just like the fully-solid
# case -- the flag "staying flipped" for hundreds of tokens is just many
# chained pieces of that single giant run, not a special persistent mode.
#
# save_to_gif_8.pcapng (4 distinct-colored vertical stripes -- red, green,
# blue, yellow, 80px each) answers two more open questions from the list
# above in one capture:
#
#   - The palette is NOT fixed at 2 colors: this frame's sub-header carries
#     FOUR populated RGB565 slots -- [16:18]=0xF800 red, [18:20]=0x07E0
#     green, [20:22]=0x001F blue, [22:24]=0xFFE0 yellow -- exactly the four
#     stripe colors, in stripe order. flag is a genuine multi-value palette
#     index (confirmed values 0-3 here, not just 0/1), and [20:22] is slot 2
#     of that palette, not a mysterious "variant" of the [18:20] color as
#     read in 0.5.5 -- that reading only looked plausible because every
#     capture before this one used at most 2 colors.
#   - The 528-byte prefix is STILL exactly 528 bytes with 4 colors in play,
#     ruling out "a per-color palette/quantization table that scales with
#     color count" as its purpose -- whatever it is, its size does not
#     depend on how many distinct colors the frame uses.
#   - The frame's content (1920 tokens, 4-way uniform: exactly 480 each of
#     (80,flag0)/(80,flag1)/(80,flag2)/(80,flag3), summing to 153600 pixels)
#     is the clean "no merge" case of the same continuous-RLE model: row
#     boundaries here always land on a color change (yellow -> red), so nothing
#     merges across them, unlike save_to_gif_7's red/blue/red case where the
#     boundary color repeated. Both are the same grammar; this just isn't the
#     boundary-merging scenario.
#
# save_to_gif_9.pcapng (a black background with a white 1px grid every 32px,
# frame 2 the same grid shifted 1px left and 1px down) is a stress test at
# far higher density than anything before it -- 9315 tokens per frame,
# mostly tiny (1px and 31px) runs from the grid lines and cells -- and holds
# up completely: total pixels sum to exactly 153600 in both frames, and the
# 528-byte prefix is STILL exactly 528 bytes even here. The two frames'
# token streams are structurally identical (same 9315-token shape, same
# length histogram) but start from opposite flag/color assignments, because
# each frame independently derives flag 0 from whatever color its own first
# pixel happens to be -- (0,0) is white in frame 1 (on both a horizontal and
# vertical line) and black in frame 2 (the shift moves both lines off that
# pixel) -- one more confirmation that frames are encoded fully independently
# (0.5.14/0.6.0), not as deltas against each other. 11th cmd/CRC_INIT data
# point along the way (1492-byte final chunk, cmd 0xDB, solved as usual).
#
# save_to_gif_10.pcapng (8 distinct-colored vertical stripes: red, green,
# blue, yellow, magenta, cyan, white, gray -- one more color than
# save_to_gif_8) finds the palette's actual limit, and something unexpected
# past it:
#
#   - Only 7 of the 8 colors get their own exact palette slot ([16:18]
#     through [28:30]: red, green, blue, yellow, magenta, cyan, white --
#     all byte-exact RGB565). Gray does NOT appear anywhere in the
#     sub-header.
#   - Instead, the content for gray's stripe is NOT a single (40,flag)
#     token like the other seven -- it's 40 alternating 1-pixel tokens,
#     (1,flag7)(1,flag8) repeated 20 times each, referencing TWO NEW
#     palette slots at [30:32]=0x640C and [32:34]=0x9C13. Decoded to RGB:
#     (96,128,96) and (152,128,152) -- their average is (124,128,124),
#     matching the actual target gray, (128,128,128), almost exactly.
#   - CONFIRMED VISUALLY, not just from the bytes: the user reported the
#     gray stripe looked textured/dithered on the real panel, not a smooth
#     solid gray. The encoder dithers colors it can't represent directly by
#     alternating two nearby palette colors pixel-by-pixel rather than
#     giving every distinct source color its own slot -- so the palette
#     doesn't have a hard "8 colors and no more" cutoff so much as a
#     deeper constraint on which individual colors qualify for their own
#     slot (7 primaries/white were fine; a mid-tone gray wasn't).
#   - The 528-byte prefix is still exactly 528 bytes with 9 total palette
#     slots in use (7 real + 2 dither-pair) -- still no observed case where
#     palette size affects it.
#   - 12th cmd/CRC_INIT data point along the way (312-byte final chunk,
#     cmd 0x3F, solved as usual).
#
# save_to_gif_11.pcapng is a control for save_to_gif_10: same 8 colors,
# reordered so gray is FIRST (was last) and white is last (was first). This
# directly tests whether dithering is about the specific color or just "ran
# out of slots" (order-dependent capacity limit). Result is decisive: gray
# STILL dithers, now using slots 0-1 instead of 7-8, with the EXACT SAME
# pair -- [16:18]=0x640C, [18:20]=0x9C13, byte-identical to save_to_gif_10
# -- while all 7 other colors (including white, now in the position gray
# held before) get clean direct slots at [20:22] through [32:34], and the
# content's dither-token run correspondingly shows up at the START of the
# frame instead of the end. This rules out "7-slot capacity limit, first
# come first served" conclusively: it was never about position or order,
# and the encoder maps this specific gray to this specific dither pair
# deterministically, independent of what else is in the frame.
#
# save_to_gif_12.pcapng tests the "which colors dither" boundary directly:
# black (0,0,0, the missing 8th RGB-cube corner), orange (255,128,0, NOT a
# corner -- G is mid-value), and red (reference), 3 stripes. Result: NEITHER
# black NOR orange dithers -- both get clean, exact palette slots ([16:18]
# =0x0000 black, [18:20]=0xFC00 orange, [20:22]=0xF800 red). This refutes
# the "8 RGB-cube corners only" theory from directly after 0.6.3/0.6.4: a
# clearly non-corner color (orange) is represented exactly, no dithering.
#
# save_to_gif_13.pcapng follows up with light gray (200,200,200, a
# different achromatic mid-tone than the original gray) and dark red
# (128,0,0, chromatic, one mid-value channel like orange but not paired
# with a maxed-out channel). Confirmed correct on the panel. Result: BOTH
# dither -- refuting "achromatic-only" too. Testing every color used so far
# against its own maximum channel value gives a clean, so-far-exceptionless
# rule: a color gets a direct palette slot only if max(R,G,B) is exactly 0
# (black) or 255 (any hue at full intensity in at least one channel); any
# color whose brightest channel lands strictly between 0 and 255 --
# regardless of how many other channels are already at an extreme --
# dithers. 12 for 12 tested colors fit this rule, including the two
# "should dither" and one "shouldn't" predictions made before checking.
# Consistent with the palette fundamentally representing "hue at full
# brightness, or black" and dithering to approximate anything else.
#
# save_to_gif_13.pcapng's exact byte-level structure is NOT fully decoded,
# unlike every earlier capture: its sub-header's 16-bit content-length field
# overflows (true content is >150 KB, several times any previous capture,
# since dithering two colors at once inflates the entropy-coded section a
# lot), and with two colors dithering simultaneously the palette shows
# additional entries beyond simple 2-color pairs -- combinations of the
# component brightness levels from both dithered targets, not yet mapped to
# a specific encoding rule. The qualitative finding (dark red and light gray
# both dither) is solid; the precise token layout for multi-color dithering
# isn't.
#
# Offline re-analysis of save_to_gif_13's raw blob (reassembled from the
# capture, no hardware involved) refines the palette structure, though not
# the token grammar. Frame 2's sub-header carries 11 populated RGB565
# slots, not simple 2-color pairs per dithered target:
#
#   - slot 4 (0xF800, pure red) is the frame's third, UNDITHERED stripe --
#     the same reference red used elsewhere -- confirming this frame is 3
#     stripes (red, light gray, dark red), not 2.
#   - slots 2-3 (0x6000/(153,0,0)-ish and 0x9800) decode to (99,0,0) and
#     (156,0,0), average (127.5,0,0) -- essentially exact for the (128,0,0)
#     dark-red target. This is the SAME simple 2-slot dither pattern as
#     save_to_gif_10/11/12's gray.
#   - slots {0,1,5,6,7,8,9,10} -- the other 8 -- are NOT simple pairs. They
#     are the EXHAUSTIVE set of all 2x2x2=8 combinations of three
#     independently-quantized channels: R in {156,206}, G in {170,215}, B
#     in {156,206} (verified: every one of the 8 slots' decoded RGB is one
#     of these 8 combinations, and all 8 combinations are present with none
#     missing or repeated). This is a materially different dithering scheme
#     from every prior single-dithered-color capture: instead of one shared
#     pair of whole colors alternating pixel-by-pixel, light gray here gets
#     its OWN per-channel independent quantization (R, G, and B each
#     dithered between their own two levels separately), needing all 8
#     corners of that 3D grid as distinct palette entries rather than 2.
#     The unweighted average of all 8 is (181, 192.5, 181), noticeably off
#     from the (200,200,200) target -- consistent with the actual pixel
#     stream using the 8 slots at UNEQUAL frequencies (a duty-cycle/ordered
#     dither per channel) rather than each of the 8 combinations equally
#     often, though the token stream itself is not yet decoded to confirm
#     this directly (see below).
#   - This refines, rather than confirms, the earlier "combinations of the
#     component brightness levels from BOTH dithered targets" guess: the
#     two dithered colors in this frame do NOT share or combine slots with
#     each other. Dark red keeps the old simple 2-slot scheme unchanged;
#     light gray gets an entirely separate, new 8-slot scheme. Which
#     scheme a given color uses (2-slot pair vs. 8-slot per-channel grid)
#     is not yet understood -- both save_to_gif_10/11's gray (128,128,128)
#     and this frame's dark red (128,0,0) use the simple 2-slot form, so it
#     isn't simply "achromatic vs. chromatic" or "how far from a valid
#     corner" -- unexplained why light gray (200,200,200) needed the richer
#     scheme when a coarser 2-slot pair, in principle, could approximate it
#     too (e.g. the same kind of pair used for the original 128-gray).
#
#   - RESOLVED: the token grammar wasn't wrong, the whole RLE MODEL was.
#     Frame 2's content region is exactly 153600 bytes -- not incidentally
#     close to 320x480, but EXACTLY equal to it -- and every single byte in
#     that region is confined to 0-10 (the 11-entry palette range, verified
#     across all 153600 bytes with zero exceptions). This is a raw,
#     uncompressed, ONE-BYTE-PER-PIXEL palette-indexed bitmap in plain
#     raster order, not a stream of (length, flag) RLE tokens at all. The
#     earlier "flat 2-byte-token" decode attempts failed because they were
#     applying the wrong model, not because of an off-by-one or a missing
#     second pass -- once read as 1 byte = 1 pixel, the frame decodes
#     perfectly with no leftover bytes and no overshoot.
#   - Confirmed spatially: every row (checked at row 0, 100, 240, 479, and
#     others) has the identical 3-stripe boundary, columns [0:106) light
#     gray, [106:212) dark red, [212:320) red -- 106/106/108 px, matching
#     the 3-stripe test image. The red stripe is uniformly flag 4 (no
#     dithering, as expected). The dark-red stripe is a perfect
#     1-pixel-alternating (2,3)(2,3)... pattern -- the same simple 2-slot
#     dither already established for single-color cases, just now
#     confirmed to literally be "alternate every pixel," not merely
#     "alternate at some coarser granularity."
#   - The light-gray stripe's dominant pattern is (flag0,flag0,flag0,flag1)
#     repeating every 4 pixels -- a 3:1 duty-cycle ordered dither. flag0
#     (0xceb9 = 206,215,206) and flag1 (0xcd59 = 206,170,206) share the
#     same R and B (206,206); only G differs (215 vs. 170). So this
#     dominant 4-pixel tile dithers ONLY the G channel (weighted average
#     ~204, vs. the 200 target), while R and B sit fixed at 206 (vs. 200)
#     -- both reasonably close given only two discrete options 156/206 to
#     choose from. Most rows (475 of 480) also substitute one of the other
#     6 combo flags (5,6,7,8,9,10) in place of flag1 at scattered positions
#     -- e.g. row 3 uses flag5/flag6 alternately at the tile's 4th position
#     instead of flag1 -- adding a second, slower-varying axis to the
#     dither (likely a real 2D ordered/Bayer matrix, not just a 1D
#     per-row repeat.) The exact row-to-row substitution rule isn't mapped
#     yet, but the core mechanism (a per-pixel raw bitmap, not RLE) is.
#   - This also explains WHY the 8-slot scheme exists at all where the
#     simpler 2-slot pair (used for gray in gif_10/11 and dark red here)
#     doesn't: a per-channel independent ordered dither needs many more
#     achievable output colors than a single alternating pair, and doing
#     that through RLE tokens would be pathological (nearly every run
#     would be 1 pixel, doubling the byte cost vs. just storing the index
#     directly) -- so past some complexity threshold the encoder appears to
#     switch from RLE to a flat indexed bitmap instead. Frame 1 (the solid
#     red reference, content_len 1200, still RLE) has mode_flag=0x0100;
#     this raw-bitmap frame has mode_flag=0x0002 -- a plausible format
#     selector (RLE vs. raw), though with only one example of each this
#     isn't proven, just consistent.
#   - First hardware test of this reading (the panel is connected): a
#     40x40 block of an existing valid flag (4, clean red) was written into
#     save_to_gif_13's light-gray stripe, TOC crc16_modbus recomputed
#     correctly, all 79 packets acked -- and the panel showed the fallback
#     animation, not the edited content. This does NOT retract the
#     byte-layout reading above (re-checked the full 528-byte prefix for
#     both frames byte-by-byte: genuinely all zero past the known header
#     fields, no hidden checksum hiding there or trailing the frame that
#     this edit could have invalidated). It matches the same "ack'd and
#     TOC-checksum-correct but still falls back" opacity documented in the
#     0.5.x RLE mutation experiments -- whatever the panel's real content
#     validator checks, it rejected this edit for reasons still unknown,
#     same unresolved mystery as before, now also confirmed present in the
#     raw-bitmap format. Restored the original blob immediately after;
#     confirmed correct by the user.
#   - A second experiment swapped two whole 40x40 blocks between the gray
#     and red stripes -- same size, so a pure permutation that leaves every
#     flag's total pixel count across the frame exactly unchanged, unlike
#     the overwrite above. Still fell back, ruling out "preserves the
#     frame's aggregate flag histogram" as the validator's actual
#     criterion.
#   - A THIRD experiment, the smallest possible edit -- swapping just two
#     adjacent bytes (row 0, columns 2 and 3, values 0 and 1) -- worked:
#     all 79 packets acked, and the panel rendered the normal animation
#     WITH the intended single-pixel change visible, confirmed by the
#     user. This is the first genuine hardware proof of the raw-bitmap
#     byte-layout reading, not just the best fit for static evidence:
#     editing one byte at a known position produced exactly the predicted
#     one-pixel visual change. Combined with the failed block-swap (which
#     is the SAME kind of edit -- a histogram-preserving permutation --
#     just 800x larger), the pass/fail split points at a scale- or
#     magnitude-based validation (how much of the frame differs from some
#     reference) rather than a property of the difference's statistics.
#     The exact threshold is unmapped. Restoring the original blob after
#     this round needed two retries before the panel actually redrew --
#     matches the flaky-restore behavior from the 0.5.x era, just needing
#     one more retry than that case did; every upload itself acked cleanly
#     throughout, so the flakiness is on the panel's redraw-trigger side,
#     not the wire transfer.
#   - RETRACTED the "scale/magnitude threshold" hypothesis above by
#     bisecting it directly. Cross-stripe block swaps (same gray<->red
#     type as the 40x40 one) at 8x8 (128 total differing positions), 4x4
#     (32), 2x2 (8), and 1x1 (2) ALL fell back -- including the 1x1 case,
#     which changes the exact same byte count (2) as the successful
#     within-stripe swap above. Byte count alone can't be the deciding
#     factor if 2 bytes changed produces opposite outcomes depending on
#     what was swapped. A same-region swap in the dark-red stripe (columns
#     106-107, values 2 and 3, both native there) rendered correctly,
#     confirming a second, independent within-region success in a
#     different stripe with a different flag pair. The pattern across all
#     8 data points so far (2 within-region successes, 6 cross-region
#     failures at every size from 1 to 1600 pixels/side): edits that keep
#     every pixel within its OWN stripe's already-established flag set
#     (gray: {0,1,5,6,7,8,9,10}; dark-red: {2,3}; red: {4}) pass, and
#     edits that put a flag value into a column range where it doesn't
#     already belong fail -- regardless of how many bytes are touched
#     either way. Reads as a per-region (likely per-column-range)
#     flag-membership constraint, not a diff-size threshold. Not yet
#     tested: a within-region swap larger than 2 bytes, or whether the
#     boundary is truly per-stripe vs. some other partition that happens
#     to coincide with the 3 stripes here.
#   - CLOSED the "larger within-region swap" gap immediately after: two
#     40x40 blocks, BOTH entirely inside the gray stripe (columns 10-49
#     and 60-99) -- the exact same size as the 40x40 swap that failed
#     every time it crossed a stripe boundary -- were swapped with each
#     other. All 79 packets acked, and the panel rendered correctly,
#     confirmed by a user photo showing a clean 3-stripe layout, no
#     fallback. Edit size genuinely doesn't seem to matter once the
#     region-membership constraint holds: within-region edits now pass at
#     both 2 bytes changed and 3200 bytes changed, while cross-region
#     edits fail at every size tested from 2 to 3200 bytes. Still
#     untested: whether the boundary is truly per contiguous stripe or
#     something finer/coarser that happens to align with these 3 stripes.
#   - COMPLICATES the picture: testing that exact question found a
#     counterexample. Swapping columns 105 (last gray pixel) and 106
#     (first dark-red pixel) on row 0 -- a single-pixel-pair edit crossing
#     the stripe boundary exactly -- passed. All 79 packets acked, panel
#     rendered the real content, not the fallback. Every OTHER
#     cross-region edit tested (6/6, at sizes from 1 to 1600 pixels/side,
#     always at positions well inside a stripe's interior) failed. So the
#     "every pixel's flag must belong to its column's stripe" reading is
#     too strong as stated -- it predicted this should fail and it didn't.
#     Whatever the real invariant is, edits exactly at a stripe transition
#     behave differently from edits deep in a stripe's interior. Plausible
#     but untested: the real check is about local transition/run
#     structure (an interior edit creates a brand-new isolated anomaly
#     with two new transitions where none existed; a boundary edit just
#     adds a small wiggle at a transition that was already there) rather
#     than a strict per-column palette membership rule. Not yet tested:
#     whether nearby-but-not-exactly-at-the-boundary positions (e.g.
#     column 100 vs. 106) behave like "boundary" or like "interior".
#   - Human-verification caveat, going forward: distinguishing "correct
#     content with a 1-2px change" from "correct content, unchanged" by
#     eye is unreliable, since this GIF alternates between this frame and
#     a full solid-red reference frame and the flicker defeats fine
#     pixel-level inspection. Every pass/fail conclusion above actually
#     rests on a coarser, reliable distinction instead: fallback animation
#     (visibly different content) vs. real content (whichever frame,
#     edited or not), which is easy to tell apart on sight regardless of
#     the flicker.
#   - Two more tests settle it (13 data points total, no exceptions). A
#     swap 5 columns into the gray interior (column 100) with the
#     dark-red boundary pixel (column 106) -- crossing regions, NOT
#     adjacent -- fell back, same as every other non-adjacent cross-region
#     test. A swap at the OTHER stripe boundary (columns 211/212,
#     dark-red/red, adjacent) rendered correctly -- ruling out "something
#     specific to the gray/dark-red transition" as the explanation for the
#     first boundary success. The full picture (2 adjacent cross-region
#     successes at both boundaries, 7 non-adjacent cross-region failures,
#     3 within-region successes at various sizes) fits one clean account:
#     what fails is creating a brand-new isolated anomaly -- a
#     foreign-colored pixel with mismatched neighbors on both sides, which
#     is what every non-adjacent cross-region edit does. An adjacent swap
#     across a boundary just shifts an ALREADY-EXISTING transition by one
#     pixel instead of creating a new one; a within-region edit of any
#     size never introduces a foreign value at all. Reading this as a
#     check on each row's transition/run structure, not raw per-column
#     palette membership, explains all 13 hardware data points without
#     exception -- still a pattern match, not a decoded algorithm, but a
#     strong one now.
#   - The TOC-level delay field (`[16:18]`, previously "50 in every
#     capture, plausibly a delay, unit unconfirmed") is now genuinely
#     confirmed rather than just plausible: the user explicitly set the
#     frame speed to 50 in the Windows app when generating this capture,
#     and the wire value is literally 50 -- a real, user-controlled field,
#     not a coincidental shared UI default. Unit (likely centiseconds,
#     GIF's own convention) still unconfirmed; every capture so far used
#     the same speed setting.
#   - Stress-tested the transition/run-structure reading one step further:
#     a symmetric 3-pixel-wide block swap centered on the gray/dark-red
#     boundary (columns 103-105 <-> 106-108 on row 0 -- moving the
#     transition point by 3 columns as a single clean shift, not scattered
#     anomalies) also rendered correctly. So the tolerance isn't limited
#     to exactly-adjacent 1-pixel swaps; a small symmetric shift of an
#     existing transition works too. 14 hardware data points now fit
#     without exception. How far a shift can go before it starts failing
#     is untested.
#
# First active test of the 528-byte prefix's zero-padding region (bytes
# 18-527, all zero in every capture seen so far) -- on frame 0 (solid red,
# RLE mode, the simplest case): overwritten with increasingly large
# non-zero patterns, crc16_modbus recomputed correctly each time, all 79
# packets acked every time. Result: NOT inert padding, but not a strict
# all-zero requirement either --
#   200 bytes non-zero: fallback.
#   20 bytes: fallback.
#   10 bytes: fallback.
#   5 bytes: real content, not fallback.
#   1 byte (offset 18, flipped 0 -> 1): real content, not fallback.
# Rules out both "genuinely unused, ignored padding" (10+ bytes reliably
# fails) and "must be strictly all-zero" (1 and 5 non-zero bytes are both
# fine). The boundary sits between 5 and 10 bytes (offset 18+5=23 to
# 18+10=28), not yet pinned down further. This behaves differently in
# character from the content region's transition/run-structure tolerance
# (0.6.11-0.6.15): content-region within-region edits pass at ANY size
# tested up to 3200 bytes, while here even a fairly arbitrary 10-byte
# pattern already fails -- looks more like a literal magnitude/length
# threshold specific to this region, though it's also possible this
# boundary marks the start of a real, still-unidentified structured field
# that just happens to read as zero in every simple capture seen so far,
# rather than a tolerance-based check on otherwise-free padding. Whether
# this generalizes to frame 1 (raw-bitmap mode) is untested.
#
# Tight bisection pins the boundary down exactly: 7 bytes passes, 8 bytes
# passes, 9 bytes fails, 10 fails (0.6.16) -- EXACTLY 8 bytes tolerated.
# Isolating the 9th byte specifically (flipping ONLY offset 26 -- the byte
# that turns a passing 8-byte edit into a failing 9-byte one -- with
# offsets 18-25 left untouched) rendered correctly, not the fallback. So
# offset 26 is not itself a meaningfully-checked field; the 9-byte failure
# was purely about HOW MANY bytes were touched in total, not which byte.
# This confirms the "magnitude threshold" reading over "hidden structured
# field starting around offset 26": if there were a real field there,
# flipping it alone should have broken something, and it didn't. The
# padding region genuinely tolerates a small, fixed count of changed bytes
# (8) regardless of which ones, and rejects more than that -- a count-based
# check, not a positional one. Untested: whether "8" is specific to this
# region/frame or a broader constant, and whether the count that matters
# is "bytes changed from zero" specifically or something more general.
#
# Repeated on frame 1 (154128 bytes, raw-bitmap mode, padding starting at
# offset 38 instead of frame 0's offset 18): 8 non-zero bytes passes, 9
# fails -- EXACTLY the same boundary as frame 0 (1728 bytes, RLE mode).
# With the same threshold holding across two frames of very different
# size and content encoding, "8" looks like a genuine constant of the
# format or firmware, not an artifact of frame size, blob position, or
# encoding mode. Still no candidate mechanism for why 8 specifically.
#   - The 8 combo flags decompose into 3 independent per-channel bits: R is
#     hi(206) for flags {0,1,8,10} and lo(156) for {5,6,7,9}; B is hi(206)
#     for {0,1,7,9} and lo(156) for {5,6,8,10}; G is hi(215) for {0,5,8,9}
#     and lo(170) for {1,6,7,10}. Measured over all 50880 gray-stripe
#     pixels: R is lo 8.56% of the time, B is lo 8.50%, G is lo 31.25% --
#     in the same ballpark as (a little under) the naive linear-interpolation
#     duty cycle each channel would need to hit 200 from its own two
#     candidate values (12.0% for R/B between 156/206, 33.3% for G between
#     170/215). This supports reading the 8-slot palette as nothing more
#     than a precomputed enumeration of all 8 outcomes of 3 SEPARATE,
#     independent single-channel ditherers (R, G, and B each deciding
#     hi/lo on their own, low-rate for R/B, higher-rate for G) -- the
#     8 RGB565 corners exist only because RGB565 can't express "this
#     channel is dithered" as anything other than a fully-specified color,
#     not because the dithering logic itself is 3-dimensional.
#   - The per-row minor-flag count is bursty, not periodic: rows 0-2 have
#     zero minor-flag pixels, row 3 has 25, row 4 has 1, row 6 has 31, and
#     so on with no obvious fixed period (checked the first 40 rows).  A
#     fixed spatial Bayer/ordered-dither matrix would be expected to
#     distribute corrections roughly evenly across rows; this clustering
#     is a better fit for error diffusion or some other history-dependent
#     scheme, where the exact algorithm (diffusion direction/coefficients)
#     is still unidentified.
#
# save_to_gif_12/13's larger uploads also exposed and fixed a real modeling
# bug, not just a documentation gap: CRC_INIT was keyed by the cmd byte from
# final_chunk_cmd(), which seemed reasonable since cmd is derived from
# length -- but cmd = (CMD_WRITE + length % 256) % 256 is many-to-one.
# save_to_gif_12's 1080-byte final chunk collides on cmd (0x3F) with
# save_to_gif_10/11's 312-byte one, and save_to_gif_13's 248-byte one
# collides (0xFF) with save_to_gif_8's 2040-byte one -- and in both cases
# the correct init genuinely differs. A cmd-keyed dict silently gave the
# wrong answer for the second capture in each collision. CRC_INIT is now
# keyed by the actual payload length (crc16_packet() derives it from the
# body's own size rather than trusting a caller-supplied cmd), which is
# unambiguous by construction. All 15 captures re-verified byte-for-byte
# after the fix, including both collision pairs.
#
# CORRECTION: "the unidentified sub-header byte [13]" had been carried in
# this list as an open item across many rounds without being re-examined.
# It isn't a real mystery -- both bytes that could plausibly be meant are
# already fully solved elsewhere: the TOC-entry's own byte [13] is the
# frame count (solved back in the save_to_gif_3.pcapng round, see "TOC
# frame-count ambiguity resolved" in the changelog), and the per-frame
# sub-header's byte 13 is simply the high byte of the [12:14] content-length
# u16 field (solved and re-verified repeatedly this session, including for
# save_to_gif_13's overflowing case). Removed from the open list below.
#
# MILESTONE: the first fully from-scratch GIF -- not derived from any
# capture -- rendered correctly on hardware. Every prior success was a
# small edit to already-valid captured content; this proves the RLE model
# is complete enough to actually BUILD new working uploads. Built purely
# from the confirmed model: a TOC of 20-byte entries, each frame a
# 528-byte fixed prefix (copying the two still-unexplained-but-always-
# constant magic byte pairs verbatim; width/height/size32/content-length/
# mode_flag=0x0100/palette all derived from scratch) followed by
# continuous-raster-order RLE content, restricted to "safe" colors
# (max(R,G,B) in {0,255}) so no dithering needs solving. Content: frame 0
# solid blue, frame 1 a 16x16 red/white checkerboard -- new, never
# captured or mutated from one. The one practical obstacle, CRC_INIT
# (no general formula relating a final chunk's length to its init, so an
# arbitrary from-scratch length usually matches none of the ~13 solved
# values), was worked around without any new brute force: a solid run can
# be split into any number of chained same-flag tokens with no change to
# the rendered image, each split costing exactly 2 bytes, so frame 0's
# single run was split into enough pieces to land the wire packetization's
# final chunk exactly on an already-solved length (1080 bytes, from
# save_to_gif_12) -- no external padding, no new CRC_INIT entry. Self-
# verified before upload (TOC crc16_modbus matches, both frames' RLE
# content sums to exactly 153600 pixels, packetizes with no exceptions),
# then uploaded: all 12 packets acked, and the panel showed exactly the
# intended animation, confirmed by the user, not the fallback.
#
# 0.7.1 generalized this into build_gif_blob() (below) and wired it into
# cli.py as a real --target gif option, taking one image per frame via
# --upload. Re-verified byte-for-byte identical to the hand-built,
# hardware-confirmed 0.7.0 blob, then re-confirmed end-to-end through the
# actual CLI command (not a script bypassing it) with two fresh PNGs --
# all 12 packets acked, user confirmed the intended animation. The
# CRC_INIT-length-matching trick only works when some frame has a large
# enough solid region to split; build_gif_blob() raises a clear
# ValueError (naming the largest run found and the capacity needed) when
# none does, and a separate ValueError listing every offending color and
# its pixel count when a color needs dithering. Scope is still RLE-mode,
# non-dithered content only -- photos and the raw-bitmap format are out
# of reach for an encoder until the dithering algorithm is solved.
#
# save_to_gif_14.pcapng (a dimmed rainbow -- full hue sweep at ~70%
# brightness, so EVERY one of 320 columns needs dithering, two identical
# frames) is by far the richest dithering dataset yet, and it answers the
# open question of whether dither-pair colors are computed per-image or
# drawn from something fixed: THEY'RE FIXED. Both frames are
# mode_flag=0x0002 raw-bitmap, byte-identical to each other (deterministic
# encoding, as established). Per-column weighted-average color (from
# actual pixel flag frequencies) matches the intended target hue closely
# across all 320 columns -- mean error ~4/255, max ~11.5/255 -- the
# broadest confirmation yet that dithering reconstructs the intended color
# on average. The palette (46 entries) decomposes, in RGB565's native
# per-channel N-bit index terms, into two small FIXED sets: R and B
# indices are only ever one of {0,6,12,19,25} (of 0-31 possible); G
# indices are only ever one of {0,10,21,32,42,53} (of 0-63 possible) -- a
# 5-level ramp for the two 5-bit channels, a 6-level ramp for the 6-bit
# one, each roughly evenly spaced from 0 up to their top rung (206/255 for
# R/B, 215/255 for G). Cross-checked directly against save_to_gif_13's
# completely different image: every one of its dithered palette entries'
# per-channel indices falls within this SAME ramp -- the one exception
# (R index 31, i.e. 255) is the clean undithered reference red, not part
# of the dither ramp at all (255 is already a direct-slot "safe" value).
# The same exact rung values appearing byte-for-byte in two unrelated
# captures is strong evidence this is a genuine, image-independent
# hardware/firmware lookup table, not something computed fresh per
# upload. Refines the model: each channel snaps independently to the
# nearest rung(s) of this shared ramp, dithering between two adjacent
# rungs when the target falls between them and using a single rung
# directly (no dithering for that channel) when it's already close
# enough -- different pixels use 2 to 4 distinct palette entries
# depending on how many of the 3 channels actually need bracketing, not
# always the full 8-corner scheme seen for save_to_gif_13's one richly-
# dithered color. Also reconfirmed rows are NOT identical within a column
# (row 0 != row 240 != row 479 for the same target) -- the per-row
# variation seen in save_to_gif_13's light-gray stripe is pervasive across
# this whole image, not a minor addendum to an otherwise-static pattern.
# Open: whether the ramp has more/higher rungs than observed (neither test
# image's targets reached bright enough to need anything above n=25/53);
# the exact snap-vs-dither selection rule and duty-cycle algorithm between
# two rungs; the per-row variation's exact mechanism (error diffusion is
# still just a hypothesis, now with much richer data to eventually
# re-check it against).
#
# save_to_gif_15.pcapng (the same hue sweep as save_to_gif_14, but at 95%
# brightness instead of 70% -- targets up to 242, much closer to 255)
# closes that "higher rungs" question: two new top rungs appear that the
# dimmer test never triggered -- R/B index 31 (=255) and G index 63
# (=255). The full ramps are: R and B, 6 levels -- {0,6,12,19,25,31}
# (8-bit 0,49,99,156,206,255); G, 7 levels -- {0,10,21,32,42,53,63}
# (8-bit 0,40,85,130,170,215,255). The R/B ramp is an EXACT even 6-way
# split of the full 0-31 native range (round(i*31/5) for i=0..5
# reproduces it precisely). The G ramp is very close to but not quite an
# exact even 7-way split of 0-63 -- differs from naive rounding of
# i*63/6 by exactly 1 at a single point (53 vs. an evenly-rounded 52);
# every other level matches exactly -- reported honestly as "very close,
# not exact" rather than forcing a formula that doesn't quite fit.
# Weighted-average color per column again matches the intended target
# closely at this brighter setting (mean error ~3.8/255, max ~10.5/255),
# consistent with save_to_gif_14's dimmer test. The ramp is now fully
# characterized end-to-end: it spans each channel's ENTIRE native range,
# not capped below the maximum as it appeared to be before this capture
# -- that apparent cap was purely because neither earlier test image's
# targets were bright enough to need the top rung.
#
# Offline re-analysis of save_to_gif_14 (no new hardware, made possible
# now that the exact ramp is known): does the observed per-channel duty
# cycle match naive linear interpolation between the two bracketing
# rungs? Across 960 column/channel data points needing two-rung
# dithering: mean absolute deviation 3.4 percentage points, mean SIGNED
# deviation ~0 (0.002) -- no systematic bias toward either rung (357
# columns observed-high, 212 observed-low, 391 close enough to call
# exact). So linear interpolation is the right first-order model for what
# duty cycle each channel is aiming for, but the actual per-column result
# isn't an exact closed-form computation -- real, non-negligible variance
# (well above simple integer-rounding noise at 480 samples, which would
# be under 0.3 points) more consistent with an error-diffusion-style
# algorithm approximating the right long-run ratio than an exact ordered-
# dither formula. Worst mismatches (up to 26 points) cluster near ramp
# segments close to 0 (e.g. the {0,40} G bracket), not uniformly spread.
# Still doesn't identify the actual diffusion algorithm (coefficients,
# direction, whether it resets per row/column or runs continuously) --
# only confirms the deviation's character (unbiased, real, uneven).
#
# RESOLVED: whether mode_flag is a real, functional decoder switch or
# just a descriptive tag -- first direct hardware test, both directions,
# on save_to_gif_13. Frame 0 (solid red, real mode_flag=0x0100/RLE,
# content untouched) flipped to 0x0002/raw-bitmap: all 79 packets acked,
# and the panel rendered a complex, clearly non-fallback pattern --
# horizontal bands including a light-gray-like region, a red/black
# staticky "noise" band, and clean red regions, repeating a few times
# vertically. Not the fallback animation, not random garbage either --
# the visible structure (colors/layout resembling frame 1's real
# 3-stripe content) is consistent with the raw-bitmap decoder reading a
# full width*height=153600-byte window starting right after frame 0's
# 528-byte prefix regardless of frame 0's own much smaller declared size,
# likely running past frame 0's real boundary into frame 1's actual
# header/content bytes in flash -- though the exact byte-level
# correspondence wasn't rigorously confirmed, only the qualitative shape.
# The reverse (frame 1, the real raw-bitmap frame, content untouched,
# flipped from 0x0002 to 0x0100/RLE): all 79 packets acked, panel showed
# a garbled staggered-scanline pattern confined to roughly the top 25% of
# the screen, remaining ~75% unchanged solid red -- a partial, incomplete
# render, again not the fallback. Plausible (not verified with an exact
# token-count calculation): reinterpreting raw palette-index bytes as
# (length,flag) pairs roughly halves how many content bytes correspond to
# one pixel of coverage, so the declared byte-length content runs out
# before covering all 153600 pixels. NEITHER direction triggered the
# panel's usual cached fallback animation -- notably different from every
# other content-validation failure in this investigation, which always
# fell back to the same generic animation. Suggests whatever structural
# validation exists (the transition/run-structure check, the 528-byte-
# prefix count threshold) is checked WITHIN each decoder's own path, not
# by a separate universal content check applied regardless of mode -- a
# mismatched mode_flag bypasses the checks that would normally catch a
# malformed frame in its own format, because the bytes are fed to the
# wrong decoder entirely rather than being malformed input to the right
# one. Confirms mode_flag is a genuine, functional field, not a passive
# tag. Untested: exact overrun byte-mapping, why the RLE-misinterpretation
# stops at ~25%, and whether this generalizes beyond save_to_gif_13.
#
# 0.7.6 found a genuine, previously-untested constraint on the delay
# field while exercising build_gif_blob()'s new per-frame delay support
# with real hardware: a from-scratch 2-frame blob (solid red 300ms, solid
# blue 700ms, i.e. delay=[30,70] centiseconds) acked all 3 packets but
# fell back. The SAME content re-uploaded with a uniform delay=50 for
# both frames rendered correctly; the same content again with a uniform
# delay=30 (still not 50, but equal across frames) ALSO rendered
# correctly. Only the non-uniform [30,70] case failed. So the constraint
# is that every frame's delay must match, not that any particular value
# is required -- never tested before, since every capture and every
# hand-built test prior to this always used the same delay (usually 50)
# for every frame. Untested: whether the real rule is "exactly equal" or
# something looser (monotonic, within some tolerance) -- only one
# non-uniform pair and two uniform values have been tried.
#
# A real methodology shift: identified the underlying display chip and
# disassembled key functions in the vendor's own encoder DLL, rather than
# more hardware experiments. pic_scan.dll exports Gif_to_data AND
# Gif_to_data_LT7689 -- the panel is built on Levetop's LT7689, a
# Cortex-M4 serial UART TFT graphics controller. Its public datasheet and
# application notes document only a generic serial playback command
# (Display GIF, opcode 0x88 -- "start playing file N," not a format
# spec) and a companion tool, LT_IMAGE_TOOL.exe, whose own output format
# is confirmed plain, uncompressed 16bpp/24bpp RGB -- no palette, no RLE.
# So the entire RLE/8-slot-dithering/528-byte-prefix scheme is AULA's own
# bespoke compression layer, not a documented chip-vendor format -- it
# exists nowhere except inside this DLL and our own reverse-engineering.
#
# pic_scan.dll isn't fully stripped -- recovered full demangled C++ export
# names and disassembled the GIF-relevant ones (32-bit x86, RVAs resolved
# via the PE export table, image base 0x6a9c0000):
#   - Scan_aRGB8565: plain bit-truncation ARGB->RGB565 (R>>3-style
#     masking, no rounding, no dithering at all). Almost certainly the
#     simple photo-frame/background converter, not the GIF path.
#   - Scan_ColorTB_Data: divides a frame's pixels into up to 255 chunks,
#     each a 0x204-byte (516-byte) substructure -- matching the same
#     "0x204 bytes per iteration" stride independently inferred from
#     Image_u16Data_to_colorTBu8Data's loop structure.
#   - Scan_ColorTB_from_image_data: builds each chunk's local palette via
#     exact-match, first-appearance-order deduplication -- directly
#     matching our own reverse-engineered palette model.
#   - Image_u16Data_to_colorTBu8Data: converts pixels to palette indices
#     via a simple linear search (up to 256 entries) for an EXACT match
#     against the chunk's table. If no exact match is found, no output
#     byte is written at all -- no fallback, no on-the-fly quantization.
#   - The zero-initialized table Scan_ColorTB_from_image_data builds (516
#     bytes / 258 u16 entries, struct offsets 0x430-0x634) is
#     structurally very close to the 528-byte prefix (same role:
#     fixed-size, mostly-zero, holds RGB565 palette entries) -- not
#     proven byte-for-byte identical, but strong circumstantial support
#     for what that region fundamentally is.
# Critical implication: since an unmatched pixel is silently skipped (not
# quantized in place), whatever decides WHICH colors need dithering and
# rewrites source pixels into the correct alternating ramp-representable
# sequence must run BEFORE all four of these functions -- it isn't in any
# of the GIF-related exports checked. Most likely inlined inside
# Gif_to_data_LT7689 (a large orchestrator handling file I/O and memory
# allocation, only partially traced) or in a private, unexported helper
# with no symbol name to search for. Finding it would mean methodically
# stepping through that function's full call graph rather than checking
# named exports -- banked here as a larger effort for later, not pursued
# further this round.
#
# What's still open: the fixed 528-byte prefix's actual contents/purpose
# (confirmed NOT a color table, fixed-size up to 11 palette slots, still
# 528 bytes by construction in save_to_gif_13's frame 2 too -- size32 - 528
# matches the (overflowing) content-length field exactly -- and now known
# to tolerate EXACTLY 8 non-zero bytes anywhere in the padding, confirmed a
# pure count threshold (not a specific critical byte) that holds
# identically in both RLE-mode and raw-bitmap-mode frames, mechanism
# behind the count still unknown), the exact snap-vs-dither selection rule
# and diffusion algorithm for the now fully-characterized fixed dither
# ramp ({0,6,12,19,25,31} for R/B, {0,10,21,32,42,53,63} for G -- spanning
# each channel's entire native range, confirmed by save_to_gif_14/15;
# linear interpolation between bracketing rungs is a good but not exact
# model of the duty cycle, mean deviation 3.4 points with no systematic
# bias, more consistent with error diffusion than a closed-form formula;
# disassembly narrowed WHERE this logic must live -- before
# Scan_ColorTB_Data/Scan_ColorTB_from_image_data/Image_u16Data_to_
# colorTBu8Data, none of which contain it -- but didn't find the actual
# code, most likely inlined in Gif_to_data_LT7689 or an unexported
# helper),
# the G ramp's single unexplained off-by-one deviation from an exact even
# split, the per-row variation's exact mechanism (error diffusion is still
# just a hypothesis; per-row burstiness fits it better than a fixed Bayer
# matrix, but the real algorithm -- diffusion coefficients, direction,
# whatever it actually is -- isn't identified), the exact byte-level
# mechanics of what happens when mode_flag is forced to mismatch its
# content (confirmed functional/real, confirmed to produce structured
# garbage rather than a clean fallback in both directions, but the exact
# overrun/truncation mechanics aren't mapped), the exact scope/mechanism of the content validator -- 14 hardware
# data points now fit "a row's transition/run structure must stay locally
# valid" without exception (3 within-region swaps of any size pass; 3
# transition-preserving cross-region edits -- 2 adjacent single-pixel
# swaps and 1 symmetric 3-pixel shift -- pass; 7 non-adjacent cross-region
# swaps, which each create a brand-new isolated anomaly, all fail; how far
# a transition shift can go before failing is untested) -- a strong
# pattern match, not yet a decoded
# algorithm, and the delay field's unit (centiseconds is the leading
# guess) plus its uniformity constraint (confirmed all frames must share
# the same delay value, but not confirmed whether "exactly equal" is the
# real rule or just the only thing tested) -- and gif_2's
# solid frames being encoded far less efficiently (4151
# varied tokens for the same 153600-pixel solid red that save_to_gif_3/4/5
# encode in exactly 600 uniform tokens) -- possibly gif_2's source image
# wasn't perfectly flat, not investigated. It is NOT raw RGB565 for the
# RLE-mode frames (well under width*height*2 bytes), not zlib, not
# raw-deflate. No JPEG SOI marker (FFD8) appears anywhere in a frame.
#
# Resumed the 0.7.7 static-analysis pivot and closed it out: disassembled
# two previously-unexamined exports, SaveMode16 (VA 0x6a9c24f0) and
# SaveMode24 (0x6a9c3290), both called directly by Gif_to_data_LT7689.
# SaveMode16 dispatches on a mode parameter -- modes {2,5} pack ARGB4444,
# modes {1,4} pack RGB565 (plain shift+mask truncation, with a special
# case remapping opaque pure-black to 0x0021 so 0x0000 stays a
# transparency sentinel), and all other modes take a "default" path that
# ALSO just does RGB565 truncation. Modes {3,4,5} then proceed to call
# Scan_ColorTB_Data -> Scan_ColorTB_from_image_data ->
# Image_u16Data_to_colorTBu8Data -> ColorTB_u8Data_to_zipU8Data -- the
# exact chain from 0.7.7, now confirmed reachable end-to-end from
# Gif_to_data_LT7689 via SaveMode16, closing the gap 0.7.7 left open.
# SaveMode24 is confirmed the trivial 24bpp sibling (lossless 8-bit
# passthrough, no quantization needed, not a dithering candidate).
# Also fully traced Scan_ColorTB_Data (pure per-chunk orchestration,
# looping up to 255 times over Scan_ColorTB_from_image_data -- clarifying
# that the "<=256px chunking" cap most likely originates in this
# chunk-count limit, not the RLE token format's separate 256-run cap) and
# Scan_ColorTB_from_image_data (confirmed exact-match palette dedup on
# already-16-bit RGB565 words, zero per-channel math). Finally, all ~55
# register-indirect calls inside Gif_to_data_LT7689 were traced back to
# their register loads and resolved to QImage width/height/pixel/dtor,
# QString/QCoreApplication housekeeping, or memory alloc/free/refcount
# boilerplate -- none lead anywhere new.
#
# Net result: the ENTIRE call graph reachable from Gif_to_data_LT7689 is
# now exhaustively traced (not "partially traced, banked" as in 0.7.7)
# and confirmed free of any dithering decision -- every step is a
# stateless, per-pixel-independent truncation, exact-equality comparison,
# or RLE emission; no ramp constant appears as an immediate anywhere, and
# no per-channel accumulator is carried across loop iterations. Since the
# wire-capture evidence (0.6.1-0.6.9) already showed dithered patterns in
# the bytes actually transmitted, the dithering must happen somewhere in
# the PC-side pipeline before transmission -- but demonstrably not in
# anything Gif_to_data_LT7689 reaches. Full disassembly transcript,
# RVA/export/import tables, and per-function notes are checked in at
# tools/aula_l99_screen/re_notes/pic_scan_dll.md so this doesn't have to
# be re-derived again.
#
# Immediately followed up on the one remaining in-DLL candidate: traced
# Gif_to_data, the non-_LT7689 sibling export. Its direct-call set is
# identical to Gif_to_data_LT7689's (same Scan_aRGB8565/8888, SaveMode16/
# SaveMode24, flash-blob writers) with exactly one addition -- an
# unexported helper at VA 0x6a9c17f0 that reads a file in 2KB chunks and
# computes a running checksum via two 256-byte tables at .rdata VAs
# 0x6a9cb080/0x6a9cb180. Dumped those tables directly from the PE image
# and diffed them byte-for-byte against a from-scratch table for the
# reflected polynomial 0xA001 (the same poly this file's own
# crc16_packet() already uses) -- exact match, confirmed standard
# CRC-16/ARC. This is a file-integrity checksum, unrelated to pixel
# dithering; Gif_to_data is otherwise functionally identical to
# Gif_to_data_LT7689 for pixel processing. This rules out BOTH GIF-export
# entry points in pic_scan.dll -- every exported GIF-relevant function in
# the DLL, and everything reachable from any of them, has now been
# examined. The dithering decision is not anywhere in pic_scan.dll. The
# one remaining candidate is the qt-tool app's own .exe (not yet
# disassembled at all) -- e.g. a QImage::convertToFormat() call with an
# explicit dithering flag, executed by the app before ever calling into
# this DLL, which would be invisible no matter how thoroughly the DLL is
# traced.

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


HEADER_SIZE_WIRE = 10  # magic(2) + lenfield(2) + cmd(1) + const(1) + address(4)


def crc16_packet(body: bytes) -> int:
    """Packet checksum: reflected poly 0xA001, init keyed by payload length.

    Keyed by length, not by the cmd byte in `body` -- see CRC_INIT for why
    (cmd is a many-to-one function of length, so it can't disambiguate).
    """
    payload_len = len(body) - HEADER_SIZE_WIRE
    if payload_len not in CRC_INIT:
        raise ValueError(f"unknown payload length {payload_len}")
    crc = CRC_INIT[payload_len]
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
    return bytes(body) + struct.pack("<H", crc16_packet(bytes(body)))


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
            # Only ever 11 bytes for the 320x480 images this module builds,
            # giving CMD_FINAL -- see final_chunk_cmd() for why this isn't a
            # fixed opcode in general. A different image size would need a
            # CRC_INIT entry for whatever cmd this computes to; none is
            # known, so build_packet() raises rather than sending a bad CRC.
            packets.append(build_packet(final_chunk_cmd(len(chunk)), CONST_DATA, address, chunk))
        offset += take
        region_bytes += take

        at_region_end = (base + offset) - region_start >= REGION_SIZE
        if at_region_end or offset >= len(blob):
            packets.append(build_packet(CMD_COMMIT, CONST_COMMIT, region_start,
                                        struct.pack(">I", region_bytes)))
            region_start = base + offset
            region_bytes = 0
    return packets


# --- GIF encoder (0.7.0) ------------------------------------------------
#
# From-scratch construction of a GIF blob for GIF_FLASH_BASE, built purely
# from the model documented above -- not derived from any capture. First
# proven on hardware in 0.7.0 (a hand-built solid-blue + checkerboard
# animation). Scope: RLE-mode frames only (mode_flag=0x0100), using only
# "safe" colors -- max(R,G,B) in {0,255} -- since the dithering algorithm
# for anything else isn't solved (see the GIF_FLASH_BASE comment block).

GIF_FRAME_PREFIX_SIZE = 528

# Bytes 0-1 and 6-7 of every frame's sub-header have been byte-identical
# across every captured frame regardless of content, in every capture in
# this investigation. Meaning unknown; copied verbatim as fixed constants.
GIF_FRAME_MAGIC_A = bytes([0x4C, 0x54])
GIF_FRAME_MAGIC_B = bytes([0x01, 0x03])

# mode_flag values (header[14:16]) -- confirmed a real, functional decoder
# switch, not a passive tag (see the GIF_FLASH_BASE comment block).
GIF_MODE_RLE = 0x0100
GIF_MODE_RAW_BITMAP = 0x0002

# The full fixed dither ramp, characterized end-to-end in the comment block
# above (see save_to_gif_14/15). Each 8-bit value here was chosen because it
# reproduces its own RGB565 index exactly under rgb_to_rgb565()'s existing
# truncation masks (value // 8 for R/B, value // 4 for G) -- a pixel already
# sitting on one of these values needs zero changes to encode correctly.
RAMP_R: tuple[int, ...] = (0, 49, 99, 156, 206, 255)
RAMP_G: tuple[int, ...] = (0, 40, 85, 130, 170, 215, 255)
RAMP_B: tuple[int, ...] = RAMP_R


def nearest_ramp_value(value: float, ramp: tuple[int, ...]) -> int:
    """Snap value (clamped to [0, 255]) to the nearest rung of ramp."""
    value = 0.0 if value < 0 else 255.0 if value > 255 else value
    best = ramp[0]
    best_diff = abs(value - best)
    for rung in ramp[1:]:
        diff = abs(value - rung)
        if diff < best_diff:
            best, best_diff = rung, diff
    return best


# Precomputed nearest_ramp_value(v, RAMP_*) for every possible clamped/rounded
# input byte -- turns dither_frame_floyd_steinberg()'s hot per-pixel quantize
# step into an O(1) lookup instead of a linear scan over the ramp. Built once
# at import time from nearest_ramp_value() itself, so it can never drift out
# of sync with the reference implementation.
RAMP_R_LUT: tuple[int, ...] = tuple(nearest_ramp_value(v, RAMP_R) for v in range(256))
RAMP_G_LUT: tuple[int, ...] = tuple(nearest_ramp_value(v, RAMP_G) for v in range(256))
RAMP_B_LUT: tuple[int, ...] = RAMP_R_LUT


def is_ramp_legal_color(r: int, g: int, b: int) -> bool:
    """True if (r, g, b) already sits exactly on the device's fixed
    per-channel ramp -- the generalization of is_safe_gif_color() that also
    accepts dithered output, not just the always-safe corner subset. Every
    is_safe_gif_color() color is also ramp-legal (0 and 255 are ramp rungs
    on every channel), so this is strictly wider, never narrower.
    """
    return r in RAMP_R and g in RAMP_G and b in RAMP_B


def dither_frame_floyd_steinberg(
    pixels: list[tuple[int, int, int]], width: int
) -> list[tuple[int, int, int]]:
    """Classic raster-order Floyd-Steinberg error diffusion (7/16 right,
    3/16 below-left, 5/16 below, 1/16 below-right), applied independently
    per channel, quantizing each channel to the nearest rung of its own ramp
    (RAMP_R/RAMP_G/RAMP_B) and diffusing the residual to not-yet-visited
    neighbors.

    This does NOT reproduce AULA's own undiscovered device-side algorithm --
    disassembly of pic_scan.dll (see the comment block above) confirmed the
    dithering decision isn't in that DLL at all, and the display chip itself
    has no documented dithering of its own; it just displays whatever
    ramp-legal RGB565 value each pixel decodes to. So there is no "correct"
    algorithm to match here -- this is a source-side approximation that
    should look correct on real hardware since every output pixel is
    guaranteed ramp-legal by construction. CONFIRMED on real hardware:
    dithered content renders and animates correctly (user-reported and
    re-tested after the raw-bitmap-mode fixes below).

    Quantization uses RAMP_*_LUT (a precomputed table) rather than calling
    nearest_ramp_value() directly, for speed. Output is deterministic and
    always ramp-legal, but is a rounded-to-nearest-int approximation, not an
    exact float-precision match to nearest_ramp_value()'s own linear search
    -- expected and harmless here, since Floyd-Steinberg is chaotically
    sensitive to rounding anyway (a single boundary difference at one pixel
    cascades through the whole diffusion chain), so there was never a
    byte-exact algorithm being preserved in the first place.

    pixels: flat width*height list, raster order, one frame's worth.
    width: needed to compute row-wrap offsets for the below-row diffusion
    targets; must evenly divide len(pixels).

    Returns a new list of ramp-legal (r, g, b) tuples, same length as
    pixels; does not mutate the input.
    """
    n = len(pixels)
    if width <= 0 or n % width != 0:
        raise ValueError(f"width {width} doesn't evenly divide {n} pixels")
    height = n // width

    err_r = [0.0] * n
    err_g = [0.0] * n
    err_b = [0.0] * n
    out: list[tuple[int, int, int]] = [(0, 0, 0)] * n

    for y in range(height):
        row = y * width
        for x in range(width):
            i = row + x
            r0, g0, b0 = pixels[i]
            r, g, b = r0 + err_r[i], g0 + err_g[i], b0 + err_b[i]

            ri = 0 if r < 0 else 255 if r > 255 else int(r + 0.5)
            gi = 0 if g < 0 else 255 if g > 255 else int(g + 0.5)
            bi = 0 if b < 0 else 255 if b > 255 else int(b + 0.5)
            rq = RAMP_R_LUT[ri]
            gq = RAMP_G_LUT[gi]
            bq = RAMP_B_LUT[bi]
            out[i] = (rq, gq, bq)

            er, eg, eb = r - rq, g - gq, b - bq
            has_right = x + 1 < width
            has_left = x - 1 >= 0
            has_down = y + 1 < height

            if has_right:
                err_r[i + 1] += er * 7 / 16
                err_g[i + 1] += eg * 7 / 16
                err_b[i + 1] += eb * 7 / 16
            if has_down:
                if has_left:
                    err_r[i + width - 1] += er * 3 / 16
                    err_g[i + width - 1] += eg * 3 / 16
                    err_b[i + width - 1] += eb * 3 / 16
                err_r[i + width] += er * 5 / 16
                err_g[i + width] += eg * 5 / 16
                err_b[i + width] += eb * 5 / 16
                if has_right:
                    err_r[i + width + 1] += er * 1 / 16
                    err_g[i + width + 1] += eg * 1 / 16
                    err_b[i + width + 1] += eb * 1 / 16
        # Tight pure-Python loop with no natural GIL-release point of its own;
        # on a multi-core machine a thread that keeps re-acquiring the GIL
        # the instant it's released can starve other threads of it far more
        # than CPython's switch-interval alone would suggest (the "GIL
        # convoy" effect) -- e.g. the GUI's main thread stalls badly enough
        # to visibly freeze a QMovie spinner while this runs on a worker
        # thread. One yield per row (not per pixel -- that would meaningfully
        # slow this down) is enough opportunities for another thread to get
        # scheduled, and is a no-op when nothing else is runnable, as in
        # single-threaded CLI use.
        time.sleep(0)
    return out


def is_safe_gif_color(r: int, g: int, b: int) -> bool:
    """A color gets a direct, undithered palette slot only if its
    brightest channel is exactly 0 or 255 -- see the dithering-trigger
    rule in the GIF_FLASH_BASE comment block (12/12 tested colors fit
    this rule). Anything else needs dithering, which this encoder can't
    produce yet.
    """
    return max(r, g, b) in (0, 255)


def _gif_runs(pixels: list[tuple[int, int, int]]) -> list[tuple[int, tuple[int, int, int]]]:
    """Raster-order (length, color) runs -- the continuous-RLE model's
    input, before splitting into <=256px chained tokens.
    """
    runs = []
    i = 0
    n = len(pixels)
    while i < n:
        color = pixels[i]
        j = i
        while j < n and pixels[j] == color:
            j += 1
        runs.append((j - i, color))
        i = j
    return runs


def _gif_tokens(runs, palette_index, split_at=None):
    """split_at: optional (run_index, piece_count) to pad one run's
    encoding into more chained same-flag tokens without changing the
    rendered image -- each extra piece costs exactly 2 content bytes.
    """
    tokens = []
    for idx, (length, color) in enumerate(runs):
        flag = palette_index[color]
        if split_at is not None and idx == split_at[0]:
            pieces_count = split_at[1]
            base, extra = divmod(length, pieces_count)
            pieces = [base + (1 if k < extra else 0) for k in range(pieces_count)]
        else:
            pieces = []
            remaining = length
            while remaining > 0:
                take = min(256, remaining)
                pieces.append(take)
                remaining -= take
        for take in pieces:
            tokens.append((take, flag))
    return tokens


def _gif_raw_bitmap_content(pixels, palette_index) -> bytes:
    """One palette-index byte per pixel, raster order -- the same per-pixel
    index data _gif_tokens() would otherwise RLE-compress, emitted directly
    instead. Always exactly len(pixels) bytes, confirmed by both
    disassembly and direct hardware byte-edit tests (see the
    GIF_FLASH_BASE comment block).
    """
    return bytes(palette_index[c] for c in pixels)


def _gif_largest_run(frames_runs, eligible: set[int] | None = None):
    """(frame_index, run_index, length) of the single longest run across
    all frames -- the best candidate for the CRC_INIT-length-matching
    padding trick, since it has the most spare capacity.

    eligible: if given, only frame indices in this set are considered --
    used to skip raw-bitmap-mode frames, whose fixed-size content has no
    tokens to pad in the first place.
    """
    best = None
    for fi, runs in enumerate(frames_runs):
        if eligible is not None and fi not in eligible:
            continue
        for ri, (length, _color) in enumerate(runs):
            if best is None or length > best[2]:
                best = (fi, ri, length)
    return best


def build_gif_blob(frames_pixels: list[list[tuple[int, int, int]]],
                    width: int = PANEL_WIDTH, height: int = PANEL_HEIGHT,
                    delay: int | list[int] = 50, dither: bool = False) -> bytes:
    """Build a from-scratch GIF blob for GIF_FLASH_BASE.

    frames_pixels: one list of (r,g,b) tuples per frame, each width*height
    long, in raster order. Raises ValueError for any color needing
    dithering (unless dither=True), or if no frame has a solid/uniform run
    large enough to tune the upload length onto an already-solved
    CRC_INIT entry.

    delay: a single value applied to every frame, or one value per frame
    (matching frames_pixels in length) -- the TOC's delay field is a
    per-entry field structurally, though every capture seen so far used
    the same value across all of one upload's frames.

    dither: if True, run each frame through dither_frame_floyd_steinberg()
    before validating colors, so images using colors outside the safe
    corner set can still be encoded -- every resulting pixel is quantized
    onto the device's fixed ramp instead of being limited to max(R,G,B) in
    {0, 255}. Default False preserves the original safe-colors-only
    behavior exactly. CONFIRMED on real hardware -- see
    dither_frame_floyd_steinberg()'s docstring.

    Note: dithered content tends to alternate colors every 1-3px, which
    used to be able to starve the CRC_INIT-length-tuning pass above of the
    long solid run it needs for an entirely-dithered (no flat region
    anywhere) image. Now largely moot in practice: heavily-dithered
    content that would have hit this almost always triggers raw-bitmap
    mode instead (see "Mode selection" below), which pads itself and
    doesn't need a donor run at all. Still theoretically possible in an
    edge case where dithered RLE content stays just under the raw-bitmap
    threshold with no large run of its own -- keeping at least one
    sizable flat region (even a solid black border) avoids it entirely.

    Mode selection: each frame's content is normally RLE-encoded
    (mode_flag=GIF_MODE_RLE), matching every previously-validated capture.
    header[12:14] (the content-length field) is only 16 bits, so RLE
    content over 65535 bytes would silently wrap -- previously a real bug
    (dithering makes this easy to hit, since alternating pixels produce far
    more RLE bytes than flat safe-color content ever did). Any frame whose
    RLE content would exceed that range is automatically encoded as
    mode_flag=GIF_MODE_RAW_BITMAP instead: one palette-index byte per
    pixel, always exactly width*height bytes. Confirmed by both
    disassembly and a real hardware capture (save_to_gif_13's raw-bitmap
    frame, content=153600 bytes) that the raw-bitmap decoder ignores the
    declared content-length field entirely and always reads exactly
    width*height bytes based on the frame's own width/height fields, so
    this sidesteps the overflow regardless of how large width*height is.

    CONFIRMED on real hardware (user-reported bug -> fixed -> re-tested):
    a from-scratch raw-bitmap-mode frame (not just an edit to an existing
    capture) renders correctly, including one built from a dithered image.
    Previously this was genuinely untested beyond RLE mode's own
    hardware-validated history since 0.7.0 -- now it's confirmed working,
    not just theoretically sound.

    CRC-length tuning (below) prefers padding a raw-bitmap frame with
    harmless trailing filler bytes -- invisible to the decoder, which
    always reads exactly width*height bytes regardless of what follows --
    over the older RLE run-splitting trick, whenever at least one frame is
    raw-bitmap mode. This fixes a real bug: a single frame with detail/
    color variation everywhere (no flat region anywhere) forces raw-bitmap
    mode with no run-based content to pad, which used to make tuning
    impossible even for a "small" (few-frame) upload once resized to the
    panel's full resolution. Also CONFIRMED on real hardware: the filler
    bytes appended past the raw-bitmap decoder's declared width*height
    read window are correctly ignored, not inspected by whatever the
    still-poorly-understood content validator checks.
    """
    n = width * height
    for i, px in enumerate(frames_pixels):
        if len(px) != n:
            raise ValueError(f"frame {i}: expected {n} pixels ({width}x{height}), got {len(px)}")

    if isinstance(delay, int):
        delays = [delay] * len(frames_pixels)
    else:
        delays = list(delay)
        if len(delays) != len(frames_pixels):
            raise ValueError(f"delay list has {len(delays)} entries, expected {len(frames_pixels)}")

    if dither:
        frames_pixels = [dither_frame_floyd_steinberg(px, width) for px in frames_pixels]

    gate = is_ramp_legal_color if dither else is_safe_gif_color
    bad: dict[tuple[int, int, int], int] = {}
    for px in frames_pixels:
        for color in px:
            if not gate(*color):
                bad[color] = bad.get(color, 0) + 1
    if bad:
        lines = "\n".join(f"  rgb{color}: {count} pixels"
                           for color, count in sorted(bad.items(), key=lambda kv: -kv[1]))
        if dither:
            raise ValueError(
                "these colors aren't ramp-legal even after dithering -- this indicates a "
                "bug in dither_frame_floyd_steinberg (it should only ever emit ramp "
                "rungs), not a limitation of the source image:\n" + lines
            )
        raise ValueError(
            "these colors need dithering, which this from-scratch encoder can't "
            "produce yet (only max(R,G,B) in {0, 255} is supported):\n" + lines
        )

    frames_runs = [_gif_runs(px) for px in frames_pixels]

    # Build each frame's palette once (first-appearance-order dedup, shared
    # by both RLE and raw-bitmap content) and decide its mode up front --
    # this must stay fixed across the CRC-length-tuning retries below,
    # since raw-bitmap content has no tokens for split_at to pad.
    frame_palettes: list[list[tuple[int, int, int]]] = []
    frame_palette_indexes: list[dict[tuple[int, int, int], int]] = []
    frame_modes: list[bool] = []  # True = raw-bitmap
    for runs in frames_runs:
        palette: list[tuple[int, int, int]] = []
        palette_index: dict[tuple[int, int, int], int] = {}
        for _length, color in runs:
            if color not in palette_index:
                palette_index[color] = len(palette)
                palette.append(color)
        frame_palettes.append(palette)
        frame_palette_indexes.append(palette_index)
        frame_modes.append(len(_gif_tokens(runs, palette_index)) * 2 > 0xFFFF)

    frame_content_lengths = [0] * len(frames_pixels)

    def _verify_and_return(blob: bytes) -> bytes:
        for fi in range(len(frames_pixels)):
            if not frame_modes[fi] and frame_content_lengths[fi] > 0xFFFF:
                raise ValueError(
                    f"frame {fi}: RLE content grew to {frame_content_lengths[fi]} bytes "
                    "after CRC-length padding, exceeding the 16-bit content-length "
                    "field -- this is an unexpected edge case, please report it"
                )
        return blob

    def build_all(split_at=None, raw_pad=None):
        frame_bytes = []
        for fi, runs in enumerate(frames_runs):
            palette = frame_palettes[fi]
            palette_index = frame_palette_indexes[fi]

            if frame_modes[fi]:
                content = _gif_raw_bitmap_content(frames_pixels[fi], palette_index)
                if raw_pad is not None and raw_pad[0] == fi:
                    content = content + bytes(raw_pad[1])
                mode_flag = GIF_MODE_RAW_BITMAP
            else:
                frame_split = split_at[1:] if split_at and split_at[0] == fi else None
                tokens = _gif_tokens(runs, palette_index, split_at=frame_split)
                content = bytearray()
                for length, flag in tokens:
                    content.append(length - 1)
                    content.append(flag)
                mode_flag = GIF_MODE_RLE
            frame_content_lengths[fi] = len(content)

            header = bytearray(GIF_FRAME_PREFIX_SIZE)
            header[0:2] = GIF_FRAME_MAGIC_A
            header[2:4] = struct.pack("<H", width)
            header[4:6] = struct.pack("<H", height)
            header[6:8] = GIF_FRAME_MAGIC_B
            size32 = GIF_FRAME_PREFIX_SIZE + len(content)
            header[8:12] = struct.pack("<I", size32)
            header[12:14] = struct.pack("<H", len(content) % 65536)
            header[14:16] = struct.pack("<H", mode_flag)
            for i, color in enumerate(palette):
                off = 16 + i * 2
                # This caps the palette at (528-16)/2 = 256 slots. The full
                # ramp only has 6*7*6 = 252 legal (R,G,B) combinations, so
                # dither=True content can never structurally overflow this.
                if off + 2 > GIF_FRAME_PREFIX_SIZE:
                    raise ValueError(
                        f"frame {fi}: {len(palette)} distinct colors is too many for the "
                        f"528-byte prefix (only ever confirmed up to 11 slots)"
                    )
                header[off:off + 2] = struct.pack("<H", rgb_to_rgb565(*color))
            frame_bytes.append(bytes(header) + bytes(content))

        toc_size = 20 * len(frame_bytes)
        total_payload = sum(len(fb) for fb in frame_bytes)
        payload = b"".join(frame_bytes)
        crc = crc16_modbus(payload)

        toc = bytearray(toc_size)
        offset = toc_size
        for i, fb in enumerate(frame_bytes):
            e = 20 * i
            struct.pack_into("<I", toc, e + 0, offset)
            struct.pack_into("<I", toc, e + 4, total_payload)
            struct.pack_into("<H", toc, e + 8, width)
            struct.pack_into("<H", toc, e + 10, height)
            toc[e + 12] = 3  # constant format/version tag, matches every capture
            toc[e + 13] = len(frame_bytes)
            struct.pack_into("<H", toc, e + 14, 0)
            struct.pack_into("<H", toc, e + 16, delays[i])
            struct.pack_into("<H", toc, e + 18, crc)
            offset += len(fb)
        return bytes(toc) + payload

    baseline = build_all()
    base_remainder = len(baseline) % CHUNK_SIZE

    candidate_targets = sorted(set(CRC_INIT) | {0})
    deltas_any = sorted({(target - base_remainder) % CHUNK_SIZE for target in candidate_targets})
    deltas_even = [d for d in deltas_any if d % 2 == 0]

    if deltas_any and deltas_any[0] == 0:
        return _verify_and_return(baseline)

    # Prefer padding a raw-bitmap frame with harmless trailing filler bytes
    # (ignored by the decoder, which always reads exactly width*height bytes
    # regardless of what follows -- see the mode-selection docstring above).
    # Unlike RLE run-splitting, this has no capacity limit and isn't
    # restricted to even deltas, so it always succeeds whenever at least one
    # frame is raw-bitmap -- fixing the case that previously had no eligible
    # padding donor at all.
    raw_bitmap_frames = [fi for fi, raw in enumerate(frame_modes) if raw]
    if raw_bitmap_frames and deltas_any:
        return _verify_and_return(build_all(raw_pad=(raw_bitmap_frames[0], deltas_any[0])))

    # No raw-bitmap frame at all -- fall back to the original RLE
    # run-splitting trick, unchanged, including its even-delta and
    # run-capacity constraints.
    eligible = {fi for fi, raw in enumerate(frame_modes) if not raw}
    largest = _gif_largest_run(frames_runs, eligible=eligible)
    if largest is None:
        raise ValueError(
            "no frame has a large enough solid/uniform run to tune the upload length onto "
            "an already-solved CRC_INIT entry -- add a bigger solid-color region to one frame"
        )
    fi, ri, run_length = largest
    base_pieces = -(-run_length // 256)  # ceil
    capacity = run_length - base_pieces

    for delta in deltas_even:
        extra = delta // 2
        if extra <= capacity:
            return _verify_and_return(build_all(split_at=(fi, ri, base_pieces + extra)))

    raise ValueError(
        "no frame has a large enough solid/uniform run to tune the upload length onto "
        "an already-solved CRC_INIT entry -- add a bigger solid-color region to one frame "
        f"(largest run found: {run_length} px, needed capacity: "
        f"{deltas_even[0] // 2 if deltas_even else '?'} extra pieces)"
    )


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
