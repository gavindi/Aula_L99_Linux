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
    byte. Confirmed against 7 independent samples across 5 capture files:
    2048-byte chunks (len%256=0 -> cmd=0x07=CMD_WRITE), commits (always a
    4-byte payload -> cmd=0x0B=CMD_COMMIT), the photo-frame/background final
    chunk (11 bytes -> cmd=0x12=CMD_FINAL), and wireshark_dumps/
    save_to_gif_1/2/3/5.pcapng final chunks (1386 bytes -> 0x71, 1582 bytes ->
    0x35, 1450 bytes -> 0xB1, 120 bytes -> 0x7F -- every one predicted exactly
    by this formula before being checked; save_to_gif_4.pcapng repeats
    save_to_gif_3's 1450-byte/0xB1 case rather than adding a new one).

    This only gives you the cmd byte. There is no known general formula for
    the matching CRC_INIT entry (two hypotheses -- init as a function of just
    this cmd byte, or of the magic+lenfield+cmd prefix -- were brute-forced
    against all 7 known (cmd, init) pairs and neither held), so calling this
    with a payload length outside CRC_INIT will raise in crc16_packet().
    """
    return (CMD_WRITE + payload_len) % 256


# Each command uses its own CRC init; see final_chunk_cmd() above for why
# CMD_COMMIT/CMD_FINAL need their own entries despite not being independent
# opcodes. Verified against all 308 packets in both upstream photo-frame
# captures. 0x71/0x35/0xB1/0x7F are solved for exactly the lengths they were
# observed at (wireshark_dumps/save_to_gif_1/2/3/5.pcapng's final chunks) --
# not a general result, since no formula for CRC_INIT vs. length was found
# (see final_chunk_cmd()).
CRC_INIT = {
    CMD_WRITE: 0xF104,
    CMD_COMMIT: 0xEEC4,
    CMD_FINAL: 0xD141,
    0x71: 0x1CB0,   # save_to_gif_1.pcapng final chunk (1386-byte payload)
    0x35: 0xD9F1,   # save_to_gif_2.pcapng final chunk (1582-byte payload)
    0xB1: 0x9F4E,   # save_to_gif_3/4.pcapng final chunk (1450-byte payload)
    0x7F: 0x6F7A,   # save_to_gif_5.pcapng final chunk (120-byte payload)
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

# "Save to GIF", confirmed from four independent captures --
# wireshark_dumps/save_to_gif_1/2/3/4/5.pcapng: every capture's write/commit
# packets are reproduced byte-for-byte by build_packet() at this address
# (resolving one of the two undocumented slots the vendor binary references
# -- 0x04200000 remains unidentified). Address only: there is no builder for
# this format. The bytes written there are NOT build_image_file() output --
# see the GIF container notes below.
GIF_FLASH_BASE = 0x04240000

# GIF container format, from five captures: save_to_gif_1.pcapng (a real
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
#     [18:20] u16      the "other" color present in the frame, if any RGB565.
#                       0x0000 when the frame is a single flat color (both
#                       captures' frame 1). When frame 2 has one differently-
#                       colored pixel, this holds that color if it's NOT the
#                       first pixel (0xFFFF white in save_to_gif_4, since the
#                       diff is at the end) or the background color if the
#                       diff IS the first pixel (0xF800 red in save_to_gif_3,
#                       where [16:18] already claimed white for the diff
#                       pixel). This pair is internally consistent across
#                       save_to_gif_3 and 4, but does NOT explain
#                       save_to_gif_2: its three frames are each a single flat
#                       color with no second color, yet their color sits at
#                       [18:20] with [16:18]=0 -- the reverse of what this
#                       rule predicts. Unexplained; possibly tied to
#                       save_to_gif_2's much larger content length (below).
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
# Everything else in the sub-header, and the bulk of every frame's own
# payload, is still undecoded -- in particular, no confirmed model yet
# reconciles the clean per-row run-length reading above with the persistent,
# never-resetting flip seen in save_to_gif_3/4, or with the flag-mutation
# results just above. It is NOT raw RGB565 (frames are well under
# width*height*2 bytes), not zlib, not raw-deflate. No JPEG SOI marker
# (FFD8) appears anywhere in a frame.

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
