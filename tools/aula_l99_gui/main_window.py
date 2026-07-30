"""Top-level window hosting the device, keyboard and screen tabs."""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionTab,
    QStylePainter,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .device_tab import DeviceTab
from .keyboard_tab import KeyboardTab
from .lighting_tab import LightingTab
from .touchscreen_tab import TouchscreenTab
from .user_lighting_tab import UserLightingTab


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
        icon_size = self.iconSize()
        for index in range(self.count()):
            self.initStyleOption(option, index)
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabShape, option)
            # CE_TabBarTabLabel lays icon+text out left-aligned (with a west-facing
            # rotation to boot), which never centred the icon even before the
            # buttons lost their border/background. Drawing the pixmap straight
            # into the middle of the tab rect sidesteps the style's label layout
            # (and the rotation) entirely.
            icon = self.tabIcon(index)
            if icon.isNull():
                continue
            icon_rect = QRect(0, 0, icon_size.width(), icon_size.height())
            icon_rect.moveCenter(option.rect.center())
            painter.drawPixmap(icon_rect, icon.pixmap(icon_size))


class TitleBar(QWidget):
    """Stand-in for the OS title bar the frameless window gives up: vendor
    logo, current-tab mode label, centred wordmark, minimize/close.

    Dragged via QWindow.startSystemMove() -- hand-rolled move()-on-drag
    doesn't work at all under Wayland, which (unlike X11) doesn't let a
    client reposition its own top-level window directly; startSystemMove()
    asks the compositor/WM to perform the move itself and is honoured by
    both.
    """

    def __init__(self, window: QMainWindow) -> None:
        super().__init__()
        self.setObjectName("TitleBar")
        self.setFixedHeight(theme.TITLE_BAR_HEIGHT)
        self._window = window

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)

        logo = QLabel()
        logo.setPixmap(QPixmap(str(theme.LOGO_IMAGE)))
        layout.addWidget(logo)

        self.mode_label = QLabel()
        self.mode_label.setObjectName("TitleModeLabel")
        layout.addWidget(self.mode_label)

        layout.addStretch(1)

        center_label = QLabel("AULA L99")
        center_label.setObjectName("TitleCenterLabel")
        layout.addWidget(center_label)

        layout.addStretch(1)

        self.usb_icon = QLabel()
        self.usb_icon.setPixmap(QPixmap(str(theme.USB_MODE_ICON)))
        self.usb_icon.setVisible(False)
        layout.addWidget(self.usb_icon)

        min_button = QPushButton()
        min_button.setObjectName("TitleMinButton")
        min_button.setFixedSize(theme.TITLE_BUTTON_SIZE)
        min_button.clicked.connect(window.showMinimized)
        layout.addWidget(min_button)

        close_button = QPushButton()
        close_button.setObjectName("TitleCloseButton")
        close_button.setFixedSize(theme.TITLE_BUTTON_SIZE)
        close_button.clicked.connect(window.close)
        layout.addWidget(close_button)

    def set_mode(self, text: str) -> None:
        self.mode_label.setText(text)

    def set_usb_connected(self, connected: bool) -> None:
        self.usb_icon.setVisible(connected)

    def set_usb_tooltip(self, text: str) -> None:
        self.usb_icon.setToolTip(text)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None and handle.startSystemMove():
                return
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AULA L99 Control")
        # Frameless so the custom title bar below can stand in for the OS
        # one -- Qt can't skin native window chrome. Fixed size rather than
        # hand-rolling edge-drag resizing (frameless windows have no native
        # resize grips), matching the vendor app's own non-resizable window.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setFixedSize(1200, 800)
        self.setWindowIcon(QIcon(str(theme.THEME / "DeviceDriver.ico")))

        # Loaded once; paintEvent re-scales it per resize rather than re-reading.
        self._background = QPixmap(str(theme.BACKGROUND_IMAGE))

        self._device_tab = DeviceTab()
        self._device_tab.setObjectName("DeviceTab")
        self._keyboard_tab = KeyboardTab(self._device_tab.keyboard)
        self._lighting_tab = LightingTab(self._device_tab.keyboard)
        self._user_lighting_tab = UserLightingTab(self._device_tab.keyboard)
        self._touchscreen_tab = TouchscreenTab(self._device_tab.screen)

        self._tabs = QTabWidget()
        self._tabs.setTabBar(SidebarTabBar())
        self._tabs.setTabPosition(QTabWidget.TabPosition.West)

        # The rail is icon-only, so the titles can't live in the tab text any
        # more -- they're kept here for the icon lookup and shown as tooltips,
        # which is the only thing naming an unlabelled button for the user.
        self._tab_titles = ["Device", "Keyboard", "Lighting", "User Lighting", "Touchscreen"]
        for widget, title in zip(
            (
                self._device_tab, self._keyboard_tab, self._lighting_tab,
                self._user_lighting_tab, self._touchscreen_tab,
            ),
            self._tab_titles,
        ):
            index = self._tabs.addTab(widget, "")
            self._tabs.setTabIcon(index, self._tab_icon(title))
            self._tabs.setTabToolTip(index, title)
        self._tabs.setIconSize(theme.TAB_ICON_SIZE)

        self._title_bar = TitleBar(self)
        self._keyboard_found = False
        self._screen_found = False
        self._keyboard_status = ""
        self._screen_status = ""
        self._device_tab.keyboard.changed.connect(self._on_keyboard_presence)
        self._device_tab.screen.changed.connect(self._on_screen_presence)

        self._tabs.currentChanged.connect(self._refresh_tab_icons)
        self._refresh_tab_icons(self._tabs.currentIndex())  # currentChanged

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._title_bar)
        central_layout.addWidget(self._tabs)
        self.setCentralWidget(central)

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
        if 0 <= current < len(self._tab_titles):
            self._title_bar.set_mode(f"{self._tab_titles[current]} Mode")
        # Immediate refresh on switching to the Device tab, on top of its own
        # background poll (see device_tab.POLL_INTERVAL_MS) -- otherwise the
        # tab could show up-to-5s-stale state right after switching to it.
        if self._tabs.widget(current) is self._device_tab:
            self._device_tab.refresh_all()

    def _on_keyboard_presence(self, status: str, _enabled: bool, found: bool) -> None:
        self._keyboard_found = found
        self._keyboard_status = status
        self._update_usb_icon()

    def _on_screen_presence(self, status: str, _enabled: bool, found: bool) -> None:
        self._screen_found = found
        self._screen_status = status
        self._update_usb_icon()

    def _update_usb_icon(self) -> None:
        # Any recognized AULA L99 hardware over USB -- cable keyboard, dongle
        # (even though it's unsupported for actions), or touchscreen -- not
        # just the subset that's actionable.
        self._title_bar.set_usb_connected(self._keyboard_found or self._screen_found)
        # Replaces the per-tab status line the control tabs used to mirror
        # from the Device tab's selectors -- both statuses combined here
        # since one icon now speaks for both devices.
        self._title_bar.set_usb_tooltip(f"{self._keyboard_status}\n{self._screen_status}")

    def paintEvent(self, event) -> None:
        theme.paint_background(self, self._background)
        super().paintEvent(event)

    def closeEvent(self, event) -> None:
        # An interrupted screen upload can freeze the panel (see
        # aula_l99_screen/cli.py's own warning); refuse to close mid-transfer
        # rather than let Qt tear down a QThread that's still running.
        if (
            self._device_tab.is_busy
            or self._keyboard_tab.is_busy
            or self._lighting_tab.is_busy
            or self._user_lighting_tab.is_busy
            or self._touchscreen_tab.is_busy
        ):
            QMessageBox.warning(
                self, "AULA L99 Control",
                "An operation is still in progress. Wait for it to finish "
                "before closing -- interrupting a screen upload can freeze "
                "the panel.",
            )
            event.ignore()
            return
        event.accept()
