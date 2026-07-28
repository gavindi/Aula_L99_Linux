"""CLI for the AULA L99's touchscreen (EEEF:268A).

Usage:
    python3 -m aula_l99_screen.cli --list
    python3 -m aula_l99_screen.cli --convert picture.png -o picture.bin
    python3 -m aula_l99_screen.cli --describe picture.bin
    python3 -m aula_l99_screen.cli --upload picture.png

This is the touchscreen, not the keyboard: a USB-serial device, unrelated to
the vendor HID protocol in aula_l99_hacky.

`--upload` writes an image to the panel's flash and is confirmed working on
real hardware. The panel may need a restart before it redraws from flash.
"""
from __future__ import annotations

import argparse
import sys

from . import protocol
from .device import SerialTransport, enumerate_serial, find_screen


def _print_devices() -> None:
    found = False
    for device in enumerate_serial():
        vid = f"{device.vendor_id:04x}" if device.vendor_id is not None else "????"
        pid = f"{device.product_id:04x}" if device.product_id is not None else "????"
        tag = "  <- AULA L99 touchscreen" if device.is_screen else ""
        print(f"{device.path}  vid={vid} pid={pid}{tag}")
        found = True
    if not found:
        print("no USB serial devices found")


def _encode(path: str, width: int, height: int) -> bytes:
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("error: Pillow is required to convert images (pip install pillow)")

    with Image.open(path) as image:
        image = image.convert("RGB")
        if image.size != (width, height):
            print(f"resizing {image.size[0]}x{image.size[1]} -> {width}x{height}")
            image = image.resize((width, height), Image.LANCZOS)
        return protocol.build_image_file(image.tobytes(), width, height)


def cmd_convert(args: argparse.Namespace) -> int:
    blob = _encode(args.convert, args.width, args.height)
    out = args.output or (args.convert.rsplit(".", 1)[0] + ".bin")
    with open(out, "wb") as handle:
        handle.write(blob)
    print(f"{out}: {protocol.describe(blob)}  ({len(blob)} bytes)")
    return 0


def cmd_describe(args: argparse.Namespace) -> int:
    with open(args.describe, "rb") as handle:
        blob = handle.read()
    print(f"{args.describe}: {protocol.describe(blob)}  ({len(blob)} bytes)")
    return 0


def cmd_upload(args: argparse.Namespace) -> int:
    import time

    blob = _encode(args.upload, args.width, args.height)
    packets = protocol.build_upload(blob, args.address)
    print(f"payload: {protocol.describe(blob)}  ({len(blob)} bytes)")
    print(f"{len(packets)} packets to flash {args.address:#x}")

    device = find_screen()
    print(f"uploading to {device.path}\n")

    sent = acked = 0
    with SerialTransport(device.path) as transport:
        for i, packet in enumerate(packets):
            transport.write(packet)
            sent += 1
            reply = transport.read_reply()
            if protocol.is_ack(packet[4], reply):
                acked += 1
            elif not args.ignore_nak:
                print(f"\npacket {i} not acked (reply {reply.hex(' ') or 'none'}); stopping.\n"
                      f"Leaving the transfer incomplete can freeze the panel — power-cycle it.",
                      file=sys.stderr)
                return 1
            if i % 25 == 0:
                print(f"  {i}/{len(packets)} sent, {acked} acked")
            time.sleep(args.gap)

    print(f"\ndone: {sent} packets sent, {acked} acked")
    return 0 if acked == sent else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--list", action="store_true", help="list USB serial devices and exit")
    parser.add_argument("--convert", metavar="IMAGE", help="convert an image to the panel's .bin")
    parser.add_argument("-o", "--output", metavar="FILE", help="output path for --convert")
    parser.add_argument("--describe", metavar="FILE", help="decode a .bin header and check its CRC")
    parser.add_argument("--upload", metavar="IMAGE",
                        help="convert and upload to the panel's flash (the real path)")
    parser.add_argument("--address", type=lambda v: int(v, 0), default=protocol.FLASH_BASE,
                        help="flash address (default %(default)#x)")
    parser.add_argument("--gap", type=float, default=0.005,
                        help="seconds between packets (default %(default)s)")
    parser.add_argument("--ignore-nak", action="store_true",
                        help="keep going when a packet is not acked")
    parser.add_argument("--width", type=int, default=protocol.PANEL_WIDTH,
                        help="panel width (default %(default)s)")
    parser.add_argument("--height", type=int, default=protocol.PANEL_HEIGHT,
                        help="panel height (default %(default)s)")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.list:
            _print_devices()
            return 0
        if args.convert:
            return cmd_convert(args)
        if args.describe:
            return cmd_describe(args)
        if args.upload:
            return cmd_upload(args)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except PermissionError as exc:
        print(f"error: {exc}\nno access to the serial port; add yourself to the "
              f"'dialout' group", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
