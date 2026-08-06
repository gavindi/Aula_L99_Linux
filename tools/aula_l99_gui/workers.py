"""Background-thread workers wrapping the keyboard/screen device I/O, plus a
generic one for CPU-bound work (currently: GIF frame decode + dithering).

The device-I/O workers reimplement the transaction-running and
packet-sending loops from each tool's cli.py (aula_l99_hacky/cli.py's
_run_cable/_run_sequence and aula_l99_screen/cli.py's cmd_upload send loop)
against the public protocol.py/device.py API, emitting Qt signals instead of
printing, so the GUI thread never blocks on hidraw feature-report or serial
I/O.
"""
from __future__ import annotations

import subprocess
import time
from datetime import datetime
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

from . import audio_spectrum
from aula_l99_hacky import protocol as kb_protocol
from aula_l99_hacky.device import HidrawTransport
from aula_l99_screen import protocol as screen_protocol
from aula_l99_screen.device import SerialTransport


# Intra-frame packet gap for the colour stream, well under
# kb_protocol.PACKET_GAP_SECONDS: a frame is 12 packets, so 10ms apiece would
# take twice the vendor's whole 58.7ms frame period. The capture left ~2.8ms
# between a frame's data blocks (re_notes/color_stream.md), and 2ms was already
# enough on the test unit for the one-shot paths.
STREAM_GAP_SECONDS = 0.003

# Only every Nth frame goes to the GUI's preview overlay. The stream itself
# runs at ~17 frames/s; repainting the layout image that often buys nothing a
# third of it doesn't.
PREVIEW_EVERY_N_FRAMES = 3


def start_worker(worker: QObject) -> QThread:
    """Move `worker` onto a new QThread and start it.

    `worker.finished` only means the *work* is done -- the thread's event
    loop hasn't been told to quit yet at that point, let alone actually
    stopped. Caller must keep a reference to both `worker` and the
    returned thread alive until `thread.finished` fires (not
    `worker.finished`): that's the only signal Qt guarantees means the
    thread has actually stopped running. Dropping the Python reference to
    a QThread that's still alive lets it get garbage-collected while
    running, which Qt treats as fatal ("QThread: Destroyed while thread
    ... is still running") and aborts the process.
    """
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread


class KeyboardWorker(QObject):
    """Runs a list of kb_protocol.Transaction over HidrawTransport -- mirrors
    cli.py's _run_cable/_run_dongle/_run_sequence but signal-driven.

    Cable path: 64-byte feature reports (set_feature/get_feature, acked via
    the ACK flag). Dongle path: 32-byte interrupt reports (write/read_report),
    replies compared with protocol.dongle_replies_match() so the per-device
    version byte (and its checksum byte) don't count as a mismatch.
    """

    progress = Signal(int, int, str, bool)  # index, total, name, acked
    finished = Signal(bool, str)  # success, message

    def __init__(self, device_path: str, transactions: list,
                 timeout: float = 1.0, gap: float = kb_protocol.PACKET_GAP_SECONDS,
                 dongle: bool = False):
        super().__init__()
        self._device_path = device_path
        self._transactions = transactions
        self._timeout = timeout
        self._gap = gap
        self._dongle = dongle

    @Slot()
    def run(self) -> None:
        try:
            failures = 0
            total = len(self._transactions)
            with HidrawTransport(self._device_path, timeout_seconds=self._timeout) as transport:
                for i, tx in enumerate(self._transactions):
                    attempts = kb_protocol.SESSION_OPEN_RETRIES if tx.retry_until_ack else 1
                    acked = True
                    for attempt in range(1, attempts + 1):
                        if self._dongle:
                            transport.write(
                                bytes([kb_protocol.REPORT_ID])
                                + tx.outgoing.ljust(kb_protocol.DONGLE_PACKET_SIZE, b"\x00"))
                            time.sleep(self._gap)
                            if tx.expect_reply:
                                reply = transport.read_report(
                                    max_length=kb_protocol.DONGLE_PACKET_SIZE)
                                time.sleep(self._gap)
                                acked = (
                                    reply is not None
                                    and (
                                        tx.expected_reply is None
                                        or kb_protocol.dongle_replies_match(
                                            reply, tx.expected_reply)
                                    )
                                )
                            else:
                                acked = True
                        else:
                            transport.set_feature(bytes([kb_protocol.REPORT_ID]) + tx.outgoing)
                            time.sleep(self._gap)
                            if tx.expect_reply:
                                reply = transport.get_feature(
                                    kb_protocol.REPORT_ID, kb_protocol.PACKET_SIZE + 1)[1:]
                                time.sleep(self._gap)
                                acked = _is_acked(tx, reply)
                            else:
                                acked = True
                        if acked or attempt == attempts:
                            break
                        time.sleep(kb_protocol.RETRY_DELAY_SECONDS)
                    if tx.expect_reply and not acked:
                        failures += 1
                    self.progress.emit(i, total, tx.name, acked)
            self.finished.emit(
                failures == 0,
                "ok" if failures == 0 else f"{failures} transaction(s) not acked",
            )
        except (FileNotFoundError, PermissionError, TimeoutError, OSError) as exc:
            self.finished.emit(False, str(exc))


class ColorStreamWorker(QObject):
    """Drives the realtime colour stream (opcode 0x20) in a loop until stopped
    -- the animation path, where KeyboardWorker is the one-shot path.

    Three things make it a different shape from KeyboardWorker rather than a
    flag on it:

    - The transport stays open for the whole animation. Reopening it per frame
      could not keep up with the vendor app's ~17 frames/s, and would give the
      Keyboard tab's colour poll a gap to slip into on every single frame.
    - The frames aren't known up front: `frame_fn(elapsed_seconds)` computes
      each one as it goes. It runs on *this* thread, so it must be pure -- no
      widget access, no shared mutable state.
    - Nothing is retried. A frame that misses its ack is stale
      STREAM_FRAME_SECONDS later, so resending it would push every later frame
      back rather than fix anything; the loop just carries on to the next one.
    """

    frame = Signal(object)  # colors dict, for the GUI's preview overlay
    finished = Signal(bool, str)

    def __init__(self, device_path: str, frame_fn: Callable[[float], dict],
                 period: float = kb_protocol.STREAM_FRAME_SECONDS,
                 gap: float = STREAM_GAP_SECONDS, timeout: float = 1.0,
                 preview_every: int = PREVIEW_EVERY_N_FRAMES):
        super().__init__()
        self._device_path = device_path
        self._frame_fn = frame_fn
        self._period = period
        self._gap = gap
        self._timeout = timeout
        self._preview_every = max(preview_every, 1)
        self._stop = False

    def stop(self) -> None:
        """Ask the loop to finish after the frame it is on.

        Called straight from the GUI thread rather than through a queued
        signal: this worker's thread is inside `run()` for the whole animation
        and never returns to its event loop, so a queued slot would not be
        delivered until the loop had already ended. A lone bool assignment is
        safe to do that way; anything more would not be.
        """
        self._stop = True

    @Slot()
    def run(self) -> None:
        try:
            frames = late = 0
            started = time.monotonic()
            with HidrawTransport(self._device_path, timeout_seconds=self._timeout) as transport:
                while not self._stop:
                    frame_started = time.monotonic()
                    colors = self._frame_fn(frame_started - started)
                    for tx in kb_protocol.build_stream_frame(colors):
                        transport.set_feature(bytes([kb_protocol.REPORT_ID]) + tx.outgoing)
                        time.sleep(self._gap)
                        if tx.expect_reply:
                            transport.get_feature(
                                kb_protocol.REPORT_ID, kb_protocol.PACKET_SIZE + 1)
                            time.sleep(self._gap)
                    frames += 1
                    if frames % self._preview_every == 0:
                        self.frame.emit(colors)
                    remaining = self._period - (time.monotonic() - frame_started)
                    if remaining > 0:
                        time.sleep(remaining)
                    else:
                        late += 1
            message = f"stream stopped after {frames} frames"
            if late:
                message += f" ({late} over the {self._period * 1000:.0f}ms frame budget)"
            self.finished.emit(True, message)
        except (FileNotFoundError, PermissionError, TimeoutError, OSError) as exc:
            self.finished.emit(False, str(exc))


class MonitorStreamWorker(QObject):
    """Sends the touchscreen's CPU/GPU and weather readout every `period`
    seconds until stopped -- the live-system-monitor companion to
    KeyboardWorker's one-shot RTC write (opcode 0x28; see
    re_notes/system_monitor_block.md).

    Same shape as ColorStreamWorker rather than KeyboardWorker for the same
    reasons as the colour stream: the transport stays open for the whole run
    so the device is only ever claimed for these sends, `load_fn` computes
    each frame as it goes, and nothing is retried -- a send that misses its
    ack is stale `period` seconds later anyway, so resending would just push
    the next one back.

    `load_fn` is the stats source: a no-arg callable returning a
    kb_protocol.MonitorData. It runs on *this* thread, so it must be pure --
    no widget access, no shared mutable state. All-zero fields are the vendor
    app's "nothing to report", so a load-only source just leaves the
    temperatures and weather at their defaults. `view` is byte 1 of the RTC
    block, which the panel ignores for values of 0 and otherwise routes to its
    real-time readout frame (>= 1).
    """

    finished = Signal(bool, str)
    sent = Signal(int, int)  # cpu_load, gpu_load of the most recent send

    def __init__(self, device_path: str,
                 load_fn: Callable[[], kb_protocol.MonitorData],
                 period: float = 5.0, view: int = 1,
                 gap: float = kb_protocol.PACKET_GAP_SECONDS,
                 timeout: float = 1.0):
        super().__init__()
        self._device_path = device_path
        self._load_fn = load_fn
        self._period = period
        self._view = view
        self._gap = gap
        self._timeout = timeout
        self._stop = False

    def stop(self) -> None:
        """Ask the loop to finish after the send it is on.

        Called straight from the GUI thread rather than through a queued
        signal: this worker's thread is inside `run()` for the whole session
        and never returns to its event loop, so a queued slot would not be
        delivered until the loop had already ended. A lone bool assignment is
        safe to do that way; anything more would not be.
        """
        self._stop = True

    @Slot()
    def run(self) -> None:
        try:
            sends = late = failures = 0
            started = time.monotonic()
            with HidrawTransport(self._device_path, timeout_seconds=self._timeout) as transport:
                while not self._stop:
                    frame_started = time.monotonic()
                    monitor = self._load_fn()
                    for tx in kb_protocol.build_rtc_transfer(
                            datetime.now(), monitor, self._view):
                        transport.set_feature(bytes([kb_protocol.REPORT_ID]) + tx.outgoing)
                        time.sleep(self._gap)
                        if tx.expect_reply:
                            reply = transport.get_feature(
                                kb_protocol.REPORT_ID, kb_protocol.PACKET_SIZE + 1)[1:]
                            time.sleep(self._gap)
                            if not _is_acked(tx, reply):
                                failures += 1
                    sends += 1
                    self.sent.emit(monitor.cpu_load, monitor.gpu_load)
                    remaining = self._period - (time.monotonic() - frame_started)
                    if remaining <= 0:
                        late += 1
                        continue
                    # Sliced so stop() is honoured within ~50ms even on a
                    # long period; the whole 5s would make the GUI's stop
                    # button and shutdown block for that long otherwise.
                    while remaining > 0 and not self._stop:
                        time.sleep(min(0.05, remaining))
                        remaining -= 0.05
            message = f"monitor stream stopped after {sends} send(s)"
            if failures:
                message += f" ({failures} not acked)"
            if late:
                message += f" ({late} over the {self._period:g}s period)"
            self.finished.emit(True, message)
        except (FileNotFoundError, PermissionError, TimeoutError, OSError) as exc:
            self.finished.emit(False, str(exc))


class AudioSpectrumWorker(QObject):
    """Streams a live spectrum to the keyboard's audio feed (opcode 0x78).

    Captures raw mono S16_LE PCM from an `arecord` subprocess on *this* thread,
    computes one frame of band levels per chunk via `level_fn` (a pure
    callable, no widget access), and sends each frame with
    kb_protocol.build_audio_frame() until stopped.

    Same shape as ColorStreamWorker/MonitorStreamWorker for the same reasons:
    the transport stays open for the whole run so the device is only ever
    claimed for these sends, and nothing is retried -- a frame that misses its
    ack is stale AUDIO_FRAME_SECONDS later, so resending would just push the
    next one back.

    The frame cadence comes from the chunk read: a CHUNK_SAMPLES-sized read
    from a 48 kHz stream blocks ~42.7ms, which is close to the vendor's
    0.047s frame period, so the loop is naturally paced and the extra sleep is
    just to keep from outpacing that budget when the send is unusually fast.

    `arecord_cmd` is the argv for a raw capture on stdout (see
    audio_spectrum.arecord_command). The subprocess is owned and reaped here;
    stop() asks it to terminate so the worker thread's blocking read returns
    instead of sitting on a live pipe.
    """

    frame = Signal(object)  # list[int] of band levels, for the tab's preview
    finished = Signal(bool, str)

    def __init__(self, device_path: str, arecord_cmd: list[str],
                 level_fn: Callable[[bytes], list[int]],
                 chunk_bytes: int = 4096,
                 period: float = kb_protocol.AUDIO_FRAME_SECONDS,
                 gap: float = kb_protocol.PACKET_GAP_SECONDS,
                 timeout: float = 1.0,
                 rhythm: int = kb_protocol.AUDIO_RHYTHM_DEFAULT,
                 background_mode: int = kb_protocol.AUDIO_BACKGROUND_MODE_DEFAULT,
                 amplitude: int = kb_protocol.AUDIO_AMPLITUDE_DEFAULT,
                 background_brightness: int = kb_protocol.AUDIO_BACKGROUND_BRIGHTNESS_DEFAULT):
        super().__init__()
        self._device_path = device_path
        self._arecord_cmd = arecord_cmd
        self._level_fn = level_fn
        self._chunk_bytes = chunk_bytes
        self._period = period
        self._gap = gap
        self._timeout = timeout
        # The Music tab's four controls as one immutable snapshot rather than
        # four attributes, so the GUI thread can swap in new values with a
        # single assignment -- the same cross-thread model as `stop()`'s
        # `_stop` flag below. `run()` reads the snapshot between PCM chunks
        # (~43ms apart), so a change applies from the next frame on.
        self._music = (rhythm, background_mode, amplitude, background_brightness)
        self._stop = False

    def set_music_settings(self, rhythm: int, background_mode: int,
                           amplitude: int, background_brightness: int) -> None:
        """Update the four Music tab controls on a stream that is running.

        Called straight from the GUI thread, like stop(): this worker's thread
        is inside `run()` for the whole session and never returns to its event
        loop, so a queued slot would not be delivered until the stream had
        already ended. A single tuple assignment is the same safety class as
        the `_stop` flag assignment; the next frame the loop sends picks the
        new values up.
        """
        self._music = (rhythm, background_mode, amplitude, background_brightness)

    def stop(self) -> None:
        """Ask the loop to finish after the chunk it is on, and end the
        capture.

        Called straight from the GUI thread rather than through a queued
        signal for the same reason the other stream workers do it: this
        thread is inside `run()` for the whole session and never returns to
        its event loop, so a queued slot would not be delivered until the
        loop had already ended. A lone bool assignment is safe to do that way;
        terminating the subprocess is what lets a blocking read() on the pipe
        actually return.
        """
        self._stop = True
        proc = getattr(self, "_proc", None)
        if proc is not None and proc.poll() is None:
            proc.terminate()

    @Slot()
    def run(self) -> None:
        try:
            proc = subprocess.Popen(
                self._arecord_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError as exc:
            self.finished.emit(False, f"could not start arecord: {exc}")
            return
        self._proc = proc
        try:
            frames = late = failures = 0
            with HidrawTransport(self._device_path, timeout_seconds=self._timeout) as transport:
                while not self._stop:
                    frame_started = time.monotonic()
                    # Read the Music controls fresh each frame: the GUI thread
                    # swaps the whole tuple in set_music_settings() mid-stream,
                    # and a change must show up on the next frame, not the next
                    # Start.
                    rhythm, background_mode, amplitude, background_brightness = self._music
                    data = proc.stdout.read(self._chunk_bytes)
                    if not data:
                        break
                    if len(data) < self._chunk_bytes:
                        data += b"\x00" * (self._chunk_bytes - len(data))
                    levels = self._level_fn(data)
                    # Amplitude is the panel's 0..100 bar-height scale: scale
                    # the computed levels to it so the scale byte and the
                    # levels agree (build_audio_blocks checks levels <= scale).
                    if amplitude < kb_protocol.AUDIO_AMPLITUDE_DEFAULT:
                        levels = [
                            round(level * amplitude / 100.0)
                            for level in levels
                        ]
                    for tx in kb_protocol.build_audio_frame(
                            levels, scale=amplitude,
                            mode=background_mode, style=rhythm,
                            background_brightness=background_brightness):
                        transport.set_feature(bytes([kb_protocol.REPORT_ID]) + tx.outgoing)
                        time.sleep(self._gap)
                        if tx.expect_reply:
                            reply = transport.get_feature(
                                kb_protocol.REPORT_ID, kb_protocol.PACKET_SIZE + 1)[1:]
                            time.sleep(self._gap)
                            if not _is_acked(tx, reply):
                                failures += 1
                    frames += 1
                    self.frame.emit(levels)
                    remaining = self._period - (time.monotonic() - frame_started)
                    if remaining > 0:
                        time.sleep(remaining)
                    else:
                        late += 1
                # The panel holds the last frame it received, so a stream that
                # just stops leaves a frozen analyser on screen. Push one
                # all-zero frame so the bars drop and the display clears --
                # the "decay/hold/blank" question in re_notes turned out to be
                # "hold", and a blank frame is the exit. Sent whenever frames
                # were actually streamed, manual stop and capture EOF alike.
                # Deliberately *inside* the `with`: the transport must still be
                # open for this last send.
                if frames:
                    rhythm, background_mode, amplitude, background_brightness = self._music
                    for tx in kb_protocol.build_audio_frame(
                            [0] * kb_protocol.AUDIO_BAND_COUNT,
                            scale=amplitude,
                            mode=background_mode, style=rhythm,
                            background_brightness=background_brightness):
                        transport.set_feature(bytes([kb_protocol.REPORT_ID]) + tx.outgoing)
                        time.sleep(self._gap)
                        if tx.expect_reply:
                            transport.get_feature(
                                kb_protocol.REPORT_ID, kb_protocol.PACKET_SIZE + 1)
                    self.frame.emit([0] * audio_spectrum.SPECTRUM_BAND_COUNT)
            stderr = proc.stderr.read().decode(errors="replace").strip() if proc.stderr else ""
            message = f"audio spectrum stopped after {frames} frame(s)"
            if failures:
                message += f" ({failures} not acked)"
            if late:
                message += f" ({late} over the {self._period * 1000:.0f}ms frame budget)"
            if frames == 0 and stderr:
                message += f"; arecord: {stderr}"
            self.finished.emit(True, message)
        except (FileNotFoundError, PermissionError, TimeoutError, OSError) as exc:
            self.finished.emit(False, str(exc))
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    proc.kill()


def _is_acked(tx, reply: bytes | bytearray | None) -> bool:
    return (
        isinstance(reply, (bytes, bytearray))
        and len(reply) >= kb_protocol.ACK_OFFSET + 1
        and reply[0] == kb_protocol.CMD_PREFIX
        and reply[1] == tx.outgoing[1]
        and bool(reply[kb_protocol.ACK_OFFSET] & kb_protocol.ACK_FLAG)
    )


def _coerce_read_colors(
    colors: object,
    fallback: dict[int, tuple[int, int, int]] | None = None,
) -> dict[int, tuple[int, int, int]]:
    if isinstance(colors, dict) and set(colors) == set(kb_protocol.KEY_IDS):
        return dict(colors)
    if isinstance(fallback, dict) and set(fallback) == set(kb_protocol.KEY_IDS):
        return dict(fallback)
    return dict(colors) if isinstance(colors, dict) else {}


def _read_colors_from_transport(
    transport,
    gap: float = kb_protocol.PACKET_GAP_SECONDS,
    attempts: int = 2,
    retry_delay: float = 0.02,
    fallback: dict[int, tuple[int, int, int]] | None = None,
) -> dict[int, tuple[int, int, int]]:
    """Read the keyboard's current per-key colours, retrying briefly if the
    first query comes back incomplete or the device is still busy."""
    last_colors: dict[int, tuple[int, int, int]] = {}
    drain = getattr(transport, "drain", None)
    if callable(drain):
        drain()

    colors: dict[int, tuple[int, int, int]] = {}
    for attempt in range(attempts):
        framed_ok = True
        for tx in kb_protocol.build_color_query_commands():
            tx_attempts = 2 if tx.retry_until_ack else 1
            reply = None
            for _ in range(tx_attempts):
                transport.set_feature(bytes([kb_protocol.REPORT_ID]) + tx.outgoing)
                time.sleep(gap)
                if not tx.expect_reply:
                    reply = None
                    break
                reply = transport.get_feature(kb_protocol.REPORT_ID, kb_protocol.PACKET_SIZE + 1)[1:]
                time.sleep(gap)
                if _is_acked(tx, reply):
                    break
                if tx_attempts > 1:
                    time.sleep(kb_protocol.RETRY_DELAY_SECONDS)

            if tx.expect_reply and not _is_acked(tx, reply):
                framed_ok = False
                break

        if not framed_ok:
            if callable(drain):
                drain()
            if attempt < attempts - 1:
                time.sleep(retry_delay)
            continue

        blocks = []
        for _ in range(kb_protocol.COLOR_BLOCK_COUNT):
            block = transport.get_feature(kb_protocol.REPORT_ID, kb_protocol.PACKET_SIZE + 1)[1:]
            time.sleep(gap)
            blocks.append(block)

        colors = kb_protocol.parse_color_blocks(blocks)
        if set(colors) == set(kb_protocol.KEY_IDS):
            return _coerce_read_colors(colors, fallback)
        if callable(drain):
            drain()
        if attempt < attempts - 1:
            time.sleep(retry_delay)
    return _coerce_read_colors(colors, fallback)


def read_colors(
    device_path: str,
    timeout: float = 0.2,
    gap: float = kb_protocol.PACKET_GAP_SECONDS,
    attempts: int = 2,
    retry_delay: float = 0.02,
    fallback: dict[int, tuple[int, int, int]] | None = None,
) -> dict[int, tuple[int, int, int]]:
    """Read the keyboard's current per-key colours -- the GUI-side companion to
    aula_l99_hacky/cli.py's cmd_read_color, minus its printing and retry loop
    (this is a read path, not the flaky write path retry_until_ack guards
    against). Meant to run inside a CallableResultWorker closure, off the GUI
    thread. Raises on transport/HID failure."""
    with HidrawTransport(device_path, timeout_seconds=timeout) as transport:
        return _read_colors_from_transport(
            transport,
            gap=gap,
            attempts=attempts,
            retry_delay=retry_delay,
            fallback=fallback,
        )


class CallableResultWorker(QObject):
    """Runs an arbitrary no-arg callable on a background thread and reports
    its return value (or the exception's message) back via `finished`.

    Introduced for GIF upload: loading/resizing source frames and building
    the upload blob (protocol.py's dithering + CRC computation) were being
    done inline in the button's click handler, which froze the window for
    however long that took -- profiled at ~3s for just a 10-frame dithered
    GIF (see CHANGELOG). This has no device-I/O or GIF-specific knowledge of
    its own; the caller supplies a closure that does the actual work and
    raises on failure instead of touching any widgets, since this runs off
    the GUI thread.
    """

    finished = Signal(object, str)  # result (None on failure), error ("" on success)

    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self._fn = fn

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 - reported back, not swallowed
            self.finished.emit(None, str(exc))
        else:
            self.finished.emit(result, "")


class ScreenUploadWorker(QObject):
    """Sends a pre-built list of packets over SerialTransport -- mirrors
    cli.py's cmd_upload send loop but signal-driven."""

    progress = Signal(int, int, int)  # sent, total, acked
    finished = Signal(bool, str)

    def __init__(self, device_path: str, packets: list[bytes], gap: float = 0.005):
        super().__init__()
        self._device_path = device_path
        self._packets = packets
        self._gap = gap

    @Slot()
    def run(self) -> None:
        try:
            sent = acked = 0
            total = len(self._packets)
            with SerialTransport(self._device_path) as transport:
                for i, packet in enumerate(self._packets):
                    transport.write(packet)
                    sent += 1
                    reply = transport.read_reply()
                    if screen_protocol.is_ack(packet[4], reply):
                        acked += 1
                    else:
                        self.finished.emit(
                            False,
                            f"packet {i} not acked; stopping (leaving the transfer "
                            f"incomplete can freeze the panel -- power-cycle it)",
                        )
                        return
                    if i % 25 == 0 or i == total - 1:
                        self.progress.emit(sent, total, acked)
                    time.sleep(self._gap)
            self.finished.emit(acked == sent, f"{sent} packets sent, {acked} acked")
        except (FileNotFoundError, PermissionError, OSError) as exc:
            self.finished.emit(False, str(exc))
