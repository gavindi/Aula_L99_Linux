"""The assignment dialog behind a key click on the Keyboard tab.

KeyboardOverlay only reports *that* a key was clicked (and draws the selection
border); this dialog is what KeyboardTab opens in response. One control row --
the "Key Type" dropdown, whose single entry is the one remap type decoded from
the vendor app ("Key Function", protocol KEY_ENTRY_KEY) -- and, to its right,
the field where the key to act as is typed. Apply validates that text through
kb_protocol.resolve_hid_usage() and only then accepts; Cancel and the title-bar
X both close without applying anything.

Like MainWindow it is frameless: Qt cannot skin native window chrome, so the
dialog draws its own title strip -- black like the main window's, with only
the vendor close button (no minimise/maximise on a modal popup).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aula_l99_hacky import protocol as kb_protocol

from . import theme


class _TitleBar(QWidget):
    """The dialog's own title strip: bold title on the main window's black,
    and the same 30x30 vendor close art -- nothing else.

    Dragging mirrors main_window.TitleBar: QWindow.startSystemMove(), because
    hand-rolled move()-on-drag doesn't work under Wayland.
    """

    def __init__(self, dialog: QDialog, title: str) -> None:
        super().__init__()
        self.setObjectName("TitleBar")
        self.setFixedHeight(theme.TITLE_BAR_HEIGHT)
        self._dialog = dialog

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 8, 0)
        row.setSpacing(8)

        label = QLabel(title)
        label.setObjectName("TitleModeLabel")
        row.addWidget(label)
        row.addStretch(1)

        close_button = QPushButton()
        close_button.setObjectName("TitleCloseButton")
        close_button.setFixedSize(theme.TITLE_BUTTON_SIZE)
        close_button.clicked.connect(dialog.reject)
        row.addWidget(close_button)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._dialog.windowHandle()
            if handle is not None and handle.startSystemMove():
                return
        super().mousePressEvent(event)


class KeyAssignmentDialog(QDialog):
    """Configure what one physical key should do. After exec() returns
    Accepted, hid_usage holds the resolved target keyboard usage."""

    def __init__(self, key_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("KeyAssignmentDialog")
        self.setWindowTitle(f"Assign Key \u2014 {key_name}")
        self.setModal(True)
        # Frameless: the _TitleBar below stands in for the OS chrome the way
        # the main window's does (see its class docstring there for why the
        # native bar can't just be recoloured instead).
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.hid_usage: int | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.title_bar = _TitleBar(self, f"Assign Key \u2014 {key_name}")
        outer.addWidget(self.title_bar)

        layout = QVBoxLayout()
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.addWidget(QLabel("Key Type:"))
        self.type_combo = QComboBox()
        # The vendor app's panel offers more types (multimedia, disable,
        # macro, ...) whose wire encodings mostly await captures; only the
        # plain key remap is offered until they are decoded -- see
        # re_notes/key_remap_macros.md.
        self.type_combo.addItem("Key Function", kb_protocol.KEY_ENTRY_KEY)
        row.addWidget(self.type_combo)

        row.addSpacing(18)
        row.addWidget(QLabel("Assign to key:"))
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("e.g. Esc, F1, space, 0x29")
        row.addWidget(self.key_edit, stretch=1)
        layout.addLayout(row)

        hint = QLabel("The clicked key acts as the key named above.")
        hint.setEnabled(False)
        layout.addWidget(hint)
        layout.addSpacing(4)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(self._on_apply)
        buttons.addWidget(self.apply_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

        outer.addLayout(layout)

    def _on_apply(self) -> None:
        try:
            self.hid_usage = kb_protocol.resolve_hid_usage(self.key_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Assign Key", str(exc))
            return
        self.accept()
