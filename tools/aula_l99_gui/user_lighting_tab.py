"""User Lighting tab: per-key color picking (wheel/RGB/presets) and the
"Apply to All Keys" static-color action.

Entirely self-contained -- its color state and Colorful checkbox affect only
this tab's own Apply action, not the Lighting tab's Run Effect (which has
its own separate copy of the same controls in lighting_tab.py).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from aula_l99_hacky import protocol as kb_protocol

from .color_wheel import ColorWheel
from .device_tab import DeviceSelector
from .device_utils import KEYBOARD_PERMISSION_HINT
from .workers import KeyboardWorker, start_worker

# Preset swatches: red, orange, yellow, green, blue, cyan, magenta, white.
PRESET_COLORS = [
    (255, 0, 0),
    (255, 128, 0),
    (255, 255, 0),
    (0, 255, 0),
    (0, 0, 255),
    (0, 255, 255),
    (255, 0, 255),
    (255, 255, 255),
]

# kb_protocol.EFFECT_NAMES[0x06] == "colourful" -- confirmed by capture, the
# built-in effect that cycles its own colors rather than taking one.
COLORFUL_EFFECT_ID = 0x06


class UserLightingTab(QWidget):
    busy_changed = Signal(bool)

    def __init__(self, selector: DeviceSelector) -> None:
        super().__init__()
        self._selector = selector
        self._thread = None
        self._worker = None
        self._busy = False
        self._device_ready = False
        self._color = QColor(255, 0, 0)
        self._action_buttons: list[QPushButton] = []
        self._color_pickers: list[QWidget] = []

        self._build_ui()
        selector.changed.connect(self._on_device_changed)

    # -- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(self._build_color_group())

        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        layout.addWidget(self.log)

    def _build_color_group(self) -> QGroupBox:
        group = QGroupBox()
        outer = QVBoxLayout(group)

        self.colorful_checkbox = QCheckBox("Colorful")
        self.colorful_checkbox.toggled.connect(self._on_colorful_toggled)
        outer.addWidget(self.colorful_checkbox)

        picker_row = QHBoxLayout()
        picker_row.addLayout(self._build_palette_column())
        picker_row.addLayout(self._build_channel_column(), stretch=1)
        outer.addLayout(picker_row)

        apply_button = QPushButton("Apply to All Keys")
        apply_button.clicked.connect(self._on_apply_color)
        outer.addWidget(apply_button)
        self._action_buttons.append(apply_button)

        return group

    def _build_palette_column(self):
        column = QVBoxLayout()

        swatch_row = QHBoxLayout()
        swatch_row.addStretch(1)
        self.color_swatch = QFrame()
        self.color_swatch.setFixedSize(40, 30)
        self.color_swatch.setFrameShape(QFrame.Shape.Box)
        self._update_swatch()
        swatch_row.addWidget(self.color_swatch)
        swatch_row.addStretch(1)
        column.addLayout(swatch_row)

        palette_label = QLabel("Palette")
        palette_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(palette_label)

        wheel_row = QHBoxLayout()
        wheel_row.addStretch(1)
        self.color_wheel = ColorWheel()
        self.color_wheel.colorPicked.connect(self._set_color)
        self._color_pickers.append(self.color_wheel)
        wheel_row.addWidget(self.color_wheel)
        wheel_row.addStretch(1)
        column.addLayout(wheel_row)

        return column

    def _build_channel_column(self):
        column = QVBoxLayout()
        self.r_slider, self.r_spin = self._build_channel_row(column, "R")
        self.g_slider, self.g_spin = self._build_channel_row(column, "G")
        self.b_slider, self.b_spin = self._build_channel_row(column, "B")

        presets_row = QHBoxLayout()
        for rgb in PRESET_COLORS:
            button = QPushButton()
            button.setFixedSize(24, 24)
            button.setStyleSheet(
                f"background-color: rgb{rgb}; border: 1px solid black;"
            )
            button.clicked.connect(lambda checked=False, rgb=rgb: self._set_color(QColor(*rgb)))
            self._color_pickers.append(button)
            presets_row.addWidget(button)
        presets_row.addStretch(1)
        column.addLayout(presets_row)

        return column

    def _build_channel_row(self, parent_layout, label_text: str):
        row = QHBoxLayout()
        row.addWidget(QLabel(label_text))

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 255)
        row.addWidget(slider, stretch=1)

        spin = QSpinBox()
        spin.setRange(0, 255)
        row.addWidget(spin)

        # Slider <-> spin box are kept in sync directly; Qt only re-emits
        # valueChanged when the value actually changes, so this can't loop.
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(self._on_channel_changed)

        parent_layout.addLayout(row)
        self._color_pickers.append(slider)
        self._color_pickers.append(spin)
        return slider, spin

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

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)
        self._sync_actions()

    # -- color ------------------------------------------------------------

    def _update_swatch(self) -> None:
        self.color_swatch.setStyleSheet(f"background-color: {self._color.name()};")

    def _set_color(self, color: QColor) -> None:
        self._color = color
        for widget, value in (
            (self.r_slider, color.red()), (self.r_spin, color.red()),
            (self.g_slider, color.green()), (self.g_spin, color.green()),
            (self.b_slider, color.blue()), (self.b_spin, color.blue()),
        ):
            blocked = widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(blocked)
        self._update_swatch()

    def _on_channel_changed(self, _value: int) -> None:
        self._set_color(QColor(self.r_slider.value(), self.g_slider.value(), self.b_slider.value()))

    def _on_colorful_toggled(self, checked: bool) -> None:
        # "Colorful" (kb_protocol's confirmed 0x06 "colourful" effect) cycles
        # its own colors, so the pickers here don't apply to it.
        for widget in self._color_pickers:
            widget.setEnabled(not checked)

    def rgb(self) -> tuple[int, int, int]:
        return (self._color.red(), self._color.green(), self._color.blue())

    # -- actions ------------------------------------------------------------

    def _on_apply_color(self) -> None:
        if self.colorful_checkbox.isChecked():
            # Colorful cycles its own colors and ignores a custom per-key
            # upload (that's why the pickers are disabled while it's
            # checked) -- Apply just selects it, with no color_transfer.
            transactions = kb_protocol.build_effect_transfer(
                COLORFUL_EFFECT_ID, rgb=self.rgb(),
                speed=kb_protocol.EFFECT_SPEED_DEFAULT, brightness=kb_protocol.EFFECT_BRIGHTNESS_MAX,
            )
        else:
            # Per protocol.py's own note on EFFECT_CUSTOM: the vendor app
            # always selects custom (per-key) mode alongside a colour
            # upload, seen whenever its per-key editor was open. Without it
            # the keyboard can still be mid-built-in-effect and ignore the
            # colour write.
            custom_mode = kb_protocol.build_effect_transfer(
                kb_protocol.EFFECT_CUSTOM, rgb=self.rgb(),
                speed=kb_protocol.EFFECT_SPEED_DEFAULT, brightness=kb_protocol.EFFECT_BRIGHTNESS_MAX,
            )
            colors = kb_protocol.build_uniform_colors(self.rgb())
            transactions = custom_mode + kb_protocol.build_color_transfer(colors)
        self._run_transactions(transactions)

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
        self._set_busy(False)
