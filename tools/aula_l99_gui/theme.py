"""The vendor skin: `main_bkg.png` behind the window plus a Qt stylesheet
driven by the sliced sprite art in `assets/skins/theme1/slices/`.

Colours here are the vendor's own, sampled from the sheets: accent #EF6C00
(hover), #CF4D00 (pressed), grey #808080 for disabled. The background image is
near-black, so every text role has to be set explicitly -- the platform palette
would otherwise leave dark-on-dark labels.

`slice_skin.py` regenerates the slices this module points at.
"""
from __future__ import annotations

import pathlib

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter, QPixmap

ASSETS = pathlib.Path(__file__).resolve().parent / "assets"
THEME = ASSETS / "skins" / "theme1"
SLICES = THEME / "slices"
ICONS = THEME / "icon"

ACCENT = "#EF6C00"
ACCENT_PRESSED = "#CF4D00"
TEXT = "#E6E6E6"
TEXT_DISABLED = "#808080"
CONTENT = "#0A0A0C"                  # log/list/preview; must stay fully opaque
PANEL_BORDER = "rgba(150, 150, 160, 90)"

BACKGROUND_IMAGE = THEME / "main_bkg.png"
LOGO_IMAGE = THEME / "logo" / "logo.png"
USB_MODE_ICON = ICONS / "usb_mode.png"

TITLE_BAR_HEIGHT = 40
TITLE_BAR_BG = "rgba(10, 10, 12, 235)"
TITLE_BUTTON_SIZE = QSize(30, 30)

# Icon strip -> tab, using the vendor's own tab art. `_pressed` is the
# fully-saturated orange frame, which reads as "current tab".
TAB_ICONS = {
    "Device": "tab_home",
    "Keyboard": "tab_customkey",
    "Lighting": "tab_light",
    "Touchscreen": "tab_tft",
}
# The strip frames are 36x36, so 40px upscales them by ~11% -- close enough to
# native that the softness doesn't show, and it keeps the rail on round numbers.
TAB_ICON_SIZE = QSize(40, 40)
# The rail is icon-only, with each button twice its icon's size. Derived rather
# than hardcoded so the 2x relationship survives a change to TAB_ICON_SIZE.
# Set here rather than in the stylesheet because Qt applies QSS
# min-width/min-height in a West tab bar's rotated frame.
SIDEBAR_TAB_SIZE = QSize(TAB_ICON_SIZE.width() * 2, TAB_ICON_SIZE.height() * 2)


def _url(path: pathlib.Path) -> str:
    """Qt stylesheet url(). Forward slashes on every platform."""
    return f"url({path.as_posix()})"


def _slice(stem: str, state: str) -> str:
    return _url(SLICES / f"{stem}_{state}.png")


def tab_icon_paths(name: str) -> tuple[pathlib.Path, pathlib.Path]:
    """(unselected, selected) icon frames for a tab title."""
    stem = TAB_ICONS[name]
    return SLICES / f"{stem}_normal.png", SLICES / f"{stem}_pressed.png"


def background_pixmap(size, source: QPixmap) -> QPixmap:
    """Cover-scale `source` to `size`, anchored to the bottom.

    Scaling by expanding preserves the 16:9 aspect ratio (the window is
    resizable and rarely 16:9), and anchoring low keeps the bright blue grid --
    the only part of the image with any detail -- on screen instead of cropping
    it away below the fold.
    """
    if size.isEmpty() or source.isNull():
        return QPixmap()
    scaled = source.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = (scaled.width() - size.width()) // 2
    y = max(scaled.height() - size.height(), 0)
    return scaled.copy(x, y, size.width(), size.height())


def paint_background(widget, source: QPixmap) -> None:
    """Draw the cover-scaled background across `widget`. Call from paintEvent."""
    pixmap = background_pixmap(widget.size(), source)
    if pixmap.isNull():
        return
    painter = QPainter(widget)
    painter.drawPixmap(0, 0, pixmap)


def stylesheet() -> str:
    return f"""
/* Let the window's background image show through the containers. */
QMainWindow, QTabWidget::pane, QTabBar, QWidget#DeviceTab {{
    background: transparent;
}}
QTabWidget::pane {{
    border: none;
    left: -1px;
}}
/* Keep the sidebar packed at the top instead of centred down the edge. */
QTabWidget::tab-bar {{
    alignment: left;
    top: 0;
}}

QWidget {{
    color: {TEXT};
    font-size: 12px;
}}
QWidget:disabled {{
    color: {TEXT_DISABLED};
}}

/* Sidebar tabs: vendor icons, orange edge on the current one. Size comes from
   SidebarTabBar.tabSizeHint, not from min-width/min-height here -- Qt applies
   those in the rotated coordinate space of a West bar, where a "width" turns
   into the tab's vertical extent and gives absurdly tall tabs. */
QTabBar::tab {{
    background: transparent;
    border: none;
    margin-bottom: 2px;
}}
QTabBar::tab:selected {{
    color: {ACCENT};
}}

/* Group boxes transparent so the starfield shows straight through. */
QGroupBox {{
    background: transparent;
    border: none;
    border-radius: 4px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    color: {ACCENT};
}}

/* Buttons: 100x30 pill, 4 states. The 20px side slices keep the rounded caps
   undistorted while the middle stretches to whatever width the layout gives. */
QPushButton {{
    border-image: {_slice("btn_apply", "normal")} 0 20 0 20 stretch stretch;
    border-left: 20px transparent;
    border-right: 20px transparent;
    min-height: 30px;
    min-width: 40px;
    padding: 0 6px;
    color: {TEXT};
}}
QPushButton:hover {{
    border-image: {_slice("btn_apply", "hover")} 0 20 0 20 stretch stretch;
    color: #1A1A1A;
}}
QPushButton:pressed {{
    border-image: {_slice("btn_apply", "pressed")} 0 20 0 20 stretch stretch;
    color: #1A1A1A;
}}
QPushButton:disabled {{
    border-image: {_slice("btn_apply", "disabled")} 0 20 0 20 stretch stretch;
    color: {TEXT_DISABLED};
}}

/* Combo box art already contains its own drop-down arrow on the right, so the
   native one is blanked out and the text is inset clear of it. */
QComboBox {{
    border-image: {_slice("img_combobox", "normal")} 0 26 0 26 stretch stretch;
    border-left: 26px transparent;
    border-right: 26px transparent;
    min-height: 30px;
    padding-left: 4px;
    padding-right: 26px;
    color: {TEXT};
}}
QComboBox:hover {{
    border-image: {_slice("img_combobox", "hover")} 0 26 0 26 stretch stretch;
    color: #1A1A1A;
}}
QComboBox:on {{
    border-image: {_slice("img_combobox", "pressed")} 0 26 0 26 stretch stretch;
    color: #1A1A1A;
}}
QComboBox:disabled {{
    border-image: {_slice("img_combobox", "disabled")} 0 26 0 26 stretch stretch;
    color: {TEXT_DISABLED};
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox::down-arrow {{
    image: none;
}}
QComboBox QAbstractItemView {{
    background: #14141A;
    border: 1px solid {PANEL_BORDER};
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: #1A1A1A;
    outline: none;
}}

/* Content panels sit over the brightest part of the background image (the blue
   grid fills the lower third), so these are fully opaque -- at any of the
   translucency used for the group-box cards the grid shows through the log
   text and the frame list and costs real legibility. */
QSpinBox, QPlainTextEdit, QListWidget, QLabel#ImagePreview {{
    background: {CONTENT};
    border: 1px solid {PANEL_BORDER};
    border-radius: 3px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: #1A1A1A;
}}
QLabel#ImagePreview {{
    color: {TEXT_DISABLED};
}}
QSpinBox {{
    min-height: 24px;
    padding: 0 4px;
}}
QSpinBox:hover {{
    border: 1px solid {ACCENT};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    width: 18px;
    border: none;
    background: transparent;
}}
QSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-arrow {{ image: {_url(ICONS / "icon_input_up.png")}; width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: {_url(ICONS / "icon_input_down.png")}; width: 10px; height: 10px; }}

QListWidget::item {{
    padding: 3px 6px;
}}
QListWidget::item:selected {{
    background: {ACCENT};
    color: #1A1A1A;
}}

QCheckBox, QRadioButton {{
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 30px;
    height: 30px;
}}
QCheckBox::indicator:unchecked {{ image: {_slice("btn_checkbox", "unchecked_normal")}; }}
QCheckBox::indicator:unchecked:hover {{ image: {_slice("btn_checkbox", "unchecked_hover")}; }}
QCheckBox::indicator:unchecked:pressed {{ image: {_slice("btn_checkbox", "unchecked_pressed")}; }}
QCheckBox::indicator:unchecked:disabled {{ image: {_slice("btn_checkbox", "unchecked_disabled")}; }}
QCheckBox::indicator:checked {{ image: {_slice("btn_checkbox", "checked_normal")}; }}
QCheckBox::indicator:checked:hover {{ image: {_slice("btn_checkbox", "checked_hover")}; }}
QCheckBox::indicator:checked:pressed {{ image: {_slice("btn_checkbox", "checked_pressed")}; }}
QCheckBox::indicator:checked:disabled {{ image: {_slice("btn_checkbox", "checked_disabled")}; }}

QRadioButton::indicator:unchecked {{ image: {_slice("btn_radiobox", "unchecked_normal")}; }}
QRadioButton::indicator:unchecked:hover {{ image: {_slice("btn_radiobox", "unchecked_hover")}; }}
QRadioButton::indicator:unchecked:pressed {{ image: {_slice("btn_radiobox", "unchecked_pressed")}; }}
QRadioButton::indicator:unchecked:disabled {{ image: {_slice("btn_radiobox", "unchecked_disabled")}; }}
QRadioButton::indicator:checked {{ image: {_slice("btn_radiobox", "checked_normal")}; }}
QRadioButton::indicator:checked:hover {{ image: {_slice("btn_radiobox", "checked_hover")}; }}
QRadioButton::indicator:checked:pressed {{ image: {_slice("btn_radiobox", "checked_pressed")}; }}
QRadioButton::indicator:checked:disabled {{ image: {_slice("btn_radiobox", "checked_disabled")}; }}

/* Progress bar reuses the slider track: grey groove, orange fill. */
QProgressBar {{
    border-image: {_slice("img_slider_back", "groove")} 0 10 0 10 stretch stretch;
    border-left: 10px transparent;
    border-right: 10px transparent;
    min-height: 22px;
    max-height: 22px;
    text-align: center;
    color: {TEXT};
}}
QProgressBar::chunk {{
    border-image: {_slice("img_slider_back", "chunk")} 0 10 0 10 stretch stretch;
    border-left: 10px transparent;
    border-right: 10px transparent;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    border-image: {_slice("img_scroll_v", "normal")} 4 0 4 0 stretch stretch;
    border-top: 4px transparent;
    border-bottom: 4px transparent;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    border-image: {_slice("img_scroll_v", "hover")} 4 0 4 0 stretch stretch;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
    border: none;
    height: 0;
}}

QToolTip {{
    background: #14141A;
    border: 1px solid {ACCENT};
    color: {TEXT};
    padding: 4px;
}}

/* Custom title bar, standing in for the OS one on a frameless window (see
   MainWindow.TitleBar) so the vendor logo/wordmark/system buttons can match
   the vendor app's own skin. */
QWidget#TitleBar {{
    background: {TITLE_BAR_BG};
}}
QLabel#TitleModeLabel {{
    font-weight: bold;
    color: {TEXT};
}}
QLabel#TitleCenterLabel {{
    color: {TEXT};
}}

/* Square icon buttons, not the stretchy pill from the generic QPushButton
   rule above -- border-image needs no side slices since the art is drawn at
   its native size with no stretching. */
QPushButton#TitleMinButton, QPushButton#TitleCloseButton {{
    min-width: 30px;
    max-width: 30px;
    min-height: 30px;
    max-height: 30px;
    padding: 0;
    border: none;
}}
QPushButton#TitleMinButton {{
    border-image: {_slice("main_sysbtn_min", "normal")} 0 0 0 0 stretch stretch;
}}
QPushButton#TitleMinButton:hover {{
    border-image: {_slice("main_sysbtn_min", "hover")} 0 0 0 0 stretch stretch;
}}
QPushButton#TitleMinButton:pressed {{
    border-image: {_slice("main_sysbtn_min", "pressed")} 0 0 0 0 stretch stretch;
}}
QPushButton#TitleCloseButton {{
    border-image: {_slice("main_sysbtn_close", "normal")} 0 0 0 0 stretch stretch;
}}
QPushButton#TitleCloseButton:hover {{
    border-image: {_slice("main_sysbtn_close", "hover")} 0 0 0 0 stretch stretch;
}}
QPushButton#TitleCloseButton:pressed {{
    border-image: {_slice("main_sysbtn_close", "pressed")} 0 0 0 0 stretch stretch;
}}
"""
