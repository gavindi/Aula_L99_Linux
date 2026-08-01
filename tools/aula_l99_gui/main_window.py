"""Top-level window hosting the device, keyboard and screen tabs."""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QRect, Qt
from PySide6.QtGui import QAction, QIcon, QMovie, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QMenu,
    QStyle,
    QStyleOptionTab,
    QStylePainter,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QSystemTrayIcon,
)

from . import settings, theme
from .config_tab import ConfigTab
from .debug_log import DebugLog
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

    def set_usb_icon(self, icon_path) -> None:
        pixmap = QPixmap(str(icon_path))
        if not pixmap.isNull():
            self.usb_icon.setPixmap(pixmap)

    def set_usb_tooltip(self, text: str) -> None:
        self.usb_icon.setToolTip(text)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None and handle.startSystemMove():
                return
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, tray_enabled: bool = False) -> None:
        super().__init__()
        self._tray_enabled = tray_enabled
        self._tray_quit_requested = False
        self._tray_icon = None

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

        self._debug_log = DebugLog()

        # Floating overlay, not part of any layout -- parented straight to
        # the window so it can sit centred over everything (title bar and
        # tab content alike) rather than just one tab's own area. Created
        # early, before any device refresh can emit a busy/monitoring signal:
        # _on_any_busy_changed touches it, and the first refresh below
        # (via _refresh_tab_icons) can fire while the auto-resumed monitor
        # stream starts.
        self._loading_movie = QMovie(str(theme.LOADING_GIF))
        self._loading_overlay = QLabel(self)
        self._loading_overlay.setMovie(self._loading_movie)
        self._loading_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._loading_overlay.setFixedSize(theme.LOADING_GIF_SIZE)
        self._loading_overlay.move(
            (self.width() - self._loading_overlay.width()) // 2,
            (self.height() - self._loading_overlay.height()) // 2,
        )
        self._loading_overlay.setVisible(False)

        self._device_tab = DeviceTab()
        self._device_tab.setObjectName("DeviceTab")
        self._keyboard_tab = KeyboardTab(self._device_tab.keyboard, self._debug_log)
        self._lighting_tab = LightingTab(self._device_tab.keyboard, self._debug_log)
        self._user_lighting_tab = UserLightingTab(self._device_tab.keyboard, self._debug_log)
        self._touchscreen_tab = TouchscreenTab(self._device_tab.screen, self._debug_log)
        self._config_tab = ConfigTab(self._device_tab.keyboard, self._debug_log)
        # The Config tab hosts the controls; KeyboardTab still does the work,
        # since it owns the poll thread an RTC write has to be sequenced
        # behind (see its module docstring).
        self._config_tab.set_clock_requested.connect(self._keyboard_tab.set_clock_now)
        self._config_tab.poll_interval_changed.connect(self._keyboard_tab.set_poll_interval)
        self._config_tab.monitor_toggled.connect(self._keyboard_tab.set_monitoring)
        self._keyboard_tab.monitoring_changed.connect(self._on_any_busy_changed)
        self._keyboard_tab.monitoring_changed.connect(self._on_monitor_state_changed)
        self._keyboard_tab.monitoring_changed.connect(self._config_tab._on_monitoring_changed)
        self._keyboard_tab.monitor_loaded.connect(self._config_tab._on_monitor_loaded)
        self._keyboard_tab.write_progress.connect(self._config_tab.show_write_progress)

        self._tabs = QTabWidget()
        self._tabs.setTabBar(SidebarTabBar())
        self._tabs.setTabPosition(QTabWidget.TabPosition.West)

        # The rail is icon-only, so the titles can't live in the tab text any
        # more -- they're kept here for the icon lookup and shown as tooltips,
        # which is the only thing naming an unlabelled button for the user.
        self._tab_titles = [
            "Device", "Keyboard", "Lighting", "User Lighting", "Touchscreen", "Config",
        ]
        for widget, title in zip(
            (
                self._device_tab, self._keyboard_tab, self._lighting_tab,
                self._user_lighting_tab, self._touchscreen_tab, self._config_tab,
            ),
            self._tab_titles,
        ):
            index = self._tabs.addTab(widget, "")
            self._tabs.setTabIcon(index, self._tab_icon(title))
            self._tabs.setTabToolTip(index, title)
        self._tabs.setIconSize(theme.TAB_ICON_SIZE)

        self._title_bar = TitleBar(self)
        if self._tray_enabled:
            self._create_tray_icon()
        self._keyboard_found = False
        self._keyboard_kind = ""
        self._screen_found = False
        self._keyboard_status = ""
        self._screen_status = ""
        # Only ever auto-resumes the saved monitor state once -- the first
        # time the keyboard shows up -- so an unplug/replug doesn't restart a
        # stream the user stopped in the meantime.
        self._monitor_auto_started = False
        self._device_tab.keyboard.changed.connect(self._on_keyboard_presence)
        self._device_tab.screen.changed.connect(self._on_screen_presence)

        self._tabs.currentChanged.connect(self._refresh_tab_icons)
        self._refresh_tab_icons(self._tabs.currentIndex())  # currentChanged

        # Re-raised here: setCentralWidget can reparent/restack central above
        # siblings added before it, which would otherwise bury the overlay
        # under the tab content it's supposed to float over.
        self._loading_overlay.raise_()

        for tab in (
            self._device_tab, self._keyboard_tab, self._lighting_tab,
            self._user_lighting_tab, self._touchscreen_tab, self._config_tab,
        ):
            tab.busy_changed.connect(self._on_any_busy_changed)
        # A User Lighting animation isn't "busy" -- it runs for minutes and
        # must not raise the loading overlay or block closing -- but colour
        # polling still has to stand off while it owns the hidraw handle, so it
        # goes through the same handler.
        self._user_lighting_tab.streaming_changed.connect(self._on_any_busy_changed)

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._title_bar)
        central_layout.addWidget(self._tabs)
        self.setCentralWidget(central)
        # Re-raised here: setCentralWidget can reparent/restack central above
        # siblings added before it, which would otherwise bury the overlay
        # under the tab content it's supposed to float over.
        self._loading_overlay.raise_()

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

    def _create_tray_icon(self) -> None:
        if self._tray_icon is not None:
            return
        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setIcon(self.windowIcon())
        self._tray_icon.setToolTip("AULA L99 Control")

        tray_menu = QMenu(self)
        show_action = QAction("Show", self)
        show_action.triggered.connect(self._show_window)
        tray_menu.addAction(show_action)

        hide_action = QAction("Hide", self)
        hide_action.triggered.connect(self.hide)
        tray_menu.addAction(hide_action)

        tray_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._tray_quit)
        tray_menu.addAction(quit_action)

        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()

    def _show_window(self) -> None:
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _tray_quit(self) -> None:
        self._tray_quit_requested = True
        if self._tray_icon is not None:
            self._tray_icon.hide()
        self.close()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_window()

    def _on_keyboard_presence(self, status: str, enabled: bool, found: bool,
                              kind: str) -> None:
        self._keyboard_found = found
        self._keyboard_kind = kind
        self._keyboard_status = status
        self._update_usb_icon()
        # Resume a monitor stream the previous run left running. Deferred
        # until the *cable* keyboard is actually usable (enabled) because the
        # stream is a cable-only feature -- the 2.4G dongle is recognized
        # (found) but can't carry it, and starting it while no device is
        # selected just raises a warning. The checkbox is restored for the
        # UI, and the stream is started explicitly rather than by relying on
        # the toggle signal: if the box is somehow already checked (the user
        # tried before the device was found), setChecked emits nothing and the
        # resume would silently not happen. Calling set_monitoring directly is
        # a harmless no-op when the start already happened through the signal.
        if enabled and not self._monitor_auto_started:
            self._monitor_auto_started = True
            if settings.monitor_running() and not self._keyboard_tab.is_monitoring:
                self._config_tab.monitor_toggle.setChecked(True)
                self._keyboard_tab.set_monitoring(True)

    def _on_monitor_state_changed(self, monitoring: bool) -> None:
        # Save whenever the stream's real state flips -- a user toggle and a
        # self-ended stream (transport failure) alike -- so the next run of
        # the GUI (or a headless daemon reading the same file) starts in the
        # same state. Deliberately NOT hooked to the toggle itself: a check
        # with no device to stream to isn't a state worth persisting.
        settings.set_monitor_running(monitoring)

    def _on_screen_presence(self, status: str, _enabled: bool, found: bool,
                            _kind: str) -> None:
        self._screen_found = found
        self._screen_status = status
        self._update_usb_icon()

    def _update_usb_icon(self) -> None:
        # Any recognized AULA L99 hardware over USB -- cable keyboard, dongle,
        # or touchscreen -- not just the subset that's actionable.
        connected = self._keyboard_found or self._screen_found
        self._title_bar.set_usb_connected(connected)
        if connected:
            # The keyboard's connection kind picks the badge: the 2.4G dongle
            # gets the radio-wave icon, everything else the USB plug.
            kind = self._keyboard_kind if self._keyboard_found else ""
            self._title_bar.set_usb_icon(theme.connection_icon(kind))
        # Replaces the per-tab status line the control tabs used to mirror
        # from the Device tab's selectors -- both statuses combined here
        # since one icon now speaks for both devices.
        self._title_bar.set_usb_tooltip(f"{self._keyboard_status}\n{self._screen_status}")

    def _on_any_busy_changed(self, _busy: bool) -> None:
        # Recomputes from every tab's own `is_busy` rather than trusting just
        # the `busy` this particular signal carried -- simpler than tracking
        # each tab's last-known state separately, and the reason this handler
        # is shared by all six tabs' `busy_changed` instead of one per tab.
        busy = (
            self._device_tab.is_busy
            or self._keyboard_tab.is_busy
            or self._lighting_tab.is_busy
            or self._user_lighting_tab.is_busy
            or self._touchscreen_tab.is_busy
            or self._config_tab.is_busy
        )
        self._loading_overlay.setVisible(busy)
        if busy:
            self._loading_movie.start()
        else:
            self._loading_movie.stop()

        # Colour polling (keyboard_tab.py) pauses for *any* upload in
        # progress, not just its own tab's -- another tab's transaction can
        # be holding the keyboard's hidraw handle open, and interleaving a
        # colour-query read with it could confuse the firmware's stateful
        # begin/commit/end session. A User Lighting animation and the
        # system-monitor stream both hold the handle for their whole run, so
        # they pause it too (but neither is "busy" -- see above).
        self._keyboard_tab.set_external_busy(
            busy
            or self._user_lighting_tab.is_streaming
            or self._keyboard_tab.is_monitoring,
        )
        # Same aggregate gates the Config tab's Set Clock button and monitor
        # toggle: the writes they start belong to KeyboardTab, so this tab
        # never sees them as its own.
        self._config_tab.set_external_busy(busy or self._keyboard_tab.is_monitoring)

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
            or self._config_tab.is_busy
        ):
            QMessageBox.warning(
                self, "AULA L99 Control",
                "An operation is still in progress. Wait for it to finish "
                "before closing -- interrupting a screen upload can freeze "
                "the panel.",
            )
            event.ignore()
            return

        if self._tray_enabled and not self._tray_quit_requested:
            self.hide()
            event.ignore()
            return

        # Colour polling isn't covered by the busy-check above (deliberately
        # -- it's frequent and lightweight, not worth nagging the user to
        # wait out), but its QThread still has to actually stop before this
        # window gets torn down, or Qt aborts the process on exit. A User
        # Lighting animation is outside that check for the same reason and
        # needs the same treatment.
        self._keyboard_tab.shutdown()
        self._user_lighting_tab.shutdown()
        if self._tray_icon is not None:
            self._tray_icon.hide()
        if self._tray_enabled and self._tray_quit_requested:
            QCoreApplication.quit()
        event.accept()
