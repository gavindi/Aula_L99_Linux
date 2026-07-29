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
#     [16:18] u16      50 in all three captures -- plausibly a delay, unit
#                       unconfirmed (likely centiseconds, matching GIF's own
#                       convention); all three test/photo animations may just
#                       share the vendor UI's default
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
# What's still open: the fixed 528-byte prefix's actual contents/purpose
# (confirmed NOT a color table, fixed-size up to 11 palette slots, and still
# 528 bytes by construction in save_to_gif_13's frame 2 too -- size32 - 528
# matches the (overflowing) content-length field exactly), the unidentified
# sub-header byte [13], why a dithered color sometimes gets a simple 2-slot
# pair (dark red here, gray in gif_10/11/12) and sometimes an 8-slot
# per-channel grid (light gray here), the exact per-channel dithering
# algorithm behind the 8-slot scheme (measured duty cycles are in the
# right ballpark for simple linear interpolation, and the per-row
# burstiness argues for error diffusion over a fixed Bayer matrix, but the
# real algorithm -- diffusion coefficients, direction, whatever it
# actually is -- isn't identified), whether mode_flag genuinely selects
# RLE-vs-raw-bitmap encoding in general (only one example of each seen so
# far), the exact scope/mechanism of the content validator -- 9 data
# points (3 within-region swaps at 2/2/3200 bytes, all OK; 6 cross-region
# swaps from 2 to 3200 bytes, all fallback) fit "each stripe's pixels must
# stay within that stripe's own established flag set," ruling out both
# simple histogram preservation and any diff-size threshold across the
# full range tested, but this is a pattern match across 9 tests, not a
# decoded algorithm, and whether the true boundary is per-stripe or some
# finer/coarser partition is untested -- and gif_2's
# solid frames being encoded far less efficiently (4151
# varied tokens for the same 153600-pixel solid red that save_to_gif_3/4/5
# encode in exactly 600 uniform tokens) -- possibly gif_2's source image
# wasn't perfectly flat, not investigated. It is NOT raw RGB565 for the
# RLE-mode frames (well under width*height*2 bytes), not zlib, not
# raw-deflate. No JPEG SOI marker (FFD8) appears anywhere in a frame.

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
