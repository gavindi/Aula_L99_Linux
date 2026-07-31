"""User Lighting tab: color picking (wheel/RGB/presets) plus "Apply to All
Keys", "Apply to Selected Key" (via the clickable KeyboardOverlay), and a
"Read Current Colours" diagnostic that paints the overlay with what's
actually lit on the hardware right now.

Entirely self-contained -- its color state and Colorful checkbox affect only
this tab's own Apply actions, not the Lighting tab's Run Effect (which has
its own separate copy of the same controls in lighting_tab.py).
"""
from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET

import defusedxml.ElementTree as safe_ET
from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
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

from . import key_layout
from .color_wheel import ColorWheel
from .debug_log import DebugLog
from .device_tab import DeviceSelector
from .device_utils import KEYBOARD_PERMISSION_HINT
from .keyboard_overlay import KeyboardOverlay
from .workers import CallableResultWorker, KeyboardWorker, read_colors, start_worker

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

FILE_PANEL_WIDTH = 220

# What the vendor app writes into <lightinfo> for a per-key preset. Nothing
# ever sends these to the keyboard -- they exist so a file we save still opens
# in the vendor app.
LIGHTINFO_SPEED = "15"
# `lightmode` is 4 on every item of every vendor-saved file seen so far; its
# other values are unknown, so saves just reproduce it.
ITEM_LIGHTMODE = "4"


def _user_lighting_dir() -> pathlib.Path:
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    save_dir = pathlib.Path(base) / "User_Lighting"
    save_dir.mkdir(parents=True, exist_ok=True)
    return save_dir


def _next_lighting_name(save_dir: pathlib.Path) -> str:
    best = 0
    for path in save_dir.glob("UserLighting*.xml"):
        digits = path.stem[len("UserLighting"):]
        if digits.isdigit():
            best = max(best, int(digits))
    return f"UserLighting{best + 1}"


def _load_lighting_xml(path: pathlib.Path) -> dict[int, tuple[int, int, int]]:
    """Parse a vendor `customlight` file into {key_id: rgb}.

    The file keys its items by HID usage code, not by the light_index/key_id
    the protocol speaks, so every keycode goes back through key_layout. Items
    naming a code this keyboard doesn't have are skipped rather than fatal --
    the format is shared across vendor models.
    """
    root = safe_ET.parse(path).getroot()
    if root.tag != "customlight":
        raise ValueError(f"not a customlight file (root is <{root.tag}>)")

    colors: dict[int, tuple[int, int, int]] = {}
    keyinfo = root.find("keyinfo")
    for item in [] if keyinfo is None else keyinfo.findall("item"):
        key_id = key_layout.KEY_ID_BY_HID.get(int(item.get("keycode", "-1")))
        if key_id is None:
            continue
        rgb = int(item.get("rgbvalue", "0"))
        colors[key_id] = ((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF)
    return colors


def _save_lighting_xml(
    path: pathlib.Path, colors: dict[int, tuple[int, int, int]]
) -> None:
    root = ET.Element("customlight")
    ET.SubElement(root, "lightinfo", name=path.stem, speed=LIGHTINFO_SPEED)
    keyinfo = ET.SubElement(root, "keyinfo")
    for key_id in kb_protocol.KEY_IDS:
        red, green, blue = colors.get(key_id, (0, 0, 0))
        ET.SubElement(
            keyinfo,
            "item",
            keycode=str(key_layout.HID_BY_KEY_ID[key_id]),
            lightmode=ITEM_LIGHTMODE,
            rgbvalue=str((red << 16) | (green << 8) | blue),
            type="0",
        )
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


class UserLightingTab(QWidget):
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
        self._selected_key: int | None = None
        self._read_worker = None
        self._read_thread = None
        # Last full 84-key table this tab knows about, from whichever of an
        # apply, a colour read or a loaded file happened most recently. Saving
        # writes this; None means nothing has established one yet.
        self._key_colors: dict[int, tuple[int, int, int]] | None = None
        self._file_colors: dict[int, tuple[int, int, int]] | None = None

        self._build_ui()
        selector.changed.connect(self._on_device_changed)
        self._refresh_file_list()

    # -- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.addWidget(self._build_file_panel())

        controls = QVBoxLayout()
        overlay_row = QHBoxLayout()
        overlay_row.addStretch(1)
        overlay_row.addWidget(self._build_overlay())
        overlay_row.addStretch(1)
        controls.addLayout(overlay_row)

        controls.addWidget(self._build_color_group())

        self.progress_bar = QProgressBar()
        controls.addWidget(self.progress_bar)
        controls.addStretch(1)
        layout.addLayout(controls)

    def _build_file_panel(self) -> QGroupBox:
        group = QGroupBox("Saved Lighting")
        group.setMaximumWidth(FILE_PANEL_WIDTH)
        layout = QVBoxLayout(group)

        self.file_list = QListWidget()
        self.file_list.currentItemChanged.connect(self._on_file_selected)
        layout.addWidget(self.file_list)

        self.apply_file_button = QPushButton("Apply to Keyboard")
        self.apply_file_button.clicked.connect(self._on_apply_file)
        self.apply_file_button.setEnabled(False)
        layout.addWidget(self.apply_file_button)

        save_button = QPushButton("Save Current")
        save_button.clicked.connect(self._on_save_current)
        layout.addWidget(save_button)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._refresh_file_list)
        layout.addWidget(refresh_button)

        return group

    # -- saved lighting files ----------------------------------------------

    def _refresh_file_list(self) -> None:
        self.file_list.clear()
        for path in sorted(_user_lighting_dir().glob("*.xml"), key=lambda p: p.name.lower()):
            item = QListWidgetItem(path.stem)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.file_list.addItem(item)

    def _on_file_selected(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        # Selecting only loads -- it paints the overlay and arms "Apply to
        # Keyboard" without writing anything, so browsing the list can't
        # disturb what the keyboard is currently showing.
        self._file_colors = None
        if current is not None:
            path = pathlib.Path(current.data(Qt.ItemDataRole.UserRole))
            try:
                colors = _load_lighting_xml(path)
            except (OSError, ValueError, ET.ParseError) as exc:
                self._debug_log.append("User Lighting", f"-- load {path.name} failed: {exc}")
                QMessageBox.critical(self, "Load Error", f"Could not read {path.name}:\n{exc}")
            else:
                self._file_colors = colors
                self._key_colors = dict(colors)
                self.overlay.set_swatches(colors)
                self._debug_log.append(
                    "User Lighting", f"-- loaded {path.name}: {len(colors)} keys"
                )
        self._sync_actions()

    def _on_apply_file(self) -> None:
        if self._file_colors is None:
            return
        # Keys the file didn't mention are written as off rather than left
        # alone: build_color_transfer always sends the whole 84-key table, so
        # there is no "unchanged" to leave them at.
        colors = {key_id: (0, 0, 0) for key_id in kb_protocol.KEY_IDS}
        colors.update(self._file_colors)
        self._key_colors = colors
        self.overlay.set_swatches(colors)
        self._run_transactions(self._build_custom_transactions(colors))

    def _on_save_current(self) -> None:
        save_dir = _user_lighting_dir()
        name, accepted = QInputDialog.getText(
            self, "Save Lighting", "Name:", text=_next_lighting_name(save_dir)
        )
        name = name.strip()
        if not accepted or not name:
            return

        path = save_dir / f"{name}.xml"
        if path.exists():
            confirm = QMessageBox.question(
                self, "Save Lighting", f"{path.name} already exists. Overwrite it?"
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

        # Nothing has established a full table yet (no apply, read or load this
        # session), so the only colour this tab can honestly claim is the one
        # in the picker.
        colors = self._key_colors or kb_protocol.build_uniform_colors(self.rgb())
        try:
            _save_lighting_xml(path, colors)
        except OSError as exc:
            self._debug_log.append("User Lighting", f"-- save {path.name} failed: {exc}")
            QMessageBox.critical(self, "Save Error", f"Could not write {path.name}:\n{exc}")
            return

        self._debug_log.append("User Lighting", f"-- saved {path.name}")
        self._refresh_file_list()
        for row in range(self.file_list.count()):
            if self.file_list.item(row).text() == path.stem:
                self.file_list.setCurrentRow(row)
                break

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

        self.apply_selected_button = QPushButton("Apply to Selected Key")
        self.apply_selected_button.clicked.connect(self._on_apply_selected_key)
        self.apply_selected_button.setEnabled(False)
        outer.addWidget(self.apply_selected_button)

        read_button = QPushButton("Read Current Colours")
        read_button.clicked.connect(self._on_read_colors)
        outer.addWidget(read_button)
        self._action_buttons.append(read_button)

        return group

    def _build_overlay(self) -> KeyboardOverlay:
        overlay = KeyboardOverlay()
        overlay.keyClicked.connect(self._on_key_selected)
        self.overlay = overlay
        return overlay

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
        self.apply_selected_button.setEnabled(
            enabled and self._selected_key is not None and not self.colorful_checkbox.isChecked()
        )
        self.apply_file_button.setEnabled(enabled and self._file_colors is not None)

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
        self._sync_actions()

    def _on_key_selected(self, key_id: int) -> None:
        self._selected_key = None if key_id < 0 else key_id
        self._sync_actions()

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
            self._key_colors = None
        else:
            colors = kb_protocol.build_uniform_colors(self.rgb())
            transactions = self._build_custom_transactions(colors)
            self._key_colors = colors
        self.overlay.clear_swatches()
        self._run_transactions(transactions)

    def _build_custom_transactions(self, colors: dict[int, tuple[int, int, int]]) -> list:
        # Per protocol.py's own note on EFFECT_CUSTOM: the vendor app always
        # selects custom (per-key) mode alongside a colour upload, seen
        # whenever its per-key editor was open. Without it the keyboard can
        # still be mid-built-in-effect and ignore the colour write.
        custom_mode = kb_protocol.build_effect_transfer(
            kb_protocol.EFFECT_CUSTOM, rgb=self.rgb(),
            speed=kb_protocol.EFFECT_SPEED_DEFAULT, brightness=kb_protocol.EFFECT_BRIGHTNESS_MAX,
        )
        return custom_mode + kb_protocol.build_color_transfer(colors)

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
        self._debug_log.append("User Lighting", f"{name}: {'ok' if acked else 'NOT ACKED'}")

    def _on_finished(self, success: bool, message: str) -> None:
        self._debug_log.append("User Lighting", f"-- {message}")
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

    def _on_apply_selected_key(self) -> None:
        # Single-key colour changes need read-modify-write: build_color_transfer
        # writes the *entire* 84-key table, so a bare {key: rgb} dict would
        # blank every other key. Stage 1 reads the current table; stage 2
        # (_on_read_for_apply_finished) merges the one change and writes it
        # back. Busy spans both stages -- only the stage-2 write's
        # thread.finished clears it, so this stage deliberately does not wire
        # up _on_thread_stopped.
        if self._busy or self._selected_key is None:
            return
        device_path = self._selector.current_path()
        if device_path is None:
            QMessageBox.warning(self, "Keyboard", "No device selected.")
            return

        self._set_busy(True)
        self.progress_bar.setRange(0, 0)
        self._debug_log.clear()

        self._read_worker = CallableResultWorker(lambda: read_colors(device_path))
        self._read_worker.finished.connect(self._on_read_for_apply_finished)
        self._read_thread = start_worker(self._read_worker)

    def _on_read_for_apply_finished(self, colors: object, error: str) -> None:
        if error or set(colors) != set(kb_protocol.KEY_IDS):
            message = error or (
                f"incomplete colour read ({len(colors)}/{len(kb_protocol.KEY_IDS)} keys) "
                f"-- refusing to write, since a partial table would blank the rest"
            )
            self._debug_log.append("User Lighting", f"-- read failed: {message}")
            QMessageBox.critical(self, "Keyboard Error", message)
            self._set_busy(False)
            return

        device_path = self._selector.current_path()
        colors[self._selected_key] = self.rgb()
        self._key_colors = dict(colors)
        transactions = self._build_custom_transactions(colors)

        self.progress_bar.setRange(0, max(len(transactions), 1))
        self.progress_bar.setValue(0)
        self.overlay.clear_swatches()

        self._worker = KeyboardWorker(device_path, transactions)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._thread = start_worker(self._worker)
        self._thread.finished.connect(self._on_thread_stopped)

    def _on_read_colors(self) -> None:
        if self._busy:
            return
        device_path = self._selector.current_path()
        if device_path is None:
            QMessageBox.warning(self, "Keyboard", "No device selected.")
            return

        self._set_busy(True)
        self.progress_bar.setRange(0, 0)
        self._debug_log.clear()

        self._read_worker = CallableResultWorker(lambda: read_colors(device_path))
        self._read_worker.finished.connect(self._on_read_colors_finished)
        self._read_thread = start_worker(self._read_worker)
        self._read_thread.finished.connect(self._on_thread_stopped)

    def _on_read_colors_finished(self, colors: object, error: str) -> None:
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        if error:
            self._debug_log.append("User Lighting", f"-- read failed: {error}")
            QMessageBox.critical(self, "Keyboard Error", error)
        else:
            self._debug_log.append("User Lighting", "-- read current colours: ok")
            self._key_colors = dict(colors)
            self.overlay.set_swatches(colors)
