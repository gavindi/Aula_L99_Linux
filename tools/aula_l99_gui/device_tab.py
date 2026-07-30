"""Device tab: picks which hidraw node / serial port the other tabs act on.

Both control tabs used to carry their own copy of this picker. They now share
the two selectors built here, and learn about the current device only through
`DeviceSelector.changed`.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aula_l99_hacky.device import find_l99
from aula_l99_screen.device import find_screen

from .device_utils import (
    describe_keyboard,
    describe_screen,
    list_keyboard_candidates,
    list_screen_devices,
)

DONGLE_UNSUPPORTED_MESSAGE = (
    "This tool only implements the wired 0C45:800A path; "
    "the dongle's packet format has never been captured."
)

# resolve(devices) -> (index to preselect or -1, status text, actions enabled)
Resolver = Callable[[list], tuple[int, str, bool]]


def _resolve_keyboard(devices: list) -> tuple[int, str, bool]:
    try:
        found = find_l99()
    except FileNotFoundError:
        return -1, "No AULA L99 keyboard found. Plug it in and click Refresh.", False

    index = next((i for i, d in enumerate(devices) if d.path == found.path), -1)
    if found.is_dongle:
        return index, DONGLE_UNSUPPORTED_MESSAGE, False
    return index, f"Using {found.path} (cable)", True


def _resolve_screen(devices: list) -> tuple[int, str, bool]:
    try:
        found = find_screen()
    except FileNotFoundError:
        return -1, "No AULA L99 touchscreen found. Plug it in and click Refresh.", False

    index = next((i for i, d in enumerate(devices) if d.path == found.path), -1)
    return index, f"Using {found.path}", True


class DeviceSelector(QGroupBox):
    """Combo + Refresh + status line for one device family."""

    changed = Signal(str, bool)  # status text, actions enabled

    def __init__(
        self,
        title: str,
        list_devices: Callable[[], list],
        describe: Callable[[object], str],
        resolve: Resolver,
    ) -> None:
        super().__init__(title)
        self._list_devices = list_devices
        self._describe = describe
        self._resolve = resolve
        self._devices: list = []
        self._status = ""
        self._enabled = False

        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        self.device_combo = QComboBox()
        row.addWidget(self.device_combo, stretch=1)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        row.addWidget(refresh_button)
        layout.addLayout(row)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # A manual pick changes which node the control tabs will act on, so
        # their status lines have to follow it, not just the auto-detection.
        self.device_combo.currentIndexChanged.connect(self._on_combo_changed)

    def refresh(self) -> None:
        self._devices = self._list_devices()

        # Repopulating the combo fires currentIndexChanged; suppress it so the
        # only `changed` emission for a refresh is the authoritative one below.
        blocked = self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for device in self._devices:
            self.device_combo.addItem(self._describe(device))
        index, status, enabled = self._resolve(self._devices)
        if index >= 0:
            self.device_combo.setCurrentIndex(index)
        self.device_combo.blockSignals(blocked)

        self._status = status
        self._enabled = enabled
        self.status_label.setText(status)
        self.changed.emit(status, enabled)

    def current_path(self) -> str | None:
        index = self.device_combo.currentIndex()
        if 0 <= index < len(self._devices):
            return self._devices[index].path
        return None

    def _on_combo_changed(self) -> None:
        self.changed.emit(self._status, self._enabled)


class DeviceTab(QWidget):
    """Hosts both selectors. Does not refresh on construction -- MainWindow
    calls refresh_all() once the control tabs have connected to `changed`,
    otherwise they'd miss the first emission and sit disabled forever."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        self.keyboard = DeviceSelector(
            "Keyboard", list_keyboard_candidates, describe_keyboard, _resolve_keyboard
        )
        self.screen = DeviceSelector(
            "Touchscreen", list_screen_devices, describe_screen, _resolve_screen
        )
        layout.addWidget(self.keyboard)
        layout.addWidget(self.screen)
        layout.addStretch(1)

    def refresh_all(self) -> None:
        self.keyboard.refresh()
        self.screen.refresh()
