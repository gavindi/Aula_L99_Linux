"""Top-level window hosting the device, keyboard and screen tabs."""
from __future__ import annotations

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QStyle,
    QStyleOptionTab,
    QStylePainter,
    QTabBar,
    QTabWidget,
)

from . import theme
from .device_tab import DeviceTab
from .keyboard_tab import KeyboardTab
from .screen_tab import ScreenTab


class SidebarTabBar(QTabBar):
    """A `West` tab bar that keeps its labels upright.

    Qt rotates both the tab shape and its label 90 degrees for a left-hand tab
    bar, which turns the sidebar into sideways text and stands the vendor icons
    on their side. Drawing the shape rotated but the label as if it were a top
    tab gives an ordinary vertical sidebar.
    """

    def tabSizeHint(self, index: int):
        # Fixed rather than derived from super(): Qt computes a West tab's hint
        # in a rotated frame, so the stylesheet's own sizing lands on the wrong
        # axis -- a QSS min-width would become the button's vertical extent.
        return theme.SIDEBAR_TAB_SIZE

    def paintEvent(self, event) -> None:
        painter = QStylePainter(self)
        option = QStyleOptionTab()
        for index in range(self.count()):
            self.initStyleOption(option, index)
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabShape, option)
            # Claiming the tab faces north for the label pass only is what stops
            # Qt standing the icon on its side; the shape above was already drawn
            # with the real (west) orientation. The buttons carry no text, so the
            # icon just centres in the rect.
            option.shape = QTabBar.Shape.RoundedNorth
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabLabel, option)


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
        self._tabs.setTabBar(SidebarTabBar())
        self._tabs.setTabPosition(QTabWidget.TabPosition.West)

        # The rail is icon-only, so the titles can't live in the tab text any
        # more -- they're kept here for the icon lookup and shown as tooltips,
        # which is the only thing naming an unlabelled button for the user.
        self._tab_titles = ["Device", "Keyboard", "Touchscreen"]
        for widget, title in zip(
            (self._device_tab, self._keyboard_tab, self._screen_tab),
            self._tab_titles,
        ):
            index = self._tabs.addTab(widget, "")
            self._tabs.setTabIcon(index, self._tab_icon(title))
            self._tabs.setTabToolTip(index, title)
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
        for index, title in enumerate(self._tab_titles):
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
