"""CLI for probing the AULA L99's vendor HID channel (0C45:800A / 05AC:024F).

Usage:
    python3 -m aula_l99_hacky.cli --list
    python3 -m aula_l99_hacky.cli --handshake
    python3 -m aula_l99_hacky.cli --rtc
    python3 -m aula_l99_hacky.cli --send-hex "06 84 00 00 01 00 80 00 ..."

`--send-hex` is the slot for testing a candidate command you pulled from your
own Wireshark/USBPcap capture of the official AULA driver: paste the exact
bytes of one HID report and see what the keyboard replies with. Requires
read/write access to the hidraw device (usually root, or a udev rule).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from . import protocol
from .device import HidrawTransport, enumerate_hidraw, find_l99


def _print_devices() -> None:
    for device in enumerate_hidraw():
        vid = f"{device.vendor_id:04x}" if device.vendor_id is not None else "????"
        pid = f"{device.product_id:04x}" if device.product_id is not None else "????"
        iface = device.interface_number if device.interface_number is not None else "?"
        print(f"{device.path}  vid={vid} pid={pid} iface={iface}  {device.name or ''}")


def _run_dongle_transaction(transport: HidrawTransport, tx: protocol.Transaction, debug: bool) -> bytes:
    outgoing = tx.outgoing.ljust(protocol.DONGLE_PACKET_SIZE, b"\x00")
    transport.write(outgoing)
    if debug:
        print(f"{tx.name}: out={outgoing.hex()}")
    reply = transport.read_report(max_length=protocol.DONGLE_PACKET_SIZE)
    print(f"{tx.name}: in={reply.hex()}")
    if tx.expected_reply is not None and reply != tx.expected_reply:
        print(f"{tx.name}: WARNING reply did not match the previously-confirmed value", file=sys.stderr)
    return reply


def _run_cable_transaction(transport: HidrawTransport, tx: protocol.Transaction, debug: bool) -> bytes:
    transport.set_feature(b"\x00" + tx.outgoing)
    if debug:
        print(f"{tx.name}: out={tx.outgoing.hex()}")
    reply = transport.get_feature(0, protocol.CABLE_PACKET_SIZE + 1)[1:]
    print(f"{tx.name}: in={reply.hex()}")
    return reply


def cmd_handshake(args: argparse.Namespace) -> int:
    device = find_l99()
    print(f"using {device.path} ({'cable' if device.is_cable else 'dongle'})")
    with HidrawTransport(device.path, timeout_seconds=args.timeout) as transport:
        if device.is_cable:
            for tx in protocol.build_cable_handshake():
                _run_cable_transaction(transport, tx, args.debug)
        else:
            transport.drain()
            for tx in protocol.build_dongle_handshake():
                _run_dongle_transaction(transport, tx, args.debug)
    return 0


def cmd_rtc(args: argparse.Namespace) -> int:
    device = find_l99()
    if device.is_cable:
        print("RTC-set as documented is the dongle/interrupt packet format; "
              "the cable path needs its own 64-byte time payload (see docs/research "
              "in the F75_Initializer prior art) — not yet wired up here.", file=sys.stderr)
        return 1

    when = datetime.now()
    with HidrawTransport(device.path, timeout_seconds=args.timeout) as transport:
        transport.drain()
        for tx in protocol.build_dongle_handshake():
            _run_dongle_transaction(transport, tx, args.debug)
        rtc_tx = protocol.Transaction("rtc-set", protocol.build_rtc_set_packet(when), protocol.RTC_SET_ACK)
        _run_dongle_transaction(transport, rtc_tx, args.debug)
    return 0


def cmd_send_hex(args: argparse.Namespace) -> int:
    device = find_l99()
    payload = protocol.parse_hex_packet(args.send_hex)
    print(f"using {device.path} ({'cable' if device.is_cable else 'dongle'}); sending {len(payload)} bytes")

    with HidrawTransport(device.path, timeout_seconds=args.timeout) as transport:
        if device.is_cable:
            transport.set_feature(payload if payload[0:1] == b"\x00" else b"\x00" + payload)
            reply = transport.get_feature(0, protocol.CABLE_PACKET_SIZE + 1)[1:]
        else:
            transport.write(payload.ljust(protocol.DONGLE_PACKET_SIZE, b"\x00"))
            reply = transport.read_report(max_length=64)
        print(f"reply: {reply.hex()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="list hidraw devices and exit")
    parser.add_argument("--handshake", action="store_true", help="run the session-init/query handshake")
    parser.add_argument("--rtc", action="store_true", help="run handshake then set the keyboard's clock")
    parser.add_argument("--send-hex", metavar="HEX", help="send one raw hex packet and print the reply")
    parser.add_argument("--timeout", type=float, default=1.0, help="reply read timeout in seconds")
    parser.add_argument("--debug", action="store_true", help="print outgoing bytes too")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.list:
        _print_devices()
        return 0
    if args.handshake:
        return cmd_handshake(args)
    if args.rtc:
        return cmd_rtc(args)
    if args.send_hex:
        return cmd_send_hex(args)

    build_parser().print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
