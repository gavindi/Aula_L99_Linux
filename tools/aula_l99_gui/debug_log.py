"""Shared debug log: every control tab's status/progress messages,
consolidated into the Config tab instead of each tab keeping its own
isolated log widget."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class DebugLog(QObject):
    message = Signal(str)
    cleared = Signal()

    def append(self, source: str, text: str) -> None:
        self.message.emit(f"[{source}] {text}")

    def clear(self) -> None:
        self.cleared.emit()
