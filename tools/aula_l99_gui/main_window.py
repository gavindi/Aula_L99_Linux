"""Top-level window hosting the device, keyboard and screen tabs."""
from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QMessageBox, QTabWidget

from .device_tab import DeviceTab
from .keyboard_tab import KeyboardTab
from .screen_tab import ScreenTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AULA L99 Control")
        self.resize(800, 720)

        self._device_tab = DeviceTab()
        self._keyboard_tab = KeyboardTab(self._device_tab.keyboard)
        self._screen_tab = ScreenTab(self._device_tab.screen)

        tabs = QTabWidget()
        tabs.addTab(self._device_tab, "Device")
        tabs.addTab(self._keyboard_tab, "Keyboard")
        tabs.addTab(self._screen_tab, "Touchscreen")
        self.setCentralWidget(tabs)

        # Only after both control tabs have connected to their selector's
        # `changed` signal -- refreshing any earlier means they never receive
        # the initial status and sit disabled with a blank status line.
        self._device_tab.refresh_all()

    def closeEvent(self, event) -> None:
        # An interrupted screen upload can freeze the panel (see
        # aula_l99_screen/cli.py's own warning); refuse to close mid-transfer
        # rather than let Qt tear down a QThread that's still running.
        if self._keyboard_tab.is_busy or self._screen_tab.is_busy:
            QMessageBox.warning(
                self, "AULA L99 Control",
                "An operation is still in progress. Wait for it to finish "
                "before closing -- interrupting a screen upload can freeze "
                "the panel.",
            )
            event.ignore()
            return
        event.accept()
