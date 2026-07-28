"""CLI for the AULA L99's touchscreen (EEEF:268A).

Usage:
    python3 -m aula_l99_screen.cli --list
    python3 -m aula_l99_screen.cli --convert picture.png -o picture.bin
    python3 -m aula_l99_screen.cli --describe picture.bin
    python3 -m aula_l99_screen.cli --send picture.png

This is the touchscreen, not the keyboard: a USB-serial device, unrelated to
the vendor HID protocol in aula_l99_hacky.

`--convert` is the trustworthy part: its output is byte-for-byte identical to
the vendor's own Image2Bin.exe for every image tested. `--send` writes those
bytes to the serial port, but the on-the-wire framing the panel expects has NOT
been established -- see the note it prints.
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


def cmd_send(args: argparse.Namespace) -> int:
    blob = _encode(args.send, args.width, args.height)
    print(f"payload: {protocol.describe(blob)}  ({len(blob)} bytes)")

    device = find_screen()
    print(f"writing to {device.path}")
    with SerialTransport(device.path) as transport:
        sent = transport.write(blob)
        reply = transport.read_reply()
    print(f"wrote {sent} bytes; panel replied: {reply.hex(' ') if reply else '(nothing)'}")

    print("\nnote: the framing the panel expects on the wire is not yet known.\n"
          "      The payload above matches the vendor's converter exactly, but\n"
          "      writing it raw has not been shown to update the display, so a\n"
          "      blank screen here is expected rather than a sign of a bad image.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--list", action="store_true", help="list USB serial devices and exit")
    parser.add_argument("--convert", metavar="IMAGE", help="convert an image to the panel's .bin")
    parser.add_argument("-o", "--output", metavar="FILE", help="output path for --convert")
    parser.add_argument("--describe", metavar="FILE", help="decode a .bin header and check its CRC")
    parser.add_argument("--send", metavar="IMAGE", help="convert and write to the panel")
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
        if args.send:
            return cmd_send(args)
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
