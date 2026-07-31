"""Entry point: python3 -m aula_l99_gui.main (run from tools/, or via uv run)."""
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from aula_l99_gui import theme
from aula_l99_gui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    QCoreApplication.setOrganizationName("AULA_L99")
    QCoreApplication.setApplicationName("AULA_L99")
    # Before any widget exists: the font has to be in the database by the time
    # the stylesheet naming it is applied.
    font_family = theme.load_font()
    if font_family:
        app.setFont(QFont(font_family, -1))   # -1: leave the point size to QSS
    app.setStyleSheet(theme.stylesheet(font_family))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
