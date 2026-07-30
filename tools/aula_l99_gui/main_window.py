"""Top-level window hosting the device, keyboard and screen tabs."""
from __future__ import annotations

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QMainWindow, QMessageBox, QTabWidget

from . import theme
from .device_tab import DeviceTab
from .keyboard_tab import KeyboardTab
from .screen_tab import ScreenTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AULA L99 Control")
        self.resize(800, 720)
        self.setWindowIcon(QIcon(str(theme.THEME / "DeviceDriver.ico")))

        # Loaded once; paintEvent re-scales it per resize rather than re-reading.
        self._background = QPixmap(str(theme.BACKGROUND_IMAGE))

        self._device_tab = DeviceTab()
        self._device_tab.setObjectName("DeviceTab")
        self._keyboard_tab = KeyboardTab(self._device_tab.keyboard)
        self._screen_tab = ScreenTab(self._device_tab.screen)

        self._tabs = QTabWidget()
        for widget, title in (
            (self._device_tab, "Device"),
            (self._keyboard_tab, "Keyboard"),
            (self._screen_tab, "Touchscreen"),
        ):
            index = self._tabs.addTab(widget, title)
            self._tabs.setTabIcon(index, self._tab_icon(title))
        self._tabs.setIconSize(theme.TAB_ICON_SIZE)
        self._tabs.currentChanged.connect(self._refresh_tab_icons)
        self._refresh_tab_icons(self._tabs.currentIndex())  # currentChanged
        self.setCentralWidget(self._tabs)                   # won't fire for tab 0

        # Only after both control tabs have connected to their selector's
        # `changed` signal -- refreshing any earlier means they never receive
        # the initial status and sit disabled with a blank status line.
        self._device_tab.refresh_all()

    # -- skin -------------------------------------------------------------

    def _tab_icon(self, title: str, selected: bool = False) -> QIcon:
        unselected_path, selected_path = theme.tab_icon_paths(title)
        return QIcon(str(selected_path if selected else unselected_path))

    def _refresh_tab_icons(self, current: int) -> None:
        # QIcon has no "selected tab" state Qt will pick up on its own, so the
        # orange frame of the vendor strip is swapped in by hand.
        for index in range(self._tabs.count()):
            title = self._tabs.tabText(index)
            self._tabs.setTabIcon(index, self._tab_icon(title, index == current))

    def paintEvent(self, event) -> None:
        theme.paint_background(self, self._background)
        super().paintEvent(event)

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
