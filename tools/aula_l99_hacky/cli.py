"""CLI for the AULA L99's vendor HID channel (0C45:800A cable / 05AC:024F dongle).

Usage:
    python3 -m aula_l99_hacky.cli --list
    python3 -m aula_l99_hacky.cli --handshake
    python3 -m aula_l99_hacky.cli --color 0000FF
    python3 -m aula_l99_hacky.cli --read-color
    python3 -m aula_l99_hacky.cli --effect 0x05 --color 0000FF --speed 5
    python3 -m aula_l99_hacky.cli --rtc
    python3 -m aula_l99_hacky.cli --send-hex "04 23 00 00 00 00 00 00 09 ..."

The colour and RTC commands are confirmed against real hardware on the wired
0C45:800A path. `--send-hex` remains the slot for testing a candidate packet
pulled from a fresh capture of the vendor app.

A udev rule granting the logged-in user access to the keyboard's hidraw nodes
is usually already in place, so root is typically not needed.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime

from . import protocol
from .device import HidrawTransport, enumerate_hidraw, find_l99


def _print_devices() -> None:
    for device in enumerate_hidraw():
        vid = f"{device.vendor_id:04x}" if device.vendor_id is not None else "????"
        pid = f"{device.product_id:04x}" if device.product_id is not None else "????"
        iface = device.interface_number if device.interface_number is not None else "?"
        print(f"{device.path}  vid={vid} pid={pid} iface={iface}  {device.name or ''}")


def _run_cable(transport: HidrawTransport, tx: protocol.Transaction,
               debug: bool, gap: float) -> bytes | None:
    """One cable-path transaction: a feature report out, optionally one back.

    Linux hidraw needs an explicit report-id byte, and the L99's vendor
    interface declares no Report ID item, so it is always 0x00. Every packet is
    followed by a gap; see PACKET_GAP_SECONDS for why.
    """
    transport.set_feature(bytes([protocol.REPORT_ID]) + tx.outgoing)
    if debug:
        print(f"{tx.name}: out={tx.outgoing.hex()}")
    time.sleep(gap)
    if not tx.expect_reply:
        return None
    reply = transport.get_feature(protocol.REPORT_ID, protocol.PACKET_SIZE + 1)[1:]
    time.sleep(gap)
    if debug:
        print(f"{tx.name}: in ={reply.hex()}")
    return reply


def _run_dongle(transport: HidrawTransport, tx: protocol.Transaction, debug: bool) -> bytes:
    outgoing = tx.outgoing.ljust(protocol.DONGLE_PACKET_SIZE, b"\x00")
    transport.write(bytes([protocol.REPORT_ID]) + outgoing)
    if debug:
        print(f"{tx.name}: out={outgoing.hex()}")
    reply = transport.read_report(max_length=protocol.DONGLE_PACKET_SIZE)
    print(f"{tx.name}: in ={reply.hex()}")
    if tx.expected_reply is not None and reply != tx.expected_reply:
        print(f"{tx.name}: WARNING reply did not match the value from prior art", file=sys.stderr)
    return reply


def _acked(tx: protocol.Transaction, reply: bytes) -> bool:
    return (reply[0] == protocol.CMD_PREFIX
            and reply[1] == tx.outgoing[1]
            and bool(reply[protocol.ACK_OFFSET] & protocol.ACK_FLAG))


def _run_sequence(device, transactions, args) -> int:
    """Run a cable-path transaction list, checking each reply acks its opcode."""
    failures = 0
    with HidrawTransport(device.path, timeout_seconds=args.timeout) as transport:
        for tx in transactions:
            attempts = protocol.SESSION_OPEN_RETRIES if tx.retry_until_ack else 1
            reply = None
            for attempt in range(1, attempts + 1):
                try:
                    reply = _run_cable(transport, tx, args.debug, args.gap)
                except OSError as exc:
                    # The keyboard is busy (an effect is running); it recovers.
                    if attempt == attempts:
                        raise
                    if args.debug:
                        print(f"{tx.name}: attempt {attempt} failed ({exc.strerror}), retrying")
                    time.sleep(protocol.RETRY_DELAY_SECONDS)
                    continue
                if reply is None or _acked(tx, reply):
                    break
                if attempt < attempts:
                    if args.debug:
                        print(f"{tx.name}: attempt {attempt} not acked "
                              f"({reply[:4].hex()}), retrying")
                    time.sleep(protocol.RETRY_DELAY_SECONDS)

            if reply is None:
                continue
            if not _acked(tx, reply):
                print(f"{tx.name}: WARNING no ack for opcode "
                      f"0x{tx.outgoing[1]:02x}, got {reply[:4].hex()}", file=sys.stderr)
                failures += 1
    return failures


def _require_cable(device, what: str):
    if not device.is_cable:
        print(f"{what} is only implemented for the wired 0C45:800A path; "
              f"the dongle's packet format has never been captured.", file=sys.stderr)
        return False
    return True


def cmd_handshake(args: argparse.Namespace) -> int:
    device = find_l99()
    print(f"using {device.path} ({'cable' if device.is_cable else 'dongle'})")
    if device.is_cable:
        return 1 if _run_sequence(device, protocol.build_cable_handshake(), args) else 0

    with HidrawTransport(device.path, timeout_seconds=args.timeout) as transport:
        transport.drain()
        for tx in protocol.build_dongle_handshake():
            _run_dongle(transport, tx, args.debug)
    return 0


def cmd_color(args: argparse.Namespace) -> int:
    device = find_l99()
    if not _require_cable(device, "setting colours"):
        return 1

    try:
        rgb = protocol.parse_rgb(args.color)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"using {device.path}; setting all {len(protocol.KEY_IDS)} keys to "
          f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}")

    transactions = protocol.build_color_transfer(protocol.build_uniform_colors(rgb))
    return 1 if _run_sequence(device, transactions, args) else 0


def cmd_read_color(args: argparse.Namespace) -> int:
    device = find_l99()
    if not _require_cable(device, "reading colours"):
        return 1

    print(f"using {device.path}; reading per-key colour")
    with HidrawTransport(device.path, timeout_seconds=args.timeout) as transport:
        for tx in protocol.build_color_query_commands():
            attempts = protocol.SESSION_OPEN_RETRIES if tx.retry_until_ack else 1
            reply = None
            for attempt in range(1, attempts + 1):
                reply = _run_cable(transport, tx, args.debug, args.gap)
                if reply is None or _acked(tx, reply):
                    break
                if attempt < attempts:
                    time.sleep(protocol.RETRY_DELAY_SECONDS)
            if reply is not None and not _acked(tx, reply):
                print(f"{tx.name}: WARNING no ack, got {reply[:4].hex()}", file=sys.stderr)
                return 1

        blocks = []
        for i in range(protocol.COLOR_BLOCK_COUNT):
            block = transport.get_feature(protocol.REPORT_ID, protocol.PACKET_SIZE + 1)[1:]
            time.sleep(args.gap)
            if args.debug:
                print(f"block{i}: in ={block.hex()}")
            blocks.append(block)

    colors = protocol.parse_color_blocks(blocks)
    for key_id in protocol.KEY_IDS:
        r, g, b = colors.get(key_id, (0, 0, 0))
        row, col = key_id >> 4, key_id & 0x0F
        print(f"  key 0x{key_id:02X} (row {row}, col {col:2d}): #{r:02X}{g:02X}{b:02X}")
    return 0


def cmd_effect(args: argparse.Namespace) -> int:
    device = find_l99()
    if not _require_cable(device, "selecting effects"):
        return 1

    try:
        effect_id = int(args.effect, 0)
        rgb = protocol.parse_rgb(args.color) if args.color else (0xFF, 0x00, 0x00)
        blocks_args = dict(rgb=rgb, speed=args.speed, brightness=args.brightness)
        transactions = protocol.build_effect_transfer(effect_id, **blocks_args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    name = protocol.EFFECT_NAMES.get(effect_id, "unknown")
    print(f"using {device.path}; effect 0x{effect_id:02X} ({name}) "
          f"colour #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X} "
          f"speed {args.speed} brightness {args.brightness}")
    return 1 if _run_sequence(device, transactions, args) else 0


def cmd_rtc(args: argparse.Namespace) -> int:
    device = find_l99()
    now = datetime.now()

    if device.is_cable:
        print(f"using {device.path}; setting clock to {now:%Y-%m-%d %H:%M:%S}")
        transactions = protocol.build_rtc_transfer(now)
        return 1 if _run_sequence(device, transactions, args) else 0

    with HidrawTransport(device.path, timeout_seconds=args.timeout) as transport:
        transport.drain()
        for tx in protocol.build_dongle_handshake():
            _run_dongle(transport, tx, args.debug)
        rtc = protocol.Transaction(
            "rtc-set", protocol.build_dongle_rtc_packet(now), True, protocol.RTC_SET_ACK
        )
        _run_dongle(transport, rtc, args.debug)
    return 0


def cmd_send_hex(args: argparse.Namespace) -> int:
    device = find_l99()
    payload = protocol.parse_hex_packet(args.send_hex)
    print(f"using {device.path} ({'cable' if device.is_cable else 'dongle'}); "
          f"sending {len(payload)} bytes")

    with HidrawTransport(device.path, timeout_seconds=args.timeout) as transport:
        if device.is_cable:
            if len(payload) > protocol.PACKET_SIZE:
                print(f"error: packet is {len(payload)} bytes, max is "
                      f"{protocol.PACKET_SIZE}", file=sys.stderr)
                return 2
            body = payload.ljust(protocol.PACKET_SIZE, b"\x00")
            transport.set_feature(bytes([protocol.REPORT_ID]) + body)
            time.sleep(args.gap)
            reply = transport.get_feature(protocol.REPORT_ID, protocol.PACKET_SIZE + 1)[1:]
        else:
            if len(payload) > protocol.DONGLE_PACKET_SIZE:
                print(f"error: packet is {len(payload)} bytes, max is "
                      f"{protocol.DONGLE_PACKET_SIZE}", file=sys.stderr)
                return 2
            body = payload.ljust(protocol.DONGLE_PACKET_SIZE, b"\x00")
            transport.write(bytes([protocol.REPORT_ID]) + body)
            reply = transport.read_report(max_length=protocol.DONGLE_PACKET_SIZE)
        print(f"reply: {reply.hex()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--list", action="store_true", help="list hidraw devices and exit")
    parser.add_argument("--handshake", action="store_true", help="open and close a session")
    parser.add_argument("--color", metavar="RRGGBB", help="set every key to one colour")
    parser.add_argument("--read-color", action="store_true",
                        help="read back every key's current colour")
    parser.add_argument("--effect", metavar="ID",
                        help="select a built-in effect by id, e.g. 0x05 (see --list-effects)")
    parser.add_argument("--list-effects", action="store_true",
                        help="show the known effect ids and exit")
    parser.add_argument("--speed", type=int, default=protocol.EFFECT_SPEED_DEFAULT,
                        help="effect speed %(default)s (1=slowest, 5=fastest)")
    parser.add_argument("--brightness", type=int, default=protocol.EFFECT_BRIGHTNESS_MAX,
                        help="effect brightness (1..5, default %(default)s)")
    parser.add_argument("--rtc", action="store_true", help="set the keyboard's clock")
    parser.add_argument("--send-hex", metavar="HEX", help="send one raw packet and print the reply")
    parser.add_argument("--timeout", type=float, default=1.0, help="reply read timeout in seconds")
    parser.add_argument("--gap", type=float, default=protocol.PACKET_GAP_SECONDS,
                        help="seconds to wait between packets (default %(default)s); "
                             "0 makes multi-block transfers fail")
    parser.add_argument("--debug", action="store_true", help="print every packet in both directions")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.list:
            _print_devices()
            return 0
        if args.list_effects:
            for eid, ename in sorted(protocol.EFFECT_NAMES.items()):
                mark = "confirmed" if eid in protocol.EFFECT_CONFIRMED else "untested"
                print(f"  0x{eid:02X}  {ename:<18} {mark}")
            print("\nIds are the 1-based position in the vendor app's effect list.")
            return 0
        if args.handshake:
            return cmd_handshake(args)
        # --effect first: --color doubles as the effect's colour parameter.
        if args.effect:
            return cmd_effect(args)
        if args.color:
            return cmd_color(args)
        if args.read_color:
            return cmd_read_color(args)
        if args.rtc:
            return cmd_rtc(args)
        if args.send_hex:
            return cmd_send_hex(args)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except PermissionError as exc:
        print(f"error: {exc}\nno access to the hidraw node; add a udev rule or run as root",
              file=sys.stderr)
        return 2

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
