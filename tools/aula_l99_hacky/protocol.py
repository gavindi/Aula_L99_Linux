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

Dongle path (05AC:024F), NOT CONFIRMED: 32-byte interrupt reports with a
trailing sum(bytes[0:31]) & 0xFF checksum, inherited from prior art on the
AULA F75 MAX (Simon-Martens/F75_Initializer). No L99 dongle has been tested,
and the wired device's format differs, so treat it as a starting guess.

Still unidentified: opcodes 0x13 and 0x00, and the 16-bit value the commit
returns at offset 4 (most likely a checksum over the upload).
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
OP_RTC = 0x28            # set the keyboard's clock (1 data block)
OP_COLOR_SET = 0x23      # write per-key colour (9 blocks out)
OP_COLOR_QUERY = 0xF5    # read back the keyboard's current per-key colour.
                         # The vendor app polls this ~27x/s to drive its
                         # on-screen preview, which means lighting effects run
                         # on the keyboard rather than being streamed from the
                         # PC. Reading is not implemented here yet.
OP_END = 0xF0            # close a session

TRAILER = bytes([0xAA, 0x55])
TRAILER_OFFSET = 62

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

# -- dongle path (unconfirmed prior art) -------------------------------------
DONGLE_PACKET_SIZE = 32
SESSION_INIT_OUT = bytes.fromhex(
    "0200000000000000000000000000000000000000000000000000000000000002"
)
SESSION_INIT_IN = bytes.fromhex(
    "02000040300000450c0a800801ffff0000000000000000000000000000000054"
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


@dataclass(frozen=True)
class Transaction:
    name: str
    outgoing: bytes
    expect_reply: bool = False
    expected_reply: bytes | None = None


def checksum(payload: bytes) -> int:
    """Dongle-path checksum. Not used by the cable path, which has no checksum
    byte in any captured packet."""
    return sum(payload) & 0xFF


def finalize_dongle_packet(body: bytes) -> bytes:
    if len(body) != DONGLE_PACKET_SIZE - 1:
        raise ValueError(f"body must be {DONGLE_PACKET_SIZE - 1} bytes, got {len(body)}")
    return body + bytes([checksum(body)])


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


def build_rtc_blocks(when: datetime) -> list[bytes]:
    """The single data block of the RTC-set command.

    Layout confirmed against wall-clock time in a capture:
        00 01 5a YY MM DD hh mm ss 00 WD 00...  with AA 55 at bytes 62..63
    where YY is the year since 2000 and WD is the weekday (Sunday = 0). The
    weekday reading comes from a single sample, so it is the least certain
    field here; the keyboard may well ignore it.
    """
    year = when.year - 2000
    if not 0 <= year <= 255:
        raise ValueError(f"year {when.year} cannot be encoded as year-since-2000")

    block = bytearray(PACKET_SIZE)
    block[1] = 0x01
    block[2] = 0x5A
    block[3] = year
    block[4] = when.month
    block[5] = when.day
    block[6] = when.hour
    block[7] = when.minute
    block[8] = when.second
    block[10] = when.isoweekday() % 7
    block[TRAILER_OFFSET:TRAILER_OFFSET + 2] = TRAILER
    return [bytes(block)]


def build_transfer(opcode: int, blocks: list[bytes], name: str) -> list[Transaction]:
    """Wrap a data transfer in the session framing the vendor app always uses:
    begin, command + blocks, commit, end."""
    transactions = [
        Transaction("begin", build_command(OP_BEGIN), expect_reply=True),
        Transaction(name, build_command(opcode, len(blocks)), expect_reply=True),
    ]
    transactions += [
        Transaction(f"{name}-block{i}", block) for i, block in enumerate(blocks)
    ]
    transactions.append(Transaction("commit", build_command(OP_COMMIT), expect_reply=True))
    transactions.append(Transaction("end", build_command(OP_END), expect_reply=True))
    return transactions


def build_color_transfer(colors: dict[int, tuple[int, int, int]]) -> list[Transaction]:
    """Set per-key colours (opcode 0x23).

    This is the only colour-write path seen in any capture. It presumably
    writes flash, since the setting survives a replug, so avoid calling it in a
    tight loop.
    """
    return build_transfer(OP_COLOR_SET, build_color_blocks(colors), "color")


def build_rtc_transfer(when: datetime) -> list[Transaction]:
    return build_transfer(OP_RTC, build_rtc_blocks(when), "rtc")


def build_cable_handshake() -> list[Transaction]:
    """Open and close a session — enough to prove the channel works.

    Deliberately no commit: committing a session that uploaded nothing makes
    the device reply with COMMIT_ERROR rather than an ack.
    """
    return [
        Transaction("begin", build_command(OP_BEGIN), expect_reply=True),
        Transaction("end", build_command(OP_END), expect_reply=True),
    ]


def build_dongle_handshake() -> list[Transaction]:
    return [
        Transaction("session-init", SESSION_INIT_OUT, True, SESSION_INIT_IN),
        Transaction("session-query", SESSION_QUERY_OUT, True, SESSION_QUERY_IN),
    ]


def build_dongle_rtc_packet(when: datetime) -> bytes:
    """RTC-set for the 32-byte dongle format. Unconfirmed prior art; the cable
    path uses build_rtc_blocks() instead."""
    year = when.year - 2000
    if not 0 <= year <= 255:
        raise ValueError(f"year {when.year} cannot be encoded as year-since-2000")

    body = bytes(
        [
            0x0C, 0x10, 0x00, 0x00, 0x01, 0x5A,
            year, when.month, when.day, when.hour, when.minute, when.second,
            0x00, 0x05, 0x00, 0x00, 0x00, 0xAA, 0x55,
        ]
        + [0x00] * 12
    )
    return finalize_dongle_packet(body)
