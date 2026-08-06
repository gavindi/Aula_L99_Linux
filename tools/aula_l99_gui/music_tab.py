"""Music tab: drive the touchscreen's spectrum analyser from live audio.

Captures from an ALSA input device (picked from `arecord -l`), computes a
17-band spectrum with audio_spectrum's pure-Python Goertzel, and streams each
frame to the panel via the keyboard's audio feed (aula_l99_hacky's OP_AUDIO,
0x78). The panel renders bands 0..16 -- exactly the 17 the tab produces -- so
what the preview shows is what the analyser draws.

The stream is a "streaming, not busy" operation in the User Lighting sense:
it runs for as long as the user leaves it on, so it must not raise the
window's loading overlay or block closing, but it does own the keyboard's
hidraw handle for its whole run and so holds the Keyboard tab's colour poll
off -- see MainWindow._on_any_busy_changed.

The spectrum feed is cable-only (cli.py's `--spectrum` is _require_cable),
so the tab is driven by the *keyboard* DeviceSelector and Start is gated on a
wired device being enabled.

The 0x78 feed lights the keyboard as well as the panel's analyser, and the
keyboard stays in that music mode after the feed stops (it only reverts when
the host session closes), so the tab snapshots the keyboard's lighting before
the stream starts and hands it back on stop -- see `_restore_keyboard`.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from aula_l99_hacky import protocol as kb_protocol

from . import audio_spectrum, settings, theme
from .debug_log import DebugLog
from .device_tab import DeviceSelector
from .device_utils import KEYBOARD_PERMISSION_HINT
from .workers import (
    AudioSpectrumWorker,
    CallableResultWorker,
    KeyboardWorker,
    read_colors,
    start_worker,
)

# Ceiling on how long to wait for the stream thread after stop(). The real
# figure is one chunk read (~43ms) plus its I/O; this only matters if the
# device stops answering and the transport sits on its own timeout.
STREAM_STOP_WAIT_MS = 3000

# Inter-packet gaps for the colour snapshot read at stream start and the
# restore write on stop. Both are one-shot paths, and ~3-5ms between packets
# is plenty (the realtime colour stream runs at 3ms), so they stay quick
# rather than inheriting the vendor poll's ~37ms gap.
RESTORE_READ_GAP = 0.005
RESTORE_GAP = 0.003

# The panel's analyser renders 17 segments (wire bands 0..16); bands 17..22 of
# the 23 the block carries are ignored. This tab produces exactly the visible
# 17 and lets build_audio_blocks zero-pad the rest.
PREVIEW_BAND_COUNT = audio_spectrum.SPECTRUM_BAND_COUNT


class SpectrumPreview(QWidget):
    """A live 17-bar analyser, drawn from the worker's frame signal.

    Deliberately a hand-rolled paintEvent rather than a charting dependency:
    it is 17 rectangles and a baseline. The orange bars match the vendor
    skin's accent; the panel's own analyser draws the same shape.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(140)
        self._levels = [0] * PREVIEW_BAND_COUNT

    def set_levels(self, levels: list[int]) -> None:
        if len(levels) != PREVIEW_BAND_COUNT:
            levels = (levels + [0] * PREVIEW_BAND_COUNT)[:PREVIEW_BAND_COUNT]
        self._levels = list(levels)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.CONTENT))
        painter.setPen(QPen(QColor(theme.PANEL_BORDER)))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        count = len(self._levels)
        width = self.width() - 2
        height = self.height() - 2
        margin = 2
        slot = (width - margin * 2) // count
        bar_width = max(slot - 2, 1)
        baseline = height

        bar_color = QColor(theme.ACCENT)
        for i, level in enumerate(self._levels):
            x = margin + 1 + i * slot + (slot - bar_width) // 2
            bar_height = max(1, round(level / 100.0 * height))
            painter.fillRect(
                x, baseline - bar_height, bar_width, bar_height, bar_color
            )
        painter.end()


class MusicTab(QWidget):
    busy_changed = Signal(bool)
    # Separate from busy_changed on purpose: the spectrum stream runs until the
    # user stops it, so like a User Lighting animation it must not raise the
    # loading overlay or block closing -- it only needs the Keyboard tab's
    # colour poll held off while it owns the hidraw handle.
    streaming_changed = Signal(bool)

    def __init__(self, selector: DeviceSelector, debug_log: DebugLog) -> None:
        super().__init__()
        self._selector = selector
        self._debug_log = debug_log
        self._thread = None
        self._worker = None
        self._stream_thread = None
        self._stream_worker = None
        self._streaming = False
        self._device_ready = False
        self._refresh_worker = None
        self._refresh_thread = None
        # True while a device listing is in flight. `start_worker`'s
        # `thread.finished -> deleteLater` chain means the C++ QThread can
        # already be gone by the time `shutdown()` runs, so it cannot be
        # queried via isRunning(); this flag is what shutdown waits on.
        self._refresh_active = False
        self._devices: list[audio_spectrum.CaptureDevice] = []
        # The keyboard's lighting just before the stream started, so stop can
        # hand it back. The 0x78 feed lights the keyboard as well as the
        # panel, and it stays in that music mode after the feed stops.
        self._restore_colors: dict[int, tuple[int, int, int]] | None = None
        self._restore_worker = None
        self._restore_thread = None
        # True while the restore write is in flight; shutdown and a fresh
        # stream both wait on it (same shape as _refresh_active, for the same
        # reason: the C++ QThread is deleteLater'd on finish and cannot be
        # queried via isRunning()).
        self._restore_active = False
        self._shutting_down = False

        self._build_ui()
        selector.changed.connect(self._on_device_changed)
        # Deferred to the first event-loop iteration rather than run in the
        # constructor: the listing is a subprocess call on a worker thread,
        # and starting that thread before QApplication's event loop is running
        # (MainWindow builds this tab during __init__) means the thread's
        # auto-deletion never gets processed and Qt aborts on teardown. A
        # one-shot timer starts the same work the instant the loop runs.
        QTimer.singleShot(0, self._refresh_devices)

    # -- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        input_group = QGroupBox("Audio Input")
        input_layout = QVBoxLayout(input_group)

        row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.setEnabled(False)
        row.addWidget(self.device_combo, stretch=1)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._refresh_devices)
        row.addWidget(refresh_button)
        input_layout.addLayout(row)

        self.input_status = QLabel()
        self.input_status.setWordWrap(True)
        input_layout.addWidget(self.input_status)
        layout.addWidget(input_group)

        preview_group = QGroupBox("Spectrum")
        preview_layout = QVBoxLayout(preview_group)
        self.preview = SpectrumPreview()
        preview_layout.addWidget(self.preview)
        layout.addWidget(preview_group, stretch=1)

        settings_group = QGroupBox("Music Settings")
        settings_layout = QVBoxLayout(settings_group)

        row = QHBoxLayout()
        row.addWidget(QLabel("Rhythm"))
        self.rhythm_combo = QComboBox()
        self.rhythm_combo.addItems(list(kb_protocol.AUDIO_RHYTHM_NAMES))
        row.addWidget(self.rhythm_combo, stretch=1)
        settings_layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Background Mode"))
        self.background_mode_combo = QComboBox()
        self.background_mode_combo.addItems(
            list(kb_protocol.AUDIO_BACKGROUND_MODE_NAMES))
        row.addWidget(self.background_mode_combo, stretch=1)
        settings_layout.addLayout(row)

        self.amplitude_slider = self._build_labeled_slider(
            settings_layout, "Amplitude",
            kb_protocol.AUDIO_AMPLITUDE_DEFAULT)
        self.background_brightness_slider = self._build_labeled_slider(
            settings_layout, "Background Brightness",
            kb_protocol.AUDIO_BACKGROUND_BRIGHTNESS_DEFAULT)
        layout.addWidget(settings_group)

        controls = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._on_start_stop)
        controls.addWidget(self.start_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.stream_status = QLabel()
        self.stream_status.setWordWrap(True)
        layout.addWidget(self.stream_status)

        self._sync_actions()
        self._load_settings()
        self.rhythm_combo.currentIndexChanged.connect(self._save_settings)
        self.background_mode_combo.currentIndexChanged.connect(self._save_settings)
        self.amplitude_slider.valueChanged.connect(self._save_settings)
        self.background_brightness_slider.valueChanged.connect(self._save_settings)

    # -- device handling --------------------------------------------------

    def _build_labeled_slider(self, parent_layout, title: str, default: int,
                              minimum: int = 0, maximum: int = 100) -> QSlider:
        parent_layout.addWidget(QLabel(title))

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(default)
        parent_layout.addWidget(slider)

        value_label = QLabel(str(default))
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        slider.valueChanged.connect(lambda value: value_label.setText(str(value)))
        parent_layout.addWidget(value_label)

        return slider

    def _load_settings(self) -> None:
        saved = settings.music_settings()
        self.rhythm_combo.setCurrentIndex(saved["rhythm"])
        self.background_mode_combo.setCurrentIndex(saved["background_mode"])
        self.amplitude_slider.setValue(saved["amplitude"])
        self.background_brightness_slider.setValue(saved["background_brightness"])

    def _music_settings(self) -> dict:
        return {
            "rhythm": self.rhythm_combo.currentIndex(),
            "background_mode": self.background_mode_combo.currentIndex(),
            "amplitude": self.amplitude_slider.value(),
            "background_brightness": self.background_brightness_slider.value(),
        }

    def _save_settings(self) -> None:
        settings.set_music_settings(self._music_settings())
        # The stream reads its Music controls fresh each frame, so push the new
        # values onto a running worker -- a live capture picks them up on the
        # next frame rather than on the next Start.
        worker = self._stream_worker
        if worker is not None:
            worker.set_music_settings(**self._music_settings())
            self._debug_log.append(
                "Music", "-- settings changed while streaming")

    def _on_device_changed(self, _status: str, enabled: bool, _found: bool,
                           _kind: str) -> None:
        self._device_ready = enabled
        self._sync_actions()

    def _refresh_devices(self) -> None:
        # arecord -l is a subprocess call, so it runs on a worker thread and
        # repopulates the combo on the GUI thread when it returns -- the same
        # pattern the Touchscreen tab uses for anything that could block.
        self.device_combo.setEnabled(False)
        self.input_status.setText("Listing audio input devices…")
        self._refresh_active = True
        self._refresh_worker = CallableResultWorker(audio_spectrum.list_capture_devices)
        self._refresh_worker.finished.connect(self._on_devices_loaded)
        self._refresh_thread = start_worker(self._refresh_worker)
        self._refresh_thread.finished.connect(self._on_refresh_thread_stopped)

    def _on_refresh_thread_stopped(self) -> None:
        self._refresh_active = False

    def _on_devices_loaded(self, devices: object, error: str) -> None:
        if error:
            self._devices = []
            self.input_status.setText(f"Could not list audio devices: {error}")
            self.device_combo.clear()
            self.device_combo.setEnabled(False)
            self._sync_actions()
            return
        self._devices = list(devices)
        self.device_combo.clear()
        for device in self._devices:
            self.device_combo.addItem(device.label, device.plughw)
        if self._devices:
            self.input_status.setText(
                f"{len(self._devices)} capture device(s); select one and press Start. "
                "Point the panel at its music screen to see the analyser.")
        else:
            self.input_status.setText("No capture devices found.")
        self._sync_actions()

    # -- streaming ---------------------------------------------------------

    def _on_start_stop(self) -> None:
        if self._streaming:
            self._stop_stream()
            return
        self._start_stream()

    def _start_stream(self) -> None:
        self._stop_stream()  # only ever one stream on the device at a time
        # A colour restore from a just-stopped stream may still be writing;
        # wait it out so its writes can't interleave with this stream's
        # frames, and cancel any restore the old stream would still trigger.
        if self._restore_active and self._restore_thread is not None:
            self._restore_thread.wait(STREAM_STOP_WAIT_MS)
        self._restore_colors = None
        if not self._device_ready:
            QMessageBox.warning(
                self, "Music", "The spectrum feed needs the wired cable keyboard; "
                "the 2.4G dongle cannot carry it.")
            return
        device_path = self._selector.current_path()
        if device_path is None:
            QMessageBox.warning(self, "Music", "No keyboard selected.")
            return
        index = self.device_combo.currentIndex()
        if index < 0:
            QMessageBox.warning(self, "Music", "No audio input device selected.")
            return
        plughw = self.device_combo.itemData(index)
        if not plughw:
            QMessageBox.warning(self, "Music", "No audio input device selected.")
            return

        # The spectrum feed lights the keyboard as well as the panel, and the
        # keyboard stays in that music mode after the feed stops (the blank
        # frame on stop clears the panel's analyser, not the keyboard's
        # lighting). Snapshot what the keyboard was showing so stop can hand
        # it back. A failed read just means no restore.
        try:
            self._restore_colors = read_colors(
                device_path, gap=RESTORE_READ_GAP)
        except OSError:
            self._restore_colors = None

        arecord_cmd = audio_spectrum.arecord_command(plughw)
        level_fn = audio_spectrum.levels_from_pcm
        self._stream_worker = AudioSpectrumWorker(
            device_path, arecord_cmd, level_fn,
            **self._music_settings(),
        )
        self._stream_worker.frame.connect(self.preview.set_levels)
        self._stream_worker.finished.connect(self._on_stream_finished)
        self._stream_thread = start_worker(self._stream_worker)
        self._set_streaming(True)
        self._debug_log.append(
            "Music", f"-- capturing {self.device_combo.currentText()} "
            f"({plughw}) -> panel spectrum")
        self.stream_status.setText(
            f"Streaming to the panel at ~{1 / kb_protocol.AUDIO_FRAME_SECONDS:.0f} "
            "frames/s. Press Stop to end.")

    def _stop_stream(self) -> None:
        """Stop the stream and wait for its thread, so the device is free
        before whatever comes next opens it. A no-op when nothing is running.

        Blocking the GUI thread here is deliberate: the wait is one chunk read
        (~43ms) plus its I/O, and every alternative means threading a
        continuation through every caller for a delay too short to see.
        """
        if not self._streaming:
            return
        self._stream_worker.stop()
        if self._stream_thread is not None:
            self._stream_thread.wait(STREAM_STOP_WAIT_MS)
        self._set_streaming(False)

    def _on_stream_finished(self, success: bool, message: str) -> None:
        self._debug_log.append("Music", f"-- {message}")
        self._set_streaming(False)
        if not success:
            text = message
            if "permission" in message.lower():
                text = f"{message}\n\n{KEYBOARD_PERMISSION_HINT}"
            QMessageBox.critical(self, "Music Error", text)
            self._restore_colors = None
            return
        self._restore_keyboard()

    def _restore_keyboard(self) -> None:
        """Hand the keyboard back to the lighting it had before the stream.

        The 0x78 spectrum feed lights the keyboard as well as the panel's
        analyser, and the keyboard stays in that music mode once the feed
        stops -- the all-zero frame on stop clears the panel, not the
        keyboard (it only reverts when the app quits and the host session
        closes). Restore the snapshot taken at stream start the same way
        user_lighting_tab puts its base colours back after an animation:
        select custom per-key mode, then write the colours, so the write is
        not ignored by a running effect/music mode.
        """
        colors = self._restore_colors
        self._restore_colors = None
        if self._shutting_down or not colors:
            return
        device_path = self._selector.current_path()
        if device_path is None:
            return
        transactions = (
            kb_protocol.build_effect_transfer(
                kb_protocol.EFFECT_CUSTOM,
                speed=kb_protocol.EFFECT_SPEED_DEFAULT,
                brightness=kb_protocol.EFFECT_BRIGHTNESS_MAX)
            + kb_protocol.build_color_transfer(colors)
        )
        self._restore_worker = KeyboardWorker(
            device_path, transactions, gap=RESTORE_GAP)
        self._restore_worker.finished.connect(self._on_restore_finished)
        self._restore_active = True
        self._restore_thread = start_worker(self._restore_worker)
        self._restore_thread.finished.connect(self._on_restore_thread_stopped)
        self._debug_log.append(
            "Music", "-- restored keyboard lighting after stream")

    def _on_restore_finished(self, success: bool, message: str) -> None:
        self._debug_log.append("Music", f"-- keyboard restore: {message}")

    def _on_restore_thread_stopped(self) -> None:
        self._restore_active = False

    def _set_streaming(self, streaming: bool) -> None:
        if streaming == self._streaming:
            return
        self._streaming = streaming
        self.start_button.setText("Stop" if streaming else "Start")
        self._sync_actions()
        self.streaming_changed.emit(streaming)

    @property
    def is_streaming(self) -> bool:
        return self._streaming

    @property
    def is_busy(self) -> bool:
        return False

    def _sync_actions(self) -> None:
        has_device = self.device_combo.currentIndex() >= 0 and bool(
            self.device_combo.itemData(self.device_combo.currentIndex()))
        self.device_combo.setEnabled(not self._streaming and bool(self._devices))
        # While streaming, the button is "Stop" and must stay enabled so it
        # can be clicked; the device combo is frozen for the duration instead.
        self.start_button.setEnabled(
            self._streaming or (self._device_ready and has_device))

    def shutdown(self) -> None:
        """Stop the stream thread before the window is torn down -- Qt aborts
        the process if a QThread is still running at that point (the same
        reason KeyboardTab and UserLightingTab have one of these). Also waits
        out a device listing or keyboard-restore write that is still in
        flight, for the same reason.

        The keyboard restore is skipped here: the keyboard returns to its
        own stored pattern when the app quits and the host session ends, so
        re-applying colours would be pointless (and would start a thread the
        teardown would then have to wait for)."""
        self._shutting_down = True
        self._stop_stream()
        if self._refresh_active and self._refresh_thread is not None:
            self._refresh_thread.wait(STREAM_STOP_WAIT_MS)
        if self._restore_active and self._restore_thread is not None:
            self._restore_thread.wait(STREAM_STOP_WAIT_MS)
