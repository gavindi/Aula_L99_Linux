"""Keyboard (aula_l99_hacky) control tab: handshake, per-key color, effects, RTC."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
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
        self._color = QColor(255, 0, 0)
        self._action_buttons: list[QPushButton] = []

        self._build_ui()
        selector.changed.connect(self._on_device_changed)

    # -- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Read-only mirror of the Device tab's status line: the picker lives
        # there now, but the user still needs to see which node an action will
        # hit, and why the buttons below are greyed out when none is found.
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        layout.addWidget(self._build_handshake_group())
        layout.addWidget(self._build_color_group())
        layout.addWidget(self._build_effect_group())
        layout.addWidget(self._build_rtc_group())

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        layout.addWidget(self.log)

    def _build_handshake_group(self) -> QGroupBox:
        group = QGroupBox("Connection")
        row = QHBoxLayout(group)
        button = QPushButton("Test Connection")
        button.clicked.connect(self._on_handshake)
        row.addWidget(button)
        row.addStretch(1)
        self._action_buttons.append(button)
        return group

    def _build_color_group(self) -> QGroupBox:
        group = QGroupBox("Color")
        row = QHBoxLayout(group)

        self.color_swatch = QFrame()
        self.color_swatch.setFixedSize(32, 24)
        self.color_swatch.setFrameShape(QFrame.Shape.Box)
        self._update_swatch()
        row.addWidget(self.color_swatch)

        choose_button = QPushButton("Choose Color…")
        choose_button.clicked.connect(self._on_choose_color)
        row.addWidget(choose_button)

        apply_button = QPushButton("Apply to All Keys")
        apply_button.clicked.connect(self._on_apply_color)
        row.addWidget(apply_button)
        self._action_buttons.append(apply_button)

        row.addStretch(1)
        return group

    def _build_effect_group(self) -> QGroupBox:
        group = QGroupBox("Effect")
        layout = QVBoxLayout(group)

        combo_row = QHBoxLayout()
        combo_row.addWidget(QLabel("Effect:"))
        self.effect_combo = QComboBox()
        for effect_id, name in sorted(kb_protocol.EFFECT_NAMES.items()):
            tag = "confirmed" if effect_id in kb_protocol.EFFECT_CONFIRMED else "untested"
            self.effect_combo.addItem(f"0x{effect_id:02X}  {name}  ({tag})", effect_id)
        combo_row.addWidget(self.effect_combo, stretch=1)
        layout.addLayout(combo_row)

        params_row = QHBoxLayout()
        params_row.addWidget(QLabel("Speed:"))
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(kb_protocol.EFFECT_SPEED_MIN, kb_protocol.EFFECT_SPEED_MAX)
        self.speed_spin.setValue(kb_protocol.EFFECT_SPEED_DEFAULT)
        params_row.addWidget(self.speed_spin)

        params_row.addWidget(QLabel("Brightness:"))
        self.brightness_spin = QSpinBox()
        self.brightness_spin.setRange(1, kb_protocol.EFFECT_BRIGHTNESS_MAX)
        self.brightness_spin.setValue(kb_protocol.EFFECT_BRIGHTNESS_MAX)
        params_row.addWidget(self.brightness_spin)
        params_row.addStretch(1)
        layout.addLayout(params_row)

        run_button = QPushButton("Run Effect")
        run_button.clicked.connect(self._on_run_effect)
        layout.addWidget(run_button)
        self._action_buttons.append(run_button)

        return group

    def _build_rtc_group(self) -> QGroupBox:
        group = QGroupBox("Clock")
        row = QHBoxLayout(group)
        button = QPushButton("Set Clock to Now")
        button.clicked.connect(self._on_set_rtc)
        row.addWidget(button)
        self._action_buttons.append(button)
        row.addStretch(1)
        return group

    # -- device handling --------------------------------------------------

    def _on_device_changed(self, status: str, enabled: bool) -> None:
        self.status_label.setText(status)
        self._device_ready = enabled
        self._sync_actions()

    def _sync_actions(self) -> None:
        # Gating on `_busy` as well as device availability matters because the
        # Device tab's Refresh stays clickable during an operation -- without
        # it, a mid-transaction refresh would re-arm these buttons.
        enabled = self._device_ready and not self._busy
        for button in self._action_buttons:
            button.setEnabled(enabled)

    # -- color ------------------------------------------------------------

    def _update_swatch(self) -> None:
        self.color_swatch.setStyleSheet(f"background-color: {self._color.name()};")

    def _on_choose_color(self) -> None:
        color = QColorDialog.getColor(self._color, self, "Choose Color")
        if color.isValid():
            self._color = color
            self._update_swatch()

    def _rgb(self) -> tuple[int, int, int]:
        return (self._color.red(), self._color.green(), self._color.blue())

    # -- actions ------------------------------------------------------------

    def _on_handshake(self) -> None:
        self._run_transactions(kb_protocol.build_cable_handshake())

    def _on_apply_color(self) -> None:
        colors = kb_protocol.build_uniform_colors(self._rgb())
        self._run_transactions(kb_protocol.build_color_transfer(colors))

    def _on_run_effect(self) -> None:
        effect_id = self.effect_combo.currentData()
        transactions = kb_protocol.build_effect_transfer(
            effect_id,
            rgb=self._rgb(),
            speed=self.speed_spin.value(),
            brightness=self.brightness_spin.value(),
        )
        self._run_transactions(transactions)

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

        # `self._worker`/`self._thread` are reassigned (not cleared) here on
        # every run: they must stay referenced for as long as the previous
        # operation's QThread might still be alive. Both objects use
        # deleteLater() (see workers.start_worker) so the C++ side is
        # already torn down safely by the time this reassignment drops the
        # old Python reference -- explicitly nulling them from a slot
        # connected to their own finished signal raced with that deferred
        # deletion and crashed (double free). Reassignment itself is only
        # safe once the *old* QThread has actually stopped, which is why
        # `self._busy` (guarding re-entry into this method) is cleared from
        # `thread.finished`, not `worker.finished` -- see _on_thread_stopped.
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
