"""Pure DSP + ALSA device listing for the Music tab's 17-band spectrum.

Everything in here is deliberately free of Qt and of hardware I/O (except
`list_capture_devices()`, which shells out to `arecord -l`), so the maths is
unit-testable off the GUI thread. The spectrum feed the panel's analyser
consumes carries up to 23 band levels (see aula_l99_hacky's OP_AUDIO, 0x78);
the panel renders the low 17 of them, which is exactly the number computed
here -- a 17-point spectrum maps 1:1 onto the on-screen bars.

The FFT is a per-band Goertzel recurrence rather than numpy: 17 bands over a
2048-sample frame at ~21 frames/s is a few hundred thousand scalar ops per
second, which pure Python does comfortably, and it keeps numpy out of the
package build (package.sh's clean venv installs only PySide6_Essentials,
Pillow and defusedxml).

Levels are absolute, dB-scaled against 16-bit full scale with a floor
(DB_FLOOR below maps to 0, full scale to 100). That is the vendor feed's own
semantics -- its levels are real magnitudes relative to the block's scale
byte -- so the panel's bars move with actual loudness rather than being
peak-normalised per frame.
"""
from __future__ import annotations

import json
import math
import re
import struct
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

# The panel renders wire bands 0..16 (17 segments) and ignores 17..22 -- see
# tools/aula_l99_hacky/re_notes/audio_spectrum_block.md. Keeping this in step
# with AUDIO_BAND_COUNT there is deliberate: the wire block is zero-padded
# from 17 to 23 by build_audio_blocks, and the two counts are the two ends of
# that same transfer.
SPECTRUM_BAND_COUNT = 17

# arecord is told to hand over mono S16_LE. 48 kHz is a safe universal rate
# for the capture devices this project targets (USB audio interfaces, the
# HD-Audio codec); plughw performs the conversion if a device only offers
# something else.
SAMPLE_RATE = 48000
SAMPLE_WIDTH = 2  # S16_LE

# One Goertzel frame is one spectrum frame. 2048 samples at 48 kHz is ~42.7ms,
# which paces the loop at roughly the vendor app's ~21 frames/s without any
# extra timing being needed.
CHUNK_SAMPLES = 2048

# Log-spaced band range. The vendor's own band edges are unknown; these are
# simply a sane 17-bar audio analyser span.
SPECTRUM_MIN_FREQ = 30.0
SPECTRUM_MAX_FREQ = 16000.0

# dB below full scale that maps to level 0. A quieter-than-this band reads as
# a silent bar rather than a hair of level.
DB_FLOOR = -60.0


@dataclass(frozen=True)
class CaptureDevice:
    """One capture source, ready to build a subprocess argv from.

    `target` is `-D`'s ALSA argument (`plughw:N,M`) for `kind == "alsa"`, or a
    PipeWire `object.serial` (as a string, for `--target`) for
    `kind == "pipewire"`.
    """

    label: str
    target: str
    kind: str = "alsa"


# A `arecord -l` device line: `card 1: AG06AG03 [AG06/AG03], device 0: USB
# Audio [USB Audio]`. The bracketed names are the human-readable ones; the
# pre-bracket names are the ALSA config names.
_DEVICE_LINE = re.compile(
    r"^card\s+(\d+):\s+.*?\[([^\]]*)\].*?,\s*device\s+(\d+):\s+.*?\[([^\]]*)\]"
)


def parse_arecord_devices(text: str) -> list[CaptureDevice]:
    """Parse `arecord -l` output into CaptureDevice entries.

    Skips non-device lines (the `**** List of CAPTURE Hardware Devices ****`
    header, subdevice listings, blank lines). Order follows the output.
    """
    devices: list[CaptureDevice] = []
    for line in text.splitlines():
        match = _DEVICE_LINE.match(line.strip())
        if match is None:
            continue
        card, card_name, device, device_name = match.groups()
        label = f"{card_name} {device_name}".strip() or f"card {card}, device {device}"
        devices.append(
            CaptureDevice(label=label, target=f"plughw:{card},{device}")
        )
    return devices


def list_capture_devices() -> list[CaptureDevice]:
    """Run `arecord -l` and parse it.

    Raises OSError if arecord is missing or will not run, so the caller can
    surface that as a user-visible message rather than an empty list.
    """
    try:
        output = subprocess.run(
            ["arecord", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except FileNotFoundError as exc:
        raise OSError("arecord not found on PATH; cannot list audio devices") from exc
    except subprocess.TimeoutExpired as exc:
        raise OSError("arecord -l timed out") from exc
    return parse_arecord_devices(output)


def arecord_command(plughw: str, rate: int = SAMPLE_RATE) -> list[str]:
    """argv for a raw mono S16_LE capture from `plughw` on stdout.

    `-t raw` gives a bare PCM stream with no WAV header; the worker reads
    fixed-size chunks of it. `plughw` rather than `hw` so sample-rate/format
    conversion happens on the ALSA side when the device does not natively
    offer 48 kHz mono S16_LE.
    """
    return [
        "arecord",
        "-D", plughw,
        "-f", "S16_LE",
        "-r", str(rate),
        "-c", "1",
        "-t", "raw",
    ]


def parse_pipewire_devices(nodes: list[dict]) -> list[CaptureDevice]:
    """Loopback and per-application entries from `pw-dump`'s parsed object list.

    `pw-dump` dumps every PipeWire object (nodes, ports, links, devices,
    clients, ...); only entries of type "PipeWire:Interface:Node" are
    considered here.

    `Audio/Sink` nodes are playback devices (speakers, HDMI, USB interfaces);
    targeting one with `pw-record --target` captures its monitor, i.e.
    whatever is currently playing out of it -- a loopback source. Nothing in
    PipeWire calls this a "monitor" node the way PulseAudio does: it's the
    same sink node PipeWire already lists, captured instead of played.

    `Stream/Output/Audio` nodes are transient, one per actively-playing
    application; targeting one captures only that app's audio, isolated from
    anything else on the system. They vanish when the app stops playing, so
    this list is only as fresh as the last refresh.
    """
    devices: list[CaptureDevice] = []
    for node in nodes:
        if node.get("type") != "PipeWire:Interface:Node":
            continue
        props = (node.get("info") or {}).get("props") or {}
        media_class = props.get("media.class")
        serial = props.get("object.serial")
        if serial is None:
            continue
        target = str(serial)
        if media_class == "Audio/Sink":
            name = (
                props.get("node.description")
                or props.get("node.nick")
                or props.get("node.name")
                or target
            )
            devices.append(
                CaptureDevice(label=f"Loopback: {name}", target=target, kind="pipewire")
            )
        elif media_class == "Stream/Output/Audio":
            app_name = props.get("application.name") or props.get("node.name") or target
            title = props.get("media.title") or props.get("media.name")
            label = f"App: {app_name}"
            if title and title not in ("playback", app_name):
                label += f" – {title}"
            devices.append(CaptureDevice(label=label, target=target, kind="pipewire"))
    return devices


def list_pipewire_devices() -> list[CaptureDevice]:
    """Run `pw-dump` and parse it into loopback/application capture entries.

    Raises OSError if pw-dump is missing, will not run, or returns output
    that doesn't parse as JSON, so the caller can fall back to ALSA-only
    listing rather than surface this as a fatal error.
    """
    try:
        output = subprocess.run(
            ["pw-dump"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout
    except FileNotFoundError as exc:
        raise OSError("pw-dump not found on PATH; cannot list PipeWire sources") from exc
    except subprocess.TimeoutExpired as exc:
        raise OSError("pw-dump timed out") from exc
    try:
        nodes = json.loads(output)
    except json.JSONDecodeError as exc:
        raise OSError("pw-dump output was not valid JSON") from exc
    return parse_pipewire_devices(nodes)


def list_all_devices() -> list[CaptureDevice]:
    """ALSA hardware devices plus PipeWire loopback/application sources.

    ALSA listing failures propagate (arecord is required for the tab to be
    useful at all); PipeWire listing failures are swallowed so a system
    without PipeWire -- or a transient pw-dump hiccup -- just falls back to
    the ALSA-only list instead of blanking the whole combo.
    """
    devices = list_capture_devices()
    try:
        devices += list_pipewire_devices()
    except OSError:
        pass
    return devices


def pw_record_command(target: str, rate: int = SAMPLE_RATE) -> list[str]:
    """argv for a raw mono S16_LE capture from a PipeWire node on stdout.

    `--target` is the node's `object.serial`; PipeWire links the capture
    stream to it directly -- to a sink's monitor ports for a loopback target,
    or straight to an application stream's output for a per-app target. `-a`
    (raw) gives a bare PCM stream with no container header, matching
    `arecord`'s `-t raw`; `-` writes it to stdout.
    """
    return [
        "pw-record",
        "--target", target,
        "--rate", str(rate),
        "--channels", "1",
        "--format", "s16",
        "--media-category", "Capture",
        "--raw",
        "-",
    ]


def band_frequencies(
    count: int = SPECTRUM_BAND_COUNT,
    low: float = SPECTRUM_MIN_FREQ,
    high: float = SPECTRUM_MAX_FREQ,
) -> list[float]:
    """`count` frequencies logarithmically spaced across `low`..`high`."""
    if count < 1:
        return []
    if count == 1:
        return [high]
    ratio = (high / low) ** (1.0 / (count - 1))
    freqs = [low * ratio ** i for i in range(count)]
    freqs[-1] = high  # ratio**count-1 can land a few ulps short of `high`
    return freqs


def decode_pcm(data: bytes) -> list[int]:
    """Mono S16_LE samples from a raw PCM chunk, little-endian."""
    count = len(data) // SAMPLE_WIDTH
    return list(struct.unpack(f"<{count}h", data[: count * SAMPLE_WIDTH]))


# Coherent gain of the Hann window used below: a full-scale sine's measured
# amplitude comes back scaled by mean(window) = 0.5, so amplitude normalisation
# divides by this as well as by n/2.
HANN_COHERENT_GAIN = 0.5


def _hann_window(n: int) -> list[float]:
    """One Hann window for an n-sample frame, precomputed once per frame."""
    if n == 0:
        return []
    return [0.5 * (1.0 - math.cos(2.0 * math.pi * i / (n - 1))) for i in range(n)]


def _windowed(samples: list[int]) -> list[float]:
    n = len(samples)
    window = _hann_window(n)
    return [sample * window[i] for i, sample in enumerate(samples)]


def goertzel_amplitude(samples: Sequence[float], rate: int, freq: float,
                       coherent_gain: float = 1.0) -> float:
    """Amplitude of one frequency in `samples`, 0..~32767.

    The Goertzel recurrence computes the DFT bin at exactly `freq` (k need not
    be an integer bin of the frame). A full-scale sine at `freq` returns
    ~32767; silence returns ~0. The normalisation divides the raw DFT
    magnitude by n/2 (and by the window's coherent gain when one has been
    applied), which is the factor relating it to sine amplitude.
    """
    n = len(samples)
    if n == 0:
        return 0.0
    k = freq * n / rate
    omega = 2.0 * math.pi * k / n
    coeff = 2.0 * math.cos(omega)
    s_prev = 0.0
    s_prev2 = 0.0
    for sample in samples:
        s = sample + coeff * s_prev - s_prev2
        s_prev2 = s_prev
        s_prev = s
    power = s_prev2 * s_prev2 + s_prev * s_prev - coeff * s_prev * s_prev2
    gain = coherent_gain if coherent_gain > 0 else 1.0
    return 2.0 * math.sqrt(max(power, 0.0)) / (n * gain)


def levels_from_samples(
    samples: list[int],
    rate: int = SAMPLE_RATE,
    bands: list[float] | None = None,
    floor_db: float = DB_FLOOR,
) -> list[int]:
    """One frame of 0..100 band levels from raw samples, low frequency first.

    The frame is Hann-windowed once, then each band's amplitude is converted
    to dB against 16-bit full scale and mapped linearly across
    `floor_db`..0 dB to 0..100, clamped. A silent frame is all zeroes.
    """
    if bands is None:
        bands = band_frequencies()
    windowed = _windowed(samples)
    levels: list[int] = []
    for freq in bands:
        amplitude = goertzel_amplitude(
            windowed, rate, freq, coherent_gain=HANN_COHERENT_GAIN)
        db = 20.0 * math.log10(amplitude / 32768.0) if amplitude > 0 else floor_db
        level = 100.0 * (db - floor_db) / (0.0 - floor_db)
        levels.append(int(max(0.0, min(100.0, level))))
    return levels


def levels_from_pcm(
    data: bytes,
    rate: int = SAMPLE_RATE,
    bands: list[float] | None = None,
) -> list[int]:
    """levels_from_samples() over a raw mono S16_LE chunk."""
    return levels_from_samples(decode_pcm(data), rate=rate, bands=bands)
