"""Device tab: picks which hidraw node / serial port the other tabs act on.

Both control tabs used to carry their own copy of this picker. They now share
the two selectors built here, and learn about the current device only through
`DeviceSelector.changed`.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aula_l99_hacky import protocol as kb_protocol
from aula_l99_hacky.device import find_l99
from aula_l99_screen.device import find_screen

from . import theme
from .device_utils import (
    KEYBOARD_PERMISSION_HINT,
    describe_keyboard,
    describe_screen,
    list_keyboard_candidates,
    list_screen_devices,
)
from .workers import KeyboardWorker, start_worker

DONGLE_UNSUPPORTED_MESSAGE = (
    "This tool only implements the wired 0C45:800A path; "
    "the dongle's packet format has never been captured."
)

KEYBOARD_LAYOUT_IMAGE = theme.THEME / "keyboard" / "img_keyboard_layout.png"

# How often the Device tab re-enumerates on its own, so a plug/unplug shows up
# without the user having to hit Refresh -- on top of the explicit refresh
# MainWindow does when this tab becomes current (see MainWindow._on_tab_changed).
POLL_INTERVAL_MS = 5000

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

    changed = Signal(str, bool, bool)  # status text, actions enabled, known device found

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
        self._found = False

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
        # A known VID:PID match (cable, dongle, or screen), independent of
        # `enabled` -- the dongle is recognized but unsupported for actions,
        # yet it's still "our" hardware plugged in over USB.
        self._found = index >= 0
        self.status_label.setText(status)
        self.changed.emit(status, enabled, self._found)

    def current_path(self) -> str | None:
        index = self.device_combo.currentIndex()
        if 0 <= index < len(self._devices):
            return self._devices[index].path
        return None

    def _on_combo_changed(self) -> None:
        self.changed.emit(self._status, self._enabled, self._found)


class DeviceTab(QWidget):
    """Hosts both selectors. Does not refresh on construction -- MainWindow
    calls refresh_all() once the control tabs have connected to `changed`,
    otherwise they'd miss the first emission and sit disabled forever."""

    def __init__(self) -> None:
        super().__init__()
        self._thread = None
        self._worker = None
        self._busy = False
        self._keyboard_ready = False

        layout = QVBoxLayout(self)

        self.keyboard = DeviceSelector(
            "Keyboard", list_keyboard_candidates, describe_keyboard, _resolve_keyboard
        )
        self.screen = DeviceSelector(
            "Touchscreen", list_screen_devices, describe_screen, _resolve_screen
        )
        layout.addWidget(self.keyboard)
        layout.addWidget(self.screen)
        layout.addWidget(self._build_connection_group())
        layout.addWidget(self._build_keyboard_image())
        layout.addStretch(1)

        self.keyboard.changed.connect(self._on_keyboard_changed)

        # Background poll so a plug/unplug shows up on its own; MainWindow
        # additionally calls refresh_all() the moment this tab becomes
        # current, so switching here doesn't wait out the rest of this tick.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self.refresh_all)
        self._poll_timer.start()

    def _build_keyboard_image(self) -> QLabel:
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(KEYBOARD_LAYOUT_IMAGE))
        if not pixmap.isNull():
            pixmap = pixmap.scaledToWidth(640, Qt.TransformationMode.SmoothTransformation)
        label.setPixmap(pixmap)
        label.setVisible(False)
        self.keyboard_image = label
        return label

    def _build_connection_group(self) -> QGroupBox:
        group = QGroupBox("Connection")
        row = QHBoxLayout(group)
        self.test_connection_button = QPushButton("Test Connection")
        self.test_connection_button.setEnabled(False)
        self.test_connection_button.clicked.connect(self._on_handshake)
        row.addWidget(self.test_connection_button)
        row.addStretch(1)
        return group

    def refresh_all(self) -> None:
        self.keyboard.refresh()
        self.screen.refresh()

    # -- connection test --------------------------------------------------

    def _on_keyboard_changed(self, status: str, enabled: bool) -> None:
        self._keyboard_ready = enabled
        self.keyboard_image.setVisible(enabled)
        self._sync_connection_button()

    def _sync_connection_button(self) -> None:
        self.test_connection_button.setEnabled(self._keyboard_ready and not self._busy)

    def _on_handshake(self) -> None:
        if self._busy:
            return
        device_path = self.keyboard.current_path()
        if device_path is None:
            QMessageBox.warning(self, "Keyboard", "No device selected.")
            return

        self._busy = True
        self._sync_connection_button()

        # See lighting_tab.py's _run_transactions for why `_worker`/`_thread`
        # are kept referenced until `thread.finished` (not `worker.finished`)
        # and why `_busy` is only cleared there.
        self._worker = KeyboardWorker(device_path, kb_protocol.build_cable_handshake())
        self._worker.finished.connect(self._on_handshake_finished)
        self._thread = start_worker(self._worker)
        self._thread.finished.connect(self._on_thread_stopped)

    def _on_handshake_finished(self, success: bool, message: str) -> None:
        if success:
            QMessageBox.information(self, "Keyboard", "Connection OK.")
            return
        text = message
        if "permission" in message.lower():
            text = f"{message}\n\n{KEYBOARD_PERMISSION_HINT}"
        QMessageBox.critical(self, "Keyboard Error", text)

    def _on_thread_stopped(self) -> None:
        self._busy = False
        self._sync_connection_button()

    @property
    def is_busy(self) -> bool:
        return self._busy
