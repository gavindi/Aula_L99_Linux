"""Keyboard tab: sets the keyboard's onboard RTC to the host's current time.

Split out from lighting_tab.py, which is also keyed off the keyboard's
DeviceSelector but hosts the color/effect controls under the Lighting tab.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aula_l99_hacky import protocol as kb_protocol

from .device_tab import DeviceSelector
from .device_utils import KEYBOARD_PERMISSION_HINT
from .workers import KeyboardWorker, start_worker


class KeyboardTab(QWidget):
    def __init__(self, selector: DeviceSelector) -> None:
        super().__init__()
        self._selector = selector
        self._thread = None
        self._worker = None
        self._busy = False
        self._device_ready = False
        self._action_buttons: list[QPushButton] = []

        self._build_ui()
        selector.changed.connect(self._on_device_changed)

    # -- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(self._build_rtc_group())

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        layout.addWidget(self.log)

    def _build_rtc_group(self) -> QGroupBox:
        group = QGroupBox()
        row = QHBoxLayout(group)
        button = QPushButton("Set Clock to Now")
        button.clicked.connect(self._on_set_rtc)
        row.addWidget(button)
        self._action_buttons.append(button)
        row.addStretch(1)
        return group

    # -- device handling --------------------------------------------------

    def _on_device_changed(self, status: str, enabled: bool) -> None:
        self._device_ready = enabled
        self._sync_actions()

    def _sync_actions(self) -> None:
        # Gating on `_busy` as well as device availability matters because the
        # Device tab's Refresh stays clickable during an operation -- without
        # it, a mid-transaction refresh would re-arm these buttons.
        enabled = self._device_ready and not self._busy
        for button in self._action_buttons:
            button.setEnabled(enabled)

    # -- actions ------------------------------------------------------------

    def _on_set_rtc(self) -> None:
        self._run_transactions(kb_protocol.build_rtc_transfer(datetime.now()))

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

        self._busy = True
        self._sync_actions()
        self.progress_bar.setMaximum(max(len(transactions), 1))
        self.progress_bar.setValue(0)
        self.log.clear()

        # See lighting_tab.py's _run_transactions for why `_worker`/`_thread`
        # are kept referenced until `thread.finished` (not `worker.finished`)
        # and why `_busy` is only cleared there.
        self._worker = KeyboardWorker(device_path, transactions)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._thread = start_worker(self._worker)
        self._thread.finished.connect(self._on_thread_stopped)

    def _on_progress(self, index: int, total: int, name: str, acked: bool) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(index + 1)
        self.log.appendPlainText(f"{name}: {'ok' if acked else 'NOT ACKED'}")

    def _on_finished(self, success: bool, message: str) -> None:
        self.log.appendPlainText(f"-- {message}")
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
        self._busy = False
        self._sync_actions()
