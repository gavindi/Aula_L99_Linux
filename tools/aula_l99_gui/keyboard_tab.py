"""Keyboard tab: a live view of each key's current colour, polled at a
user-adjustable interval (default 100ms).

The two controls that used to sit under that view -- "Set Clock to Now" and
the poll interval -- are on the Config tab now, driving this tab through
`set_clock_now()`/`set_poll_interval()`. The work itself stays here rather
than moving with them: the poll thread lives here, and so does the
write-behind-an-in-flight-read queue that keeps an RTC write from racing it
for the same hidraw handle.

Split out from lighting_tab.py, which is also keyed off the keyboard's
DeviceSelector but hosts the color/effect controls under the Lighting tab.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from aula_l99_hacky import protocol as kb_protocol

from .debug_log import DebugLog
from .device_tab import DeviceSelector
from .device_utils import KEYBOARD_PERMISSION_HINT
from .keyboard_overlay import KeyboardOverlay
from .workers import CallableResultWorker, KeyboardWorker, read_colors, start_worker

DEFAULT_POLL_INTERVAL_MS = 100
# The vendor app itself polls its colour-query opcode ~27x/s (~37ms) to drive
# its own preview (see protocol.py's OP_COLOR_QUERY note) -- this is the read
# side, not the flash-writing colour-set path protocol.py warns not to
# hammer. The spinner's floor (1ms) is far below that precedented rate; in
# practice each read's own HID round-trip time (open + several feature
# reports) dominates over the timer interval, and _poll_busy prevents ticks
# from overlapping if a read is still in flight when the next one fires.
MIN_POLL_INTERVAL_MS = 1
MAX_POLL_INTERVAL_MS = 5000


class KeyboardTab(QWidget):
    busy_changed = Signal(bool)
    # (value, maximum) for whichever tab is hosting the button that started
    # the write -- the Config tab, since this one no longer has any controls
    # of its own to put a progress bar under.
    write_progress = Signal(int, int)

    def __init__(self, selector: DeviceSelector, debug_log: DebugLog) -> None:
        super().__init__()
        self._selector = selector
        self._debug_log = debug_log
        self._thread = None
        self._worker = None
        self._busy = False
        self._device_ready = False
        self._poll_worker = None
        self._poll_thread = None
        self._poll_busy = False
        self._external_busy = False
        self._pending_write = None

        self._build_ui()
        selector.changed.connect(self._on_device_changed)

    # -- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        overlay_row = QHBoxLayout()
        overlay_row.addStretch(1)
        overlay_row.addWidget(self._build_overlay())
        overlay_row.addStretch(1)
        layout.addLayout(overlay_row)
        layout.addStretch(1)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(DEFAULT_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._on_poll_tick)
        self._poll_timer.start()

    def _build_overlay(self) -> KeyboardOverlay:
        overlay = KeyboardOverlay()
        overlay.setVisible(False)
        self.overlay = overlay
        return overlay

    # -- device handling --------------------------------------------------

    def _on_device_changed(self, status: str, enabled: bool) -> None:
        self._device_ready = enabled
        self.overlay.setVisible(enabled)
        if not enabled:
            self.overlay.clear_swatches()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)

    def set_external_busy(self, busy: bool) -> None:
        """Called by MainWindow with whether *any* tab is mid-upload -- colour
        polling pauses for those too, not just this tab's own actions, since
        any of them can be holding the keyboard's hidraw handle open."""
        self._external_busy = busy

    # -- actions ------------------------------------------------------------

    def set_clock_now(self) -> None:
        """Set the keyboard's onboard RTC to the host's current time. Called
        from the Config tab's button."""
        self._run_transactions(kb_protocol.build_rtc_transfer(datetime.now()))

    def set_poll_interval(self, interval_ms: int) -> None:
        """Retune colour polling live, from the Config tab's spin box."""
        self._poll_timer.setInterval(interval_ms)

    @property
    def is_busy(self) -> bool:
        return self._busy

    def _run_transactions(self, transactions: list) -> None:
        if self._busy:
            return
        device_path = self._selector.current_path()
        if device_path is None:
            QMessageBox.warning(self, "Keyboard", "No device selected.")
            return

        self._set_busy(True)
        self.write_progress.emit(0, max(len(transactions), 1))
        self._debug_log.clear()

        if self._poll_busy:
            # A colour-poll read already has the hidraw handle open --
            # opening a second one for this write at the same time is exactly
            # the interleaving _on_poll_tick's own guard exists to prevent.
            # Queue it; _on_poll_thread_stopped starts it once that read
            # actually finishes, typically well under a poll interval later.
            self._pending_write = (device_path, transactions)
            return
        self._start_write(device_path, transactions)

    def _start_write(self, device_path: str, transactions: list) -> None:
        # See lighting_tab.py's _run_transactions for why `_worker`/`_thread`
        # are kept referenced until `thread.finished` (not `worker.finished`)
        # and why `_busy` is only cleared there.
        self._worker = KeyboardWorker(device_path, transactions)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._thread = start_worker(self._worker)
        self._thread.finished.connect(self._on_thread_stopped)

    def _on_progress(self, index: int, total: int, name: str, acked: bool) -> None:
        self.write_progress.emit(index + 1, total)
        self._debug_log.append("Keyboard", f"{name}: {'ok' if acked else 'NOT ACKED'}")

    def _on_finished(self, success: bool, message: str) -> None:
        self._debug_log.append("Keyboard", f"-- {message}")
        if not success:
            text = message
            if "permission" in message.lower():
                text = f"{message}\n\n{KEYBOARD_PERMISSION_HINT}"
            QMessageBox.critical(self, "Keyboard Error", text)

    def _on_thread_stopped(self) -> None:
        # Only safe to allow a new action (and thus a new
        # self._worker/self._thread reassignment) once the QThread has
        # actually stopped -- not merely once the worker reported it was
        # done, which races the still-shutting-down old thread.
        self._set_busy(False)

    # -- colour polling -----------------------------------------------------

    def _on_poll_tick(self) -> None:
        # Skipped (not queued) while busy -- an RTC write and a colour read
        # opening the same hidraw node from two threads at once could
        # interleave the firmware's stateful begin/commit/end session.
        # `_poll_busy` guards against a slow read still being in flight when
        # the next tick fires, rather than piling up overlapping workers.
        if not self._device_ready or self._busy or self._external_busy or self._poll_busy:
            return
        device_path = self._selector.current_path()
        if device_path is None:
            return

        self._poll_busy = True
        self._poll_worker = CallableResultWorker(lambda: read_colors(device_path))
        self._poll_worker.finished.connect(self._on_poll_finished)
        self._poll_thread = start_worker(self._poll_worker)
        self._poll_thread.finished.connect(self._on_poll_thread_stopped)

    def _on_poll_finished(self, colors: object, error: str) -> None:
        # Silently skipped on error -- a transient read failure every second
        # shouldn't spam a dialog; explicit actions (Set Clock) still surface
        # their own errors.
        if not error:
            self.overlay.set_swatches(colors)

    def _on_poll_thread_stopped(self) -> None:
        self._poll_busy = False
        if self._pending_write is not None:
            device_path, transactions = self._pending_write
            self._pending_write = None
            self._start_write(device_path, transactions)

    def shutdown(self) -> None:
        """Called by MainWindow just before the app closes. Colour polling
        isn't gated by MainWindow.closeEvent's busy-check (it's a lightweight,
        frequent read, not a risky write worth nagging the user to wait out)
        -- but an in-flight poll's QThread still has to actually stop before
        this object graph gets torn down, or Qt aborts the process rather
        than destroy a thread that's still running. `_poll_busy` guards
        touching `_poll_thread` at all: once it's False, `_on_poll_thread_stopped`
        has already run, meaning `thread.finished` (and the deleteLater()
        chained off the same signal in workers.start_worker) has already
        fired, so the underlying C++ QThread may no longer exist to call
        into."""
        self._poll_timer.stop()
        if self._poll_busy and self._poll_thread is not None:
            self._poll_thread.quit()
            self._poll_thread.wait()
