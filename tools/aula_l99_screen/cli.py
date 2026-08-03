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
needs dithering, which the device's own algorithm isn't understood well
enough to reproduce. Pass `--dither` to run our own Floyd-Steinberg
dithering instead and lift that restriction -- CONFIRMED working on real
hardware, including the automatic raw-bitmap-mode fallback for oversized
content. See protocol.py's GIF_FLASH_BASE comment block and
build_gif_blob() for the full story, including why some images may fail
with a "no large enough solid run" error.
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


def _pixels_from_image(image) -> bytes:
    # Flat RGB888, the form protocol.build_gif_blob() works in natively --
    # tobytes() hands the buffer over whole, where getdata()/
    # get_flattened_data() built a Python tuple per pixel (~27x the memory,
    # and a per-pixel loop to match).
    return image.tobytes("raw", "RGB")


def _encode_gif_frame_pixels(path: str, width: int, height: int) -> bytes:
    return _pixels_from_image(_load_image(path, width, height))


def _evenly_spaced_indices(total: int, limit: int) -> list[int]:
    """Up to `limit` indices spread evenly over range(total) -- sampling
    across the whole source rather than truncating to its opening frames."""
    if limit <= 0 or total <= 0:
        return []
    if total <= limit:
        return list(range(total))
    return [i * total // limit for i in range(limit)]


GIF_EXTENSIONS = {".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def _gif_source_frames(path: str, width: int, height: int):
    """One (pixels, delay_centiseconds) pair per frame of an animated GIF.

    Each frame's own embedded delay is used directly -- GIF's native delay
    field is already in centiseconds, matching our best hypothesis for the
    wire format's delay field unit (see protocol.py's GIF_FLASH_BASE notes).
    """
    try:
        from PIL import Image, ImageSequence
    except ImportError:
        raise SystemExit("error: Pillow is required to read GIF frames (pip install pillow)")

    frames = []
    delays = []
    with Image.open(path) as im:
        total = getattr(im, "n_frames", 1)
        # The TOC's frame-count field is one byte, so a long source has to be
        # sampled down or the encode fails outright at the very end. Deciding
        # which frames to keep up front also means only those get converted
        # and resized, which is where the time goes.
        keep = _evenly_spaced_indices(total, protocol.MAX_GIF_FRAMES)
        if len(keep) < total:
            print(f"sampling {len(keep)} of {total} frames "
                  f"(the panel's format carries at most {protocol.MAX_GIF_FRAMES})")
        keep = set(keep)
        for index, frame in enumerate(ImageSequence.Iterator(im)):
            if index not in keep:
                continue
            rgb = frame.convert("RGB")
            if rgb.size != (width, height):
                rgb = rgb.resize((width, height), Image.LANCZOS)
            frames.append(_pixels_from_image(rgb))
            delay_ms = frame.info.get("duration", 500)
            delays.append(max(1, round(delay_ms / 10)))
    if not frames:
        raise SystemExit(f"error: {path} has no frames")
    return frames, delays


def _video_source_frames(path: str, width: int, height: int,
                          fps: float | None, max_frames: int | None):
    """One (pixels, delay_centiseconds) pair per extracted video frame.

    Shells out to ffmpeg (no new Python dependency). fps and/or max_frames
    must be given by the caller -- there's no established safe default
    frame count for this panel, so we refuse to guess one silently.
    """
    import pathlib
    import shutil
    import subprocess
    import tempfile

    from PIL import Image

    if shutil.which("ffmpeg") is None:
        raise SystemExit("error: ffmpeg is required to extract frames from a video (not found on PATH)")

    if fps is None:
        if shutil.which("ffprobe") is None:
            raise SystemExit("error: ffprobe is required to derive --fps from --max-frames (not found on PATH)")
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"error: ffprobe failed on {path}:\n{exc.stderr}")
        try:
            duration = float(result.stdout.strip())
        except ValueError:
            raise SystemExit(f"error: ffprobe didn't report a usable duration for {path}")
        if duration <= 0:
            raise SystemExit(f"error: ffprobe reported a non-positive duration for {path}")
        fps = max_frames / duration
        print(f"deriving --fps {fps:.3f} from --max-frames {max_frames} and duration {duration:.2f}s")

    with tempfile.TemporaryDirectory(prefix="aula_l99_video_") as tmpdir:
        pattern = str(pathlib.Path(tmpdir) / "frame_%05d.png")
        cmd = ["ffmpeg", "-y", "-i", path, "-vf", f"fps={fps},scale={width}:{height}", pattern]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"error: ffmpeg failed on {path}:\n{exc.stderr}")

        frame_paths = sorted(pathlib.Path(tmpdir).glob("frame_*.png"))
        if max_frames is not None:
            frame_paths = frame_paths[:max_frames]
        if not frame_paths:
            raise SystemExit(f"error: ffmpeg produced no frames from {path} at fps={fps}")

        delay_cs = max(1, round(100 / fps))
        frames = []
        for frame_path in frame_paths:
            with Image.open(frame_path) as im:
                frames.append(_pixels_from_image(im.convert("RGB")))
    return frames, [delay_cs] * len(frames)


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
        import pathlib

        if len(args.upload) == 1:
            ext = pathlib.Path(args.upload[0]).suffix.lower()
        else:
            ext = None

        if ext in GIF_EXTENSIONS:
            frames, source_delays = _gif_source_frames(args.upload[0], args.width, args.height)
        elif ext in VIDEO_EXTENSIONS:
            if args.fps is None and args.max_frames is None:
                raise SystemExit(
                    "error: extracting frames from a video requires --fps or --max-frames "
                    "(no safe default frame count is established for this panel)"
                )
            frames, source_delays = _video_source_frames(
                args.upload[0], args.width, args.height, args.fps, args.max_frames
            )
        else:
            frames = [_encode_gif_frame_pixels(path, args.width, args.height) for path in args.upload]
            source_delays = [50] * len(frames)

        if args.gif_delay is not None:
            delays = [args.gif_delay] * len(frames)
        else:
            delays = source_delays
            if len(set(delays)) > 1:
                raise SystemExit(
                    f"error: extracted per-frame delays aren't uniform ({delays}) -- the "
                    f"panel is confirmed to reject a GIF whose frames have different delay "
                    f"values (it plays the fallback animation instead of the upload). Pass "
                    f"--gif-delay N to force one uniform value for every frame."
                )

        blob = protocol.build_gif_blob(frames, args.width, args.height, delay=delays,
                                       dither=args.dither)
        print(f"payload: {len(frames)} frame(s), delays={delays}  ({len(blob)} bytes)")
        if len(blob) > protocol.VENDOR_MAX_GIF_BLOB_BYTES:
            # Warning, not a refusal: how much flash is mapped above the GIF
            # base is unverified, so this only reports that the upload is
            # larger than the vendor app could ever have written.
            print(f"warning: {len(blob) / 1e6:.1f} MB exceeds the "
                  f"{protocol.VENDOR_MAX_GIF_BLOB_BYTES / 1e6:.1f} MB ceiling implied by "
                  f"the vendor's own frame and content-length limits -- dithered frames "
                  f"encode much larger than its own do, and the flash beyond that point "
                  f"is unverified")
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
    parser.add_argument("--upload", metavar="PATH", nargs="+",
                        help="convert and upload to the panel's flash (the real path). "
                             "One image for --target photo-frame/background. For --target "
                             "gif: one or more images (one per frame), OR a single animated "
                             ".gif (all its frames are used, each keeping its own embedded "
                             "delay), OR a single video file (requires --fps or --max-frames)")
    parser.add_argument("--target", choices=sorted(TARGET_ADDRESSES), default="photo-frame",
                        help="upload destination for --upload (default %(default)s)")
    parser.add_argument("--address", type=lambda v: int(v, 0), default=None,
                        help="flash address for --upload; overrides --target")
    parser.add_argument("--gif-delay", type=int, default=None,
                        help="inter-frame delay for --target gif, unit unconfirmed. "
                             "Overrides every frame's delay uniformly, including a source "
                             "GIF's own embedded per-frame delays or a video's computed "
                             "delay. Default: 50 for plain images, the source GIF's own "
                             "delays for a .gif input, or derived from --fps for a video")
    parser.add_argument("--fps", type=float, default=None,
                        help="frames per second to sample when --upload is a video file")
    parser.add_argument("--max-frames", type=int, default=None,
                        help="cap the number of frames extracted from a video file "
                             "(also derives --fps from the video's duration if --fps isn't given)")
    parser.add_argument("--dither", action="store_true",
                        help="for --target gif: apply Floyd-Steinberg dithering onto the "
                             "device's fixed color ramp, allowing images with non-safe "
                             "colors to be encoded instead of rejected. Default: off, "
                             "matching the original safe-colors-only behavior confirmed on "
                             "real hardware. This dithering path is now CONFIRMED working "
                             "on real hardware too, including the automatic raw-bitmap-mode "
                             "fallback for oversized content")
    parser.add_argument("--gap", type=float, default=0.0,
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
