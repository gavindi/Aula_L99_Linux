"""Lighting (aula_l99_hacky) control tab: built-in effect selection, with
its own color controls (wheel/RGB/presets) for whatever effect is running.

Entirely self-contained -- this tab's color state and Colorful checkbox
affect only its own Run Effect action, not the User Lighting tab's Apply
action (which has its own separate copy of the same controls in
user_lighting_tab.py).

No colour polling here, unlike keyboard_tab.py -- confirmed on hardware that
OP_COLOR_QUERY, even sequenced strictly after a Run Effect write (never
overlapping it), silently reverts the keyboard back out of the just-applied
built-in effect. The overlay below is a static image only.
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
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from aula_l99_hacky import protocol as kb_protocol

from . import theme
from .color_wheel import ColorWheel
from .debug_log import DebugLog
from .device_tab import DeviceSelector
from .device_utils import KEYBOARD_PERMISSION_HINT
from .keyboard_overlay import KeyboardOverlay
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

# Rows the effect list is guaranteed, before the layout hands it the tab's
# spare height.
EFFECT_LIST_MIN_ROWS = 8


class LightingTab(QWidget):
    busy_changed = Signal(bool)

    def __init__(self, selector: DeviceSelector, debug_log: DebugLog) -> None:
        super().__init__()
        self._selector = selector
        self._debug_log = debug_log
        self._thread = None
        self._worker = None
        self._busy = False
        self._device_ready = False
        self._color = QColor(255, 0, 0)
        self._action_buttons: list[QPushButton] = []
        self._color_pickers: list[QWidget] = []
        self._pre_colorful_index: int | None = None

        self._build_ui()
        selector.changed.connect(self._on_device_changed)

    # -- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        # The effect list is a column of its own spanning the full height of
        # the tab, with the keyboard image and the controls stacked beside it.
        # It used to sit under the image, in a row that gave it about a third
        # of the window -- not enough for 21 effects, so it scrolled.
        layout = QHBoxLayout(self)
        layout.addWidget(self._build_effect_list_group())

        column = QVBoxLayout()
        overlay_row = QHBoxLayout()
        overlay_row.addStretch(1)
        overlay_row.addWidget(self._build_overlay())
        overlay_row.addStretch(1)
        column.addLayout(overlay_row)

        column.addLayout(self._build_controls_column())

        self.progress_bar = QProgressBar()
        column.addWidget(self.progress_bar)
        layout.addLayout(column, stretch=1)

    def _build_overlay(self) -> KeyboardOverlay:
        overlay = KeyboardOverlay()
        overlay.setVisible(False)
        self.overlay = overlay
        return overlay

    def _build_effect_list_group(self) -> QGroupBox:
        group = QGroupBox()
        # Same width as the User Lighting tab's list panes, so the left edge of
        # the window doesn't jump when switching between the two tabs.
        group.setFixedWidth(theme.SIDE_PANEL_WIDTH)
        layout = QVBoxLayout(group)

        self.effect_list = QListWidget()
        for effect_id, name in sorted(kb_protocol.EFFECT_NAMES.items()):
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, effect_id)
            self.effect_list.addItem(item)
        self.effect_list.setCurrentRow(0)
        self.effect_list.itemDoubleClicked.connect(self._on_run_effect)
        # A floor of EFFECT_LIST_MIN_ROWS rows only -- the list is the full
        # height of the tab now (see _build_ui), so the space it actually gets
        # comes from the window, not from this. Keeping the floor small means a
        # shorter window squeezes nothing: it just scrolls, as it must.
        row_height = self.effect_list.sizeHintForRow(0)
        frame = 2 * self.effect_list.frameWidth()
        rows = min(EFFECT_LIST_MIN_ROWS, self.effect_list.count())
        self.effect_list.setMinimumHeight(row_height * rows + frame)
        layout.addWidget(self.effect_list)

        return group

    def _build_controls_column(self) -> QVBoxLayout:
        column = QVBoxLayout()

        self.brightness_slider = self._build_labeled_slider(
            column, "Lighting Brightness", 1, kb_protocol.EFFECT_BRIGHTNESS_MAX,
            kb_protocol.EFFECT_BRIGHTNESS_MAX,
        )
        self.speed_slider = self._build_labeled_slider(
            column, "Lighting Speed", kb_protocol.EFFECT_SPEED_MIN,
            kb_protocol.EFFECT_SPEED_MAX, kb_protocol.EFFECT_SPEED_DEFAULT,
        )

        column.addWidget(self._build_color_group())

        run_button = QPushButton("Run Effect")
        run_button.clicked.connect(self._on_run_effect)
        column.addWidget(run_button)
        self._action_buttons.append(run_button)

        # The row's stretch belongs to the effect list, not to the gaps between
        # these controls -- this keeps them packed at the top the way the
        # trailing stretch in _build_ui used to.
        column.addStretch(1)

        return column

    def _build_labeled_slider(
        self, parent_layout, title: str, minimum: int, maximum: int, default: int
    ) -> QSlider:
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
        self.overlay.setVisible(enabled)
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

    def _find_effect_row(self, effect_id: int) -> int:
        for row in range(self.effect_list.count()):
            if self.effect_list.item(row).data(Qt.ItemDataRole.UserRole) == effect_id:
                return row
        return -1

    def _on_colorful_toggled(self, checked: bool) -> None:
        # "Colorful" (kb_protocol's confirmed 0x06 "colourful" effect) cycles
        # its own colors, so the pickers here don't apply to it -- forcing
        # the Effect selection instead of adding a second control that does
        # the same thing as the list.
        for widget in self._color_pickers:
            widget.setEnabled(not checked)
        if checked:
            self._pre_colorful_index = self.effect_list.currentRow()
            colorful_row = self._find_effect_row(COLORFUL_EFFECT_ID)
            if colorful_row >= 0:
                self.effect_list.setCurrentRow(colorful_row)
            self.effect_list.setEnabled(False)
        else:
            self.effect_list.setEnabled(True)
            if self._pre_colorful_index is not None:
                self.effect_list.setCurrentRow(self._pre_colorful_index)
                self._pre_colorful_index = None

    def _rgb(self) -> tuple[int, int, int]:
        return (self._color.red(), self._color.green(), self._color.blue())

    # -- actions ------------------------------------------------------------

    def _on_run_effect(self) -> None:
        item = self.effect_list.currentItem()
        if item is None:
            QMessageBox.warning(self, "Keyboard", "No effect selected.")
            return
        effect_id = item.data(Qt.ItemDataRole.UserRole)
        transactions = kb_protocol.build_effect_transfer(
            effect_id,
            rgb=self._rgb(),
            speed=self.speed_slider.value(),
            brightness=self.brightness_slider.value(),
        )
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
        self._debug_log.clear()

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
        self._debug_log.append("Lighting", f"{name}: {'ok' if acked else 'NOT ACKED'}")

    def _on_finished(self, success: bool, message: str) -> None:
        self._debug_log.append("Lighting", f"-- {message}")
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
