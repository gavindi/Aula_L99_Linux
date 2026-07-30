"""Config tab: currently just the consolidated debug log every other
control tab writes into instead of keeping its own isolated log widget."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QPlainTextEdit, QVBoxLayout, QWidget

from .debug_log import DebugLog


class ConfigTab(QWidget):
    busy_changed = Signal(bool)  # never emitted; keeps main_window's tab interface uniform

    def __init__(self, debug_log: DebugLog) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        group = QGroupBox("Debug Log")
        group_layout = QVBoxLayout(group)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        group_layout.addWidget(self.log)
        layout.addWidget(group)

        debug_log.message.connect(self.log.appendPlainText)
        debug_log.cleared.connect(self.log.clear)

    @property
    def is_busy(self) -> bool:
        return False
