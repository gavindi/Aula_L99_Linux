"""Vendor HID protocol facts for the AULA L99 keyboard (0C45:800A cable / 05AC:024F dongle).

Confirmed so far (via prior art on this exact VID/PID — see PLAN.md for sources):
  - Cable path:  64-byte HID feature reports (SET_REPORT / GET_REPORT) on interface 3.
  - Dongle path: 32-byte HID interrupt reports on interface 3.
  - Every 32-byte packet's last byte is a checksum: sum(bytes[0:31]) & 0xFF.
  - A session handshake (init, then query) precedes at least the RTC-set command;
    treat it as a precondition for any other vendor command until proven otherwise.
  - The cable path additionally wraps that in session-init / session-prepare /
    ... / session-finalize framing (see build_cable_transaction_sequence).

NOT yet confirmed for this VID/PID: RGB/lighting effect commands, per-key color
layout, or macro commands. `send-hex` in cli.py exists to test candidate
packets pulled from your own USB capture against real hardware.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

DONGLE_PACKET_SIZE = 32
CABLE_PACKET_SIZE = 64

# -- Session handshake (dongle path, 32-byte interrupt reports) --------------
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

# -- Session handshake (cable path, 64-byte feature reports) -----------------
CABLE_SESSION_INIT_OUT = bytes.fromhex(
    "04180000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000"
)
CABLE_SESSION_PREPARE_OUT = bytes.fromhex(
    "04280000000000000100000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000"
)
CABLE_SESSION_FINALIZE_OUT = bytes.fromhex(
    "04020000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000"
)


def checksum(payload: bytes) -> int:
    return sum(payload) & 0xFF


def finalize_dongle_packet(body: bytes) -> bytes:
    if len(body) != DONGLE_PACKET_SIZE - 1:
        raise ValueError(f"body must be {DONGLE_PACKET_SIZE - 1} bytes, got {len(body)}")
    return body + bytes([checksum(body)])


def build_rtc_set_packet(when: datetime) -> bytes:
    """RTC-set command, confirmed for this exact keyboard by prior art. Sets the
    keyboard's clock, which is what gets it out of boot-logo mode on the F75 MAX;
    worth trying first on the L99 as a sanity check that the handshake + checksum
    scheme really is shared."""
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


def parse_hex_packet(value: str) -> bytes:
    """Turn a hex string (spaces/colons allowed) into bytes, e.g. from a Wireshark 'Hex Stream' column."""
    cleaned = value.replace(" ", "").replace(":", "").replace("0x", "")
    return bytes.fromhex(cleaned)


@dataclass(frozen=True)
class Transaction:
    name: str
    outgoing: bytes
    expected_reply: bytes | None = None
    read_delay_seconds: float = 0.02


def build_dongle_handshake() -> list[Transaction]:
    return [
        Transaction("session-init", SESSION_INIT_OUT, SESSION_INIT_IN),
        Transaction("session-query", SESSION_QUERY_OUT, SESSION_QUERY_IN),
    ]


def build_cable_handshake() -> list[Transaction]:
    return [
        Transaction("cable-session-init", CABLE_SESSION_INIT_OUT),
        Transaction("cable-session-prepare", CABLE_SESSION_PREPARE_OUT),
    ]
