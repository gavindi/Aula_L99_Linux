"""Vendor HID protocol for the AULA L99 keyboard (0C45:800A cable / 05AC:024F dongle).

Everything in the "cable path" section below was captured from the vendor
Windows app running under Wine and decoded against real hardware: the app's
HID feature-report ioctls were intercepted in winedevice.exe, giving full
64-byte payloads in both directions.

Cable path (0C45:800A, interface 3 -> /dev/hidrawN), CONFIRMED:
  - 64-byte HID feature reports (SET_REPORT/GET_REPORT, wValue 0x0300,
    wIndex 3), each preceded by a 0x00 report-id byte on Linux hidraw
    because the report descriptor declares no Report ID item.
  - Commands are 64-byte packets starting 0x04 <opcode>; byte 8 is the
    number of raw 64-byte data blocks that follow with no header of their own.
  - The device replies to a command with the same opcode and byte 3 = 0x01.
  - The final data block of a transfer carries 0xAA 0x55 at bytes 62..63.
  - Per-key colour is plain RGB, passed through literally (verified by
    setting #00FF00 -> "00 ff 00" and #0000FF -> "00 00 ff").
  - Data blocks flow out from the host for a write command (0x23) and back
    from the device for a query (0xF5); the header looks the same either way,
    so check the direction before assuming what a capture shows.
  - Not every command on this channel is session-framed, and not every one
    lays its blocks out the same way. The realtime colour stream (0x20) does
    neither -- see re_notes/color_stream.md -- so treat the begin/commit/end
    shape and the matrix block layout as properties of individual opcodes
    rather than of the channel.

Dongle path (05AC:024F, interface 3 -> /dev/hidrawN), CONFIRMED on an L99:
   - 32-byte interrupt reports (not feature reports) with a trailing
     sum(bytes[0:31]) & 0xFF checksum. The handshake and RTC-set below are the
     F75_Initializer prior art, and both worked on the L99 dongle unchanged:
     the session-init and session-query probes get their expected replies, and
     an RTC write returns the prior-art ack.
   - Byte 11 of the session-init reply is a per-device firmware/build version,
     not link state: 0x08 on the F75 MAX prior art, 0x29 on the L99 dongle
     under test, stable across sessions and unchanged before/after the
     keyboard pairs. Reply comparisons must not require it to match.
   - The keyboard's own reports (keystrokes) arrive on a different interface
     (0), not this vendor channel.

Still unidentified: opcode 0x00. The 16-bit value the commit reply carries at
offset 4 is confirmed to be a plain monotonic sequence counter (increments by
exactly 1 per commit regardless of payload content), not a checksum as
previously guessed here -- see re_notes/settings_write.md.

The panel's CPU/GPU and weather readout is not a protocol of its own: it rides
in the OP_RTC block below, on this same channel. See
re_notes/system_monitor_block.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# -- cable path (confirmed) --------------------------------------------------
REPORT_ID = 0x00
PACKET_SIZE = 64

CMD_PREFIX = 0x04
OP_BEGIN = 0x18          # open a session
OP_COMMIT = 0x02         # apply; reply carries 16 bits at offset 4
OP_RTC = 0x28            # set the clock *and* the panel's system-monitor and
                         # weather readout -- one block carrying both. See the
                         # RTC block layout further down.
OP_COLOR_SET = 0x23      # write per-key colour (9 blocks out)
OP_COLOR_STREAM = 0x20   # stream per-key colour in real time (8 blocks out).
                         # A second, quite different colour-write path: no
                         # session framing, a packed key order instead of the
                         # matrix layout, and no terminator block. The vendor
                         # app drives it at ~17 frames/s to animate the
                         # keyboard from the host. See re_notes/color_stream.md.
OP_COLOR_QUERY = 0xF5    # read back the keyboard's current per-key colour.
                         # The vendor app polls this ~27x/s to drive its
                         # on-screen preview, which means lighting effects run
                         # on the keyboard rather than being streamed from the
                         # PC.
                         #
                         # Confirmed against tmp/l99dump1.pcapng: unlike the
                         # write path, a query is NOT wrapped in a
                         # begin/commit/end session. The steady-state poll
                         # loop is just commit -> query -> 9 blocks in,
                         # repeated, with the commit apparently only needed
                         # to close out the previous query's read before the
                         # next one is issued (the very first query in the
                         # capture is preceded by a bare commit, not a
                         # begin). A begin/effect-select/commit/end session
                         # elsewhere in the same capture happens independent
                         # of this loop and doesn't interrupt it. The 9
                         # blocks carry the same [key_id, R, G, B] x16 layout
                         # as a write, except there is no terminator block:
                         # all 9 are real rows (0x00-0x8F), the 9th simply
                         # has no physical keys mapped into it.
OP_EFFECT = 0x13         # select a built-in effect (1 block out)
OP_SETTINGS_WRITE = 0x17 # apply the settings-panel block (1 block out); see
                         # re_notes/settings_write.md for the block layout
OP_AUDIO = 0x78          # push one frame of audio spectrum levels (1 block
                         # out). The host captures the PC's audio and does the
                         # FFT; the device only receives 23 numbers. See the
                         # audio block below and re_notes/audio_spectrum_block.md.
OP_END = 0xF0            # close a session

# --- built-in effects (opcode 0x13) ----------------------------------------
# The effect runs on the keyboard; the host only selects it and its parameters.
#
# Payload block, with the AA 55 trailer at bytes 14..15 rather than 62..63:
#   [0]      effect id
#   [1..3]   R G B
#   [8]      mode flag, 0x01 for most effects but 0x00 for ids 0x04 and 0x07
#   [9]      brightness, seen only as 0x05 (believed to be the 1..5 max)
#   [10]     speed, 1..5, confirmed by working the speed slider min..max
#   [14..15] AA 55
EFFECT_SPEED_MIN = 1
EFFECT_SPEED_MAX = 5
EFFECT_SPEED_DEFAULT = 3
EFFECT_BRIGHTNESS_MAX = 5
EFFECT_TRAILER_OFFSET = 14

# The vendor app lists 20 presets; the id is the 1-based position in that list.
# Ids 0x04..0x08 were confirmed by capture (selecting glittering, fluttering,
# colourful, breath and spectrum produced exactly those values); the rest are
# read off the app's list order and are untested.
EFFECT_NAMES = {
    0x01: "static",       # confirmed: pairs with a 0x23 per-key colour upload
    0x02: "single-on",
    0x03: "single-off",
    0x04: "glittering",   # confirmed
    0x05: "fluttering",   # confirmed
    0x06: "colourful",    # confirmed
    0x07: "breath",       # confirmed
    0x08: "spectrum",     # confirmed
    0x09: "outward",
    0x0A: "scrolling",
    0x0B: "rolling",
    0x0C: "rotating",
    0x0D: "explode",
    0x0E: "launch",
    0x0F: "ripples",
    0x10: "flowing",
    0x11: "pulsating",
    0x12: "tilt",
    0x13: "shuttle",
    0x14: "led-off",
}
EFFECT_CONFIRMED = frozenset({0x01, 0x04, 0x05, 0x06, 0x07, 0x08})

# Not a preset: the custom per-key mode, seen whenever the vendor app had the
# per-key colour editor open. Select this alongside a 0x23 colour upload.
EFFECT_CUSTOM = 0x80
EFFECT_NAMES[EFFECT_CUSTOM] = "custom (per-key)"

TRAILER = bytes([0xAA, 0x55])
TRAILER_OFFSET = 62

# --- RTC / system-monitor block (opcode 0x28) -------------------------------
# One block carries the clock, the CPU/GPU readings and the weather readout.
# Bytes 0..12 are confirmed against wall-clock time in a capture. Bytes 13..21
# were decoded from save_to_gif_16.pcapng cross-checked against
# DeviceDriver.exe, then confirmed on hardware by writing a distinctive value
# to each field and reading the panel -- see re_notes/system_monitor_block.md.
RTC_TAG = 0x5A
RTC_OFF_VIEW = 1        # selected screen-view index, 1-based (see build_rtc_blocks)
RTC_OFF_TAG = 2
RTC_OFF_YEAR = 3        # year since 2000
RTC_OFF_MONTH = 4
RTC_OFF_DAY = 5
RTC_OFF_HOUR = 6
RTC_OFF_MINUTE = 7
RTC_OFF_SECOND = 8
RTC_OFF_WEEKDAY = 10    # Sunday = 0
RTC_OFF_CPU_LOAD = 13   # per cent
RTC_OFF_CPU_TEMP = 14
RTC_OFF_GPU_LOAD = 15   # per cent
RTC_OFF_GPU_TEMP = 16
RTC_OFF_AIR_TEMP = 17   # current outside temperature
RTC_OFF_DAY_HIGH = 18
RTC_OFF_NIGHT_LOW = 19
RTC_OFF_CONDITION = 20
RTC_OFF_HUMIDITY = 21   # per cent

# The vendor app maps its weather provider's Chinese condition text onto these
# codes by substring search. Code 0 is ambiguous: it means "cloudy", but it is
# also what an unrecognised condition string leaves behind, since that is the
# initial value.
WEATHER_CONDITIONS = {
    "cloudy": 0,
    "clear": 1,
    "light-snow": 2,
    "thunder": 3,
    "rain": 4,
    "heavy-snow": 5,
}

# The dongle's RTC packet carries the same fields 4 bytes later than the cable
# block does. UNVERIFIED on two counts: no dongle has ever been tested, and the
# offsets come from a code path in DeviceDriver.exe that has never been
# captured on any device.
RTC_DONGLE_SHIFT = 4

# Every monitor field is one byte. The vendor reaches them via _wtoi followed
# by a low-byte store, so it wraps rather than validating; we accept the signed
# range too because air temperature and the night low go below zero in winter.
# Whether the panel *renders* those as signed is untested -- all we know is
# what the vendor app would have put on the wire.
MONITOR_VALUE_MIN = -128
MONITOR_VALUE_MAX = 255

# Byte 3 of a reply is an ack flag the device sets once it has processed the
# command.
ACK_OFFSET = 3
ACK_FLAG = 0x01
COMMIT_ERROR = 0xFF  # seen when committing a session that uploaded nothing

# Feature reports must not be issued back-to-back: with no gap at all the
# second data block of a transfer fails with ETIMEDOUT, and a reply read
# immediately after a command returns the command echoed with the ack still
# clear. The vendor app leaves a very uniform ~36.7ms between every packet,
# which looks like Windows timer granularity rather than a device requirement:
# 2ms was enough on the test unit. 10ms keeps a wide margin.
PACKET_GAP_SECONDS = 0.01

KEY_ROWS = 8
KEYS_PER_ROW = 16
BYTES_PER_KEY = 4
COLOR_BLOCK_COUNT = KEY_ROWS + 1  # 8 rows of keys + one terminator block

# The 84 physical keys, as sent by the vendor app. A key's id encodes its
# matrix position: row = id >> 4, column = id & 0x0F. Positions absent here
# have no key on an L99 and are transmitted as four zero bytes.
KEY_IDS = (
    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D,
    0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F,
    0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F,
    0x30, 0x31, 0x37, 0x38, 0x39, 0x3A, 0x3B, 0x3C, 0x3D, 0x3E, 0x3F,
    0x40, 0x41, 0x42, 0x43, 0x49, 0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x4F,
    0x50, 0x51, 0x52, 0x53, 0x54, 0x55, 0x5B, 0x5C, 0x5D, 0x5E,
    0x60, 0x62, 0x63, 0x64, 0x65, 0x66, 0x67,
    0x70, 0x71, 0x73, 0x75, 0x76, 0x77, 0x78, 0x79,
)

# --- realtime colour stream (opcode 0x20) -----------------------------------
# Decoded from save_to_gif_18.pcapng: 245 frames at ~17/s, animating one key
# from the host. Same [key_id, R, G, B] quads as OP_COLOR_SET, but laid out
# differently in three ways, all confirmed across every frame of that capture:
#
#   - 8 blocks, not 9, and none of them is a terminator: the payload is a flat
#     array of STREAM_SLOT_COUNT quads spanning all 8 blocks at once, rather
#     than one block per matrix row.
#   - The first STREAM_KEY_COUNT slots are the physical keys packed with no
#     gaps, in the order below; the remaining slots are zero padding.
#   - No 0xAA 0x55 trailer anywhere. TRAILER_OFFSET would land mid-quad here,
#     which is presumably why.
STREAM_BLOCK_COUNT = 8
STREAM_SLOT_COUNT = 128          # 8 blocks x 16 quads
STREAM_KEY_COUNT = 84            # the physical keys; the rest is zero padding

# The packed order. This is the same 84 ids as KEY_IDS, sorted into visual
# reading order -- rows top to bottom, keys left to right within a row. That
# was checked rather than eyeballed: it reproduces exactly by sorting the
# vendor layout XML's key rects by (top, left), which is how a host-side
# animation would want to walk the keyboard.
STREAM_KEY_ORDER = (
    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x77, 0x70, 0x71,
    0x73, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x67, 0x75,
    0x25, 0x26, 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x43, 0x76, 0x37,
    0x38, 0x39, 0x3A, 0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x41, 0x42, 0x55, 0x79, 0x49, 0x4A, 0x4B,
    0x4C, 0x4D, 0x4E, 0x4F, 0x50, 0x51, 0x52, 0x53, 0x54, 0x65, 0x78, 0x5B, 0x5C, 0x5D, 0x5E, 0x60,
    0x62, 0x63, 0x64, 0x66,
)

# The vendor app's frame period, for reference when driving this. Measured as
# the median gap between consecutive 0x20 command headers; within a frame it
# left only ~2.8ms between data blocks, far tighter than the ~36.7ms it uses
# everywhere else, which is more evidence that PACKET_GAP_SECONDS is a host
# artefact rather than a device requirement.
STREAM_FRAME_SECONDS = 0.0587

# --- audio spectrum block (opcode 0x78) -------------------------------------
# Decoded from save_to_gif_17.pcapng: 137 frames at ~21/s feeding the panel's
# spectrum analyser. Like the colour stream above, the host does all the work
# -- it captures the PC's audio via WASAPI loopback and runs the FFT itself,
# so what reaches the keyboard is 23 numbers and nothing else.
#
# The block is a data block, not a command, even though it happens to begin
# 0x04. Two things say so: the device echoes it back verbatim with byte 3
# still clear, exactly as it echoes the RTC data block, while every real
# command in the same capture comes back with byte 3 = 0x01; and byte 8 (the
# block-count field of a command) varies from 0 to 38 across frames, which is
# not a block count.
#
# Layout, with every field below constant across all 137 captured frames:
#     04 08 64 <23 levels> <38 zero bytes>
# and no 0xAA 0x55 trailer, which makes this the only outbound block in the
# protocol without one.
AUDIO_BAND_COUNT = 23
AUDIO_OFF_LEVELS = 3
AUDIO_LEVEL_MAX = 100

# Bytes 0..2. Named rather than inlined because two of the three are only
# provisionally constants -- see re_notes/audio_spectrum_block.md. Byte 1
# collides with EFFECT_NAMES[0x08] == "spectrum", which may be the Music
# Rhythm tab's rhythm style leaking through, or may be coincidence. Byte 2 is
# 100, which is either the full-scale denominator the levels are relative to
# or that tab's Amplitude slider, also a 0..100 control. One capture at one
# setting cannot tell those apart.
AUDIO_OFF_MODE = 0
AUDIO_OFF_STYLE = 1
AUDIO_OFF_SCALE = 2
AUDIO_MODE_DEFAULT = 0x04
AUDIO_STYLE_DEFAULT = 0x08
AUDIO_SCALE_DEFAULT = 0x64

# The vendor app's frame period, measured as the median gap between
# consecutive frames. Bands run low frequency to high: the opening frames of
# the capture are loud at band 0 and silent above band 4, and one late frame
# is silent below band 8, so the ordering is not in doubt.
AUDIO_FRAME_SECONDS = 0.047

# Every level the vendor app ever put on the wire, across both captures, is
# exactly floor(n * 8 / 5) for some n -- 0, 1, 3, 4, 6, 8, 9, 11, 12, 14, ...
# So its internal amplitude is a 0..62-ish integer scaled by 1.6 to reach 100,
# and the real resolution of this feed is about 63 steps, not 101. Nothing
# here enforces that; a level the app would never have produced is still a
# legal byte as far as we know.
AUDIO_LEVEL_QUANTUM = (8, 5)

# -- dongle path (prior art, confirmed on the L99) ---------------------------
DONGLE_PACKET_SIZE = 32

# Byte 11 of the session-init reply is a per-device firmware/build version,
# not link state: 0x08 on the AULA F75 MAX prior art, 0x29 on the L99 dongle
# under test, stable across sessions and unchanged before/after pairing. So it
# must be excluded from reply comparisons -- see dongle_replies_match().
SESSION_INIT_VERSION_BYTE = 11

SESSION_INIT_OUT = bytes.fromhex(
    "0200000000000000000000000000000000000000000000000000000000000002"
)
# The reply below is the L99 dongle's own bytes, byte 11 = 0x29 included. The
# F75_Initializer capture of the same probe differs only at byte 11 (0x08).
SESSION_INIT_IN = bytes.fromhex(
    "02000040300000450c0a802901ffff0000000000000000000000000000000075"
)
SESSION_QUERY_OUT = bytes.fromhex(
    "2001000000000000000000000000000000000000000000000000000000000021"
)
SESSION_QUERY_IN = bytes.fromhex(
    "2001006400000000000000000000000000000000000000000000000000000085"
)
RTC_SET_ACK = bytes.fromhex(
    "0c1000000000000000000000000000000000000000000000000000000000001c"
)


# Retries exist for one situation: the vendor app being open at the same time.
# It holds the same hidraw node and polls 0xF5 continuously, so our reads pick
# up the replies to its polls (04 F5 00 FF) and time out. 9 attempts were
# needed to open a session under that contention; with the app closed none are
# needed, even with an effect running on the keyboard.
SESSION_OPEN_RETRIES = 20
RETRY_DELAY_SECONDS = 0.05


@dataclass(frozen=True)
class Transaction:
    name: str
    outgoing: bytes
    expect_reply: bool = False
    expected_reply: bytes | None = None
    retry_until_ack: bool = False


@dataclass(frozen=True)
class MonitorData:
    """The nine system-monitor/weather values the RTC block carries.

    All default to zero, which is what the block looked like in every capture
    taken before save_to_gif_16 -- so a default instance reproduces the
    clock-only block the vendor app sends when it has nothing to report.
    """
    cpu_load: int = 0
    cpu_temp: int = 0
    gpu_load: int = 0
    gpu_temp: int = 0
    air_temp: int = 0
    day_high: int = 0
    night_low: int = 0
    condition: int = 0
    humidity: int = 0

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            encode_monitor_value(getattr(self, field_name), field_name)

    @property
    def is_empty(self) -> bool:
        return all(getattr(self, f) == 0 for f in self.__dataclass_fields__)


def encode_monitor_value(value: int, name: str = "value") -> int:
    """One monitor field as the byte that goes on the wire."""
    if not MONITOR_VALUE_MIN <= value <= MONITOR_VALUE_MAX:
        raise ValueError(
            f"{name} must be {MONITOR_VALUE_MIN}..{MONITOR_VALUE_MAX}, got {value}"
        )
    return value & 0xFF


def checksum(payload: bytes) -> int:
    """Dongle-path checksum. Not used by the cable path, which has no checksum
    byte in any captured packet."""
    return sum(payload) & 0xFF


def finalize_dongle_packet(body: bytes) -> bytes:
    if len(body) != DONGLE_PACKET_SIZE - 1:
        raise ValueError(f"body must be {DONGLE_PACKET_SIZE - 1} bytes, got {len(body)}")
    return body + bytes([checksum(body)])


def dongle_replies_match(reply: bytes, expected: bytes) -> bool:
    """Whether a dongle-path reply is the expected one.

    The only tolerated differences are SESSION_INIT_VERSION_BYTE and the
    trailing checksum byte that necessarily follows it: the F75 prior art
    showed the version byte differing between keyboards, and since the checksum
    covers it, those two bytes change together. The reply's own checksum is
    still validated, so a corrupt reply is never accepted. For any packet that
    is not session-init the version byte is zero in both, so the comparison can
    only pass if the whole reply matches.
    """
    if reply == expected:
        return True
    if len(reply) != DONGLE_PACKET_SIZE or len(expected) != DONGLE_PACKET_SIZE:
        return False
    if reply[-1] != checksum(reply[:-1]):
        return False
    return (
        reply[:SESSION_INIT_VERSION_BYTE] == expected[:SESSION_INIT_VERSION_BYTE]
        and reply[SESSION_INIT_VERSION_BYTE + 1:-1]
        == expected[SESSION_INIT_VERSION_BYTE + 1:-1]
    )


def parse_hex_packet(value: str) -> bytes:
    """Turn a hex string (spaces/colons allowed) into bytes."""
    cleaned = value.replace(" ", "").replace(":", "").replace("0x", "")
    return bytes.fromhex(cleaned)


def parse_rgb(value: str) -> tuple[int, int, int]:
    """Parse 'RRGGBB' or '#RRGGBB' into an (r, g, b) tuple."""
    text = value.lstrip("#").strip()
    if len(text) != 6:
        raise ValueError(f"expected 6 hex digits (RRGGBB), got {value!r}")
    raw = bytes.fromhex(text)
    return (raw[0], raw[1], raw[2])


def parse_condition(value: str) -> int:
    """Parse a weather condition given either by name or as a number."""
    text = value.strip().lower()
    if text in WEATHER_CONDITIONS:
        return WEATHER_CONDITIONS[text]
    try:
        return int(text, 0)
    except ValueError:
        names = ", ".join(sorted(WEATHER_CONDITIONS))
        raise ValueError(f"unknown condition {value!r}; expected a number or one of: {names}")


def parse_audio_levels(value: str) -> list[int]:
    """Parse a comma- or space-separated list of band levels.

    Short lists are legal and are padded with silence by build_audio_blocks(),
    so "100" is a valid frame meaning "band 0 only".
    """
    text = value.replace(",", " ").split()
    if not text:
        raise ValueError("no levels given")
    levels = []
    for band, item in enumerate(text):
        try:
            levels.append(int(item, 0))
        except ValueError:
            raise ValueError(f"band {band}: {item!r} is not a number")
    return levels


def build_command(opcode: int, block_count: int = 0) -> bytes:
    """A 64-byte command header. `block_count` is how many raw data blocks the
    host will send immediately afterwards."""
    packet = bytearray(PACKET_SIZE)
    packet[0] = CMD_PREFIX
    packet[1] = opcode
    packet[8] = block_count
    return bytes(packet)


def _terminator_block() -> bytes:
    block = bytearray(PACKET_SIZE)
    block[TRAILER_OFFSET:TRAILER_OFFSET + 2] = TRAILER
    return bytes(block)


def build_color_blocks(colors: dict[int, tuple[int, int, int]]) -> list[bytes]:
    """Build the 9 data blocks for a per-key colour transfer.

    `colors` maps key id -> (r, g, b). Keys absent from the mapping are sent as
    four zero bytes, which is what the vendor app does for matrix positions
    with no physical key.
    """
    for key_id, rgb in colors.items():
        if key_id not in KEY_IDS:
            raise ValueError(f"key id 0x{key_id:02X} is not a physical key on the L99")
        if len(rgb) != 3 or not all(0 <= c <= 255 for c in rgb):
            raise ValueError(f"bad colour for key 0x{key_id:02X}: {rgb!r}")

    blocks = []
    for row in range(KEY_ROWS):
        block = bytearray(PACKET_SIZE)
        for column in range(KEYS_PER_ROW):
            key_id = (row << 4) | column
            rgb = colors.get(key_id)
            if rgb is None:
                continue
            offset = column * BYTES_PER_KEY
            block[offset] = key_id
            block[offset + 1:offset + 4] = bytes(rgb)
        blocks.append(bytes(block))
    blocks.append(_terminator_block())
    return blocks


def build_uniform_colors(rgb: tuple[int, int, int]) -> dict[int, tuple[int, int, int]]:
    """Every physical key set to one colour."""
    return {key_id: rgb for key_id in KEY_IDS}


def parse_color_blocks(blocks: list[bytes]) -> dict[int, tuple[int, int, int]]:
    """Decode the data blocks returned by an OP_COLOR_QUERY read.

    Inverse of build_color_blocks(), except a query reply has no terminator
    block: every block is a real row, so all of them are scanned the same way.
    Positions with no physical key (key id absent from KEY_IDS, including the
    all-zero padding in the last block) are dropped.

    Blocks are length-checked like parse_stream_blocks() and
    parse_audio_block() do. Today's callers read via get_feature(), which
    always returns exactly PACKET_SIZE bytes because the ioctl fills a
    preallocated buffer -- but the slicing below would silently return a
    2-element "colour" for a short block rather than failing, so a caller
    switching to read_report() (which returns whatever arrived) would get
    wrong colours instead of an error.
    """
    colors: dict[int, tuple[int, int, int]] = {}
    for index, block in enumerate(blocks):
        if len(block) != PACKET_SIZE:
            raise ValueError(
                f"block {index}: expected a {PACKET_SIZE}-byte block, got {len(block)}")
        for column in range(KEYS_PER_ROW):
            offset = column * BYTES_PER_KEY
            key_id = block[offset]
            if key_id in KEY_IDS:
                colors[key_id] = tuple(block[offset + 1:offset + 4])
    return colors


def build_color_query_commands() -> list[Transaction]:
    """The two framed commands that precede a colour read: commit (closing
    out whatever came before) then the query itself, announcing 9 inbound
    blocks. Follow this with COLOR_BLOCK_COUNT raw get_feature() reads, which
    have no framing of their own -- see parse_color_blocks()."""
    return [
        Transaction("commit", build_command(OP_COMMIT), expect_reply=True,
                    retry_until_ack=True),
        Transaction("color-query", build_command(OP_COLOR_QUERY, COLOR_BLOCK_COUNT),
                    expect_reply=True, retry_until_ack=True),
    ]


def build_stream_blocks(colors: dict[int, tuple[int, int, int]]) -> list[bytes]:
    """Build the 8 data blocks of one realtime-stream frame (opcode 0x20).

    Unlike build_color_blocks(), the quads are packed into STREAM_KEY_ORDER
    rather than placed at their matrix position, so a key missing from
    `colors` is still transmitted -- as its own id with black -- because
    leaving its slot out would shift every key after it. That is what the
    vendor app does: every frame in the capture carried all 84 ids, with the
    83 unlit keys sitting at 00 00 00.
    """
    for key_id, rgb in colors.items():
        if key_id not in KEY_IDS:
            raise ValueError(f"key id 0x{key_id:02X} is not a physical key on the L99")
        if len(rgb) != 3 or not all(0 <= c <= 255 for c in rgb):
            raise ValueError(f"bad colour for key 0x{key_id:02X}: {rgb!r}")

    payload = bytearray(STREAM_SLOT_COUNT * BYTES_PER_KEY)
    for slot, key_id in enumerate(STREAM_KEY_ORDER):
        offset = slot * BYTES_PER_KEY
        payload[offset] = key_id
        payload[offset + 1:offset + 4] = bytes(colors.get(key_id, (0, 0, 0)))
    return [bytes(payload[i:i + PACKET_SIZE])
            for i in range(0, len(payload), PACKET_SIZE)]


def parse_stream_blocks(blocks: list[bytes]) -> dict[int, tuple[int, int, int]]:
    """Decode one stream frame. Inverse of build_stream_blocks().

    Reads by slot position rather than trusting the id byte, so a frame whose
    order differs from STREAM_KEY_ORDER shows up as a mismatch instead of
    being silently accepted.
    """
    payload = b"".join(blocks)
    expected = STREAM_SLOT_COUNT * BYTES_PER_KEY
    if len(payload) != expected:
        raise ValueError(f"expected {expected} bytes of stream payload, got {len(payload)}")

    colors: dict[int, tuple[int, int, int]] = {}
    for slot, key_id in enumerate(STREAM_KEY_ORDER):
        offset = slot * BYTES_PER_KEY
        if payload[offset] != key_id:
            raise ValueError(
                f"slot {slot} holds key 0x{payload[offset]:02X}, expected "
                f"0x{key_id:02X}; this frame is not in STREAM_KEY_ORDER"
            )
        colors[key_id] = tuple(payload[offset + 1:offset + 4])
    return colors


def build_stream_frame(colors: dict[int, tuple[int, int, int]]) -> list[Transaction]:
    """One frame of the realtime colour stream.

    Deliberately not built on build_transfer(): the capture shows this path
    carries no session framing at all. There is no begin and no end anywhere
    in it, and the commit comes *after* the data blocks rather than before,
    which is the opposite of the OP_COLOR_QUERY poll loop. Repeat this
    sequence once per frame; the vendor app repeats it every
    STREAM_FRAME_SECONDS.
    """
    blocks = build_stream_blocks(colors)
    transactions = [
        Transaction("stream", build_command(OP_COLOR_STREAM, len(blocks)),
                    expect_reply=True, retry_until_ack=True),
    ]
    transactions += [
        Transaction(f"stream-block{i}", block) for i, block in enumerate(blocks)
    ]
    transactions.append(Transaction("commit", build_command(OP_COMMIT), expect_reply=True,
                                    retry_until_ack=True))
    return transactions


def build_audio_blocks(levels: list[int], scale: int = AUDIO_SCALE_DEFAULT,
                       mode: int = AUDIO_MODE_DEFAULT,
                       style: int = AUDIO_STYLE_DEFAULT) -> list[bytes]:
    """The single data block of one audio spectrum frame (opcode 0x78).

    `levels` is up to AUDIO_BAND_COUNT band magnitudes, low frequency first.
    A short list is padded with zeroes, so passing one value drives band 0 and
    leaves the rest silent -- which is the useful shape for working out which
    bar of the panel is which band.

    Levels are checked against `scale` rather than against AUDIO_LEVEL_MAX,
    because no captured frame ever exceeded byte 2 and the honest reading of
    that byte is "the value the levels are relative to". If `scale` really
    turns out to be an unrelated amplitude setting, this check is too strict
    and the fix is to drop it, not to widen it silently.
    """
    if len(levels) > AUDIO_BAND_COUNT:
        raise ValueError(
            f"at most {AUDIO_BAND_COUNT} bands, got {len(levels)}")
    for byte_value, name in ((scale, "scale"), (mode, "mode"), (style, "style")):
        if not 0 <= byte_value <= 0xFF:
            raise ValueError(f"{name} must be 0..255, got {byte_value}")
    for band, level in enumerate(levels):
        if not 0 <= level <= scale:
            raise ValueError(
                f"band {band} level must be 0..{scale} (the scale byte), got {level}")

    block = bytearray(PACKET_SIZE)
    block[AUDIO_OFF_MODE] = mode
    block[AUDIO_OFF_STYLE] = style
    block[AUDIO_OFF_SCALE] = scale
    block[AUDIO_OFF_LEVELS:AUDIO_OFF_LEVELS + len(levels)] = bytes(levels)
    return [bytes(block)]


def parse_audio_block(block: bytes) -> tuple[list[int], int]:
    """Decode one audio frame into its levels and its scale byte.

    Inverse of build_audio_blocks(). Returns all AUDIO_BAND_COUNT levels
    including trailing zeroes, since a silent high band is a real reading
    rather than absent data.
    """
    if len(block) != PACKET_SIZE:
        raise ValueError(f"expected a {PACKET_SIZE}-byte block, got {len(block)}")
    levels = list(block[AUDIO_OFF_LEVELS:AUDIO_OFF_LEVELS + AUDIO_BAND_COUNT])
    return levels, block[AUDIO_OFF_SCALE]


def build_audio_frame(levels: list[int], scale: int = AUDIO_SCALE_DEFAULT,
                      **kwargs) -> list[Transaction]:
    """One frame of the audio spectrum feed.

    Like build_stream_frame(), and unlike build_transfer(), this carries no
    session framing -- but the commit sits *before* the command here rather
    than after it, matching the captured cycle exactly:

        commit -> 0x78 announcing one block -> the block

    An RTC write interleaved cleanly into the middle of that loop in the
    capture without disturbing it, so the two feeds do not need sequencing
    against each other. Repeat this every AUDIO_FRAME_SECONDS to animate.
    """
    blocks = build_audio_blocks(levels, scale, **kwargs)
    return [
        Transaction("commit", build_command(OP_COMMIT), expect_reply=True,
                    retry_until_ack=True),
        Transaction("audio", build_command(OP_AUDIO, len(blocks)),
                    expect_reply=True, retry_until_ack=True),
        Transaction("audio-block0", blocks[0]),
    ]


def _write_monitor_fields(buffer: bytearray, monitor: MonitorData, shift: int = 0) -> None:
    """Place the nine monitor bytes, optionally shifted for the dongle layout."""
    for offset, value, name in (
        (RTC_OFF_CPU_LOAD, monitor.cpu_load, "cpu_load"),
        (RTC_OFF_CPU_TEMP, monitor.cpu_temp, "cpu_temp"),
        (RTC_OFF_GPU_LOAD, monitor.gpu_load, "gpu_load"),
        (RTC_OFF_GPU_TEMP, monitor.gpu_temp, "gpu_temp"),
        (RTC_OFF_AIR_TEMP, monitor.air_temp, "air_temp"),
        (RTC_OFF_DAY_HIGH, monitor.day_high, "day_high"),
        (RTC_OFF_NIGHT_LOW, monitor.night_low, "night_low"),
        (RTC_OFF_CONDITION, monitor.condition, "condition"),
        (RTC_OFF_HUMIDITY, monitor.humidity, "humidity"),
    ):
        buffer[offset + shift] = encode_monitor_value(value, name)


def build_rtc_blocks(when: datetime, monitor: MonitorData | None = None,
                     view: int = 1) -> list[bytes]:
    """The single data block of the RTC-set command.

    Bytes 0..12 confirmed against wall-clock time in two captures:
        00 VV 5a YY MM DD hh mm ss 00 WD 00...  with AA 55 at bytes 62..63
    where YY is the year since 2000 and WD is the weekday (Sunday = 0). The
    weekday reading comes from a single sample, so it is the least certain
    field here; the keyboard may well ignore it.

    `view` is byte 1, which an earlier reading of this block took for a
    constant 0x01. The vendor app computes it as the index of the selected
    screen view in its own list, plus one, so 1 means "the first view" -- which
    is why it looked constant. On hardware, view 0 is ignored (the panel never
    shows the data) while every value >= 1 lands on the same real-time readout
    frame; views 1, 2, 3 and 5 were confirmed identical in routing, and the
    byte does not switch the panel's screen. The values are only visible while
    the panel is actually showing that frame, which is a property of the
    screen, not of the view byte.

    `monitor` fills bytes 13..21 with the CPU/GPU and weather readout the panel
    displays; each field was confirmed on hardware by writing a distinctive
    value and reading the panel. Omitting it leaves them zero, which is the
    block every capture before save_to_gif_16 showed.
    """
    year = when.year - 2000
    if not 0 <= year <= 255:
        raise ValueError(f"year {when.year} cannot be encoded as year-since-2000")
    if not 0 <= view <= 255:
        raise ValueError(f"view must be 0..255, got {view}")

    block = bytearray(PACKET_SIZE)
    block[RTC_OFF_VIEW] = view
    block[RTC_OFF_TAG] = RTC_TAG
    block[RTC_OFF_YEAR] = year
    block[RTC_OFF_MONTH] = when.month
    block[RTC_OFF_DAY] = when.day
    block[RTC_OFF_HOUR] = when.hour
    block[RTC_OFF_MINUTE] = when.minute
    block[RTC_OFF_SECOND] = when.second
    block[RTC_OFF_WEEKDAY] = when.isoweekday() % 7
    _write_monitor_fields(block, monitor or MonitorData())
    block[TRAILER_OFFSET:TRAILER_OFFSET + 2] = TRAILER
    return [bytes(block)]


def build_transfer(opcode: int, blocks: list[bytes], name: str) -> list[Transaction]:
    """Wrap a data transfer in the session framing the vendor app always uses:
    begin, command + blocks, commit, end."""
    transactions = [
        Transaction("begin", build_command(OP_BEGIN), expect_reply=True,
                    retry_until_ack=True),
        Transaction(name, build_command(opcode, len(blocks)), expect_reply=True,
                    retry_until_ack=True),
    ]
    transactions += [
        Transaction(f"{name}-block{i}", block) for i, block in enumerate(blocks)
    ]
    transactions.append(Transaction("commit", build_command(OP_COMMIT), expect_reply=True,
                                    retry_until_ack=True))
    transactions.append(Transaction("end", build_command(OP_END), expect_reply=True,
                                    retry_until_ack=True))
    return transactions


def build_color_transfer(colors: dict[int, tuple[int, int, int]]) -> list[Transaction]:
    """Set per-key colours (opcode 0x23).

    The persistent colour-write path: it presumably writes flash, since the
    setting survives a replug, so avoid calling it in a tight loop. For
    animation use build_stream_frame() (opcode 0x20) instead, which the vendor
    app runs at ~17 frames/s -- a rate nothing would survive against flash, so
    that path is almost certainly volatile. "Almost certainly" because nothing
    here has been tested against a replug; all we have is the capture.
    """
    return build_transfer(OP_COLOR_SET, build_color_blocks(colors), "color")


def build_effect_blocks(
    effect_id: int,
    rgb: tuple[int, int, int] = (0xFF, 0x00, 0x00),
    speed: int = EFFECT_SPEED_DEFAULT,
    brightness: int = EFFECT_BRIGHTNESS_MAX,
    mode_flag: int | None = None,
) -> list[bytes]:
    """The single data block that selects a built-in effect.

    `mode_flag` defaults to the value the vendor app used for this id: 0x00 for
    the two effects seen with it, 0x01 otherwise. Pass it explicitly to
    experiment.
    """
    if not 0 <= effect_id <= 0xFF:
        raise ValueError(f"effect id out of range: {effect_id}")
    if not EFFECT_SPEED_MIN <= speed <= EFFECT_SPEED_MAX:
        raise ValueError(f"speed must be {EFFECT_SPEED_MIN}..{EFFECT_SPEED_MAX}, got {speed}")
    if not 1 <= brightness <= EFFECT_BRIGHTNESS_MAX:
        raise ValueError(f"brightness must be 1..{EFFECT_BRIGHTNESS_MAX}, got {brightness}")
    if len(rgb) != 3 or not all(0 <= c <= 255 for c in rgb):
        raise ValueError(f"bad colour: {rgb!r}")

    if mode_flag is None:
        mode_flag = 0x00 if effect_id in (0x04, 0x07) else 0x01

    block = bytearray(PACKET_SIZE)
    block[0] = effect_id
    block[1:4] = bytes(rgb)
    block[8] = mode_flag
    block[9] = brightness
    block[10] = speed
    block[EFFECT_TRAILER_OFFSET:EFFECT_TRAILER_OFFSET + 2] = TRAILER
    return [bytes(block)]


def build_effect_transfer(effect_id: int, **kwargs) -> list[Transaction]:
    return build_transfer(OP_EFFECT, build_effect_blocks(effect_id, **kwargs), "effect")


def build_rtc_transfer(when: datetime, monitor: MonitorData | None = None,
                       view: int = 1) -> list[Transaction]:
    return build_transfer(OP_RTC, build_rtc_blocks(when, monitor, view), "rtc")


def build_cable_handshake() -> list[Transaction]:
    """Open and close a session — enough to prove the channel works.

    Deliberately no commit: committing a session that uploaded nothing makes
    the device reply with COMMIT_ERROR rather than an ack.
    """
    return [
        Transaction("begin", build_command(OP_BEGIN), expect_reply=True,
                    retry_until_ack=True),
        Transaction("end", build_command(OP_END), expect_reply=True),
    ]


def build_dongle_handshake() -> list[Transaction]:
    return [
        Transaction("session-init", SESSION_INIT_OUT, True, SESSION_INIT_IN),
        Transaction("session-query", SESSION_QUERY_OUT, True, SESSION_QUERY_IN),
    ]


def build_dongle_rtc_packet(when: datetime, monitor: MonitorData | None = None) -> bytes:
    """RTC-set for the 32-byte dongle format. Unconfirmed prior art; the cable
    path uses build_rtc_blocks() instead.

    Two mutually incompatible layouts are in play here, and this function picks
    between them, which is ugly but honest:

    - With no monitor data (the default) it emits the F75_Initializer prior-art
      packet unchanged: tag at 4..5, clock at 6..11, AA 55 at 17..18.
    - With monitor data it switches to the layout read out of DeviceDriver.exe's
      own dongle path: the cable block shifted +RTC_DONGLE_SHIFT, so tag at
      5..6, clock at 7..12, monitor at 17..25, AA 55 at 26..27.

    Those two disagree by one byte throughout, and the prior art's trailer sits
    exactly where the vendor layout puts the first monitor field, so there is no
    splice of the two that either source supports. At least one reading is
    wrong. The prior art is from a *different keyboard* (AULA F75 MAX) while the
    vendor layout is this device's own code, which argues for the latter -- but
    the vendor dongle path has never been captured, and no L99 dongle has ever
    been tested at all, so neither is confirmed. Whichever you try first, expect
    to have to try the other.
    """
    year = when.year - 2000
    if not 0 <= year <= 255:
        raise ValueError(f"year {when.year} cannot be encoded as year-since-2000")

    if monitor is None or monitor.is_empty:
        body = bytes(
            [
                0x0C, 0x10, 0x00, 0x00, 0x01, 0x5A,
                year, when.month, when.day, when.hour, when.minute, when.second,
                0x00, 0x05, 0x00, 0x00, 0x00, 0xAA, 0x55,
            ]
            + [0x00] * 12
        )
        return finalize_dongle_packet(body)

    shift = RTC_DONGLE_SHIFT
    body = bytearray(DONGLE_PACKET_SIZE - 1)
    body[0:4] = bytes([0x0C, 0x10, 0x00, 0x00])
    body[RTC_OFF_VIEW + shift] = 0x01
    body[RTC_OFF_TAG + shift] = RTC_TAG
    body[RTC_OFF_YEAR + shift] = year
    body[RTC_OFF_MONTH + shift] = when.month
    body[RTC_OFF_DAY + shift] = when.day
    body[RTC_OFF_HOUR + shift] = when.hour
    body[RTC_OFF_MINUTE + shift] = when.minute
    body[RTC_OFF_SECOND + shift] = when.second
    body[RTC_OFF_WEEKDAY + shift] = when.isoweekday() % 7
    _write_monitor_fields(body, monitor, shift)
    trailer_at = RTC_OFF_HUMIDITY + shift + 1
    body[trailer_at:trailer_at + 2] = TRAILER
    return finalize_dongle_packet(bytes(body))
