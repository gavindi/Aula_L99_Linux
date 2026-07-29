"""CLI for the AULA L99's touchscreen (EEEF:268A).

Usage:
    python3 -m aula_l99_screen.cli --list
    python3 -m aula_l99_screen.cli --convert picture.png -o picture.bin
    python3 -m aula_l99_screen.cli --describe picture.bin
    python3 -m aula_l99_screen.cli --upload picture.png
    python3 -m aula_l99_screen.cli --upload picture.png --target background
    python3 -m aula_l99_screen.cli --upload frame1.png frame2.png --target gif

This is the touchscreen, not the keyboard: a USB-serial device, unrelated to
the vendor HID protocol in aula_l99_hacky.

`--upload` writes an image to the panel's flash, confirmed working on real
hardware for both `--target photo-frame` (default) and `--target background`.
The panel may need a restart before it redraws from flash.

`--target gif` builds a from-scratch GIF from one or more images (one per
frame) and is confirmed working on real hardware as of 0.7.0, but only for
images using "safe" colors (max(R,G,B) exactly 0 or 255) -- anything else
needs dithering, which isn't understood well enough yet to encode. See
protocol.py's GIF_FLASH_BASE comment block and build_gif_blob() for the
full story, including why some images may fail with a "no large enough
solid run" error.
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


def _load_image(path: str, width: int, height: int):
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("error: Pillow is required to convert images (pip install pillow)")

    with Image.open(path) as image:
        image = image.convert("RGB")
        if image.size != (width, height):
            print(f"resizing {image.size[0]}x{image.size[1]} -> {width}x{height}")
            image = image.resize((width, height), Image.LANCZOS)
        return image


def _encode(path: str, width: int, height: int) -> bytes:
    image = _load_image(path, width, height)
    return protocol.build_image_file(image.tobytes(), width, height)


def _encode_gif_frame_pixels(path: str, width: int, height: int) -> list[tuple[int, int, int]]:
    image = _load_image(path, width, height)
    if hasattr(image, "get_flattened_data"):
        return list(image.get_flattened_data())
    return list(image.getdata())  # Pillow < 12


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


TARGET_ADDRESSES = {
    "photo-frame": protocol.PHOTO_FRAME_FLASH_BASE,
    "background": protocol.BACKGROUND_FLASH_BASE,
    "gif": protocol.GIF_FLASH_BASE,
}


def cmd_upload(args: argparse.Namespace) -> int:
    import time

    address = args.address if args.address is not None else TARGET_ADDRESSES[args.target]

    if args.target == "gif":
        frames = [_encode_gif_frame_pixels(path, args.width, args.height) for path in args.upload]
        blob = protocol.build_gif_blob(frames, args.width, args.height, delay=args.gif_delay)
        print(f"payload: {len(frames)} frame(s), {args.gif_delay} delay units  ({len(blob)} bytes)")
    else:
        if len(args.upload) != 1:
            raise SystemExit(
                f"error: --target {args.target} takes exactly one image, got {len(args.upload)} "
                f"(multiple images are only supported with --target gif)"
            )
        blob = _encode(args.upload[0], args.width, args.height)
        print(f"payload: {protocol.describe(blob)}  ({len(blob)} bytes)")

    packets = protocol.build_upload(blob, address)
    print(f"{len(packets)} packets to flash {address:#x}")

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
    parser.add_argument("--upload", metavar="IMAGE", nargs="+",
                        help="convert and upload to the panel's flash (the real path). "
                             "One image for --target photo-frame/background; one or more "
                             "images (one per frame) for --target gif")
    parser.add_argument("--target", choices=sorted(TARGET_ADDRESSES), default="photo-frame",
                        help="upload destination for --upload (default %(default)s)")
    parser.add_argument("--address", type=lambda v: int(v, 0), default=None,
                        help="flash address for --upload; overrides --target")
    parser.add_argument("--gif-delay", type=int, default=50,
                        help="inter-frame delay for --target gif, unit unconfirmed "
                             "(default %(default)s, matching every capture seen so far)")
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
