"""Entry point: python3 -m aula_l99_gui.main (run from tools/, or via uv run)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from aula_l99_gui import theme
from aula_l99_gui.main_window import MainWindow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AULA L99 GUI")
    parser.add_argument(
        "--tray",
        action="store_true",
        help="Add a system tray/app indicator icon.",
    )
    parser.add_argument(
        "--start-hidden",
        action="store_true",
        help="Start hidden and keep running in the tray. Requires --tray.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    app = QApplication(sys.argv)
    if args.tray and not QSystemTrayIcon.isSystemTrayAvailable():
        print(
            "Warning: system tray is unavailable on this platform. Starting normally.",
            file=sys.stderr,
        )
        args.tray = False
        args.start_hidden = False
    if args.tray:
        app.setQuitOnLastWindowClosed(False)

    QCoreApplication.setOrganizationName("AULA_L99")
    QCoreApplication.setApplicationName("AULA_L99")
    # Before any widget exists: the font has to be in the database by the time
    # the stylesheet naming it is applied.
    font_family = theme.load_font()
    if font_family:
        app.setFont(QFont(font_family, -1))   # -1: leave the point size to QSS
    app.setStyleSheet(theme.stylesheet(font_family))
    window = MainWindow(tray_enabled=args.tray)
    if not args.start_hidden:
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
