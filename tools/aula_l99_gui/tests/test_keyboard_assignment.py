"""Keyboard-tab key assignment: the dialog's Apply/Cancel/X behaviour, and
the tab opening it for an overlay key click and writing the remap only on
Apply.

These instantiate real Qt widgets, so they run under an offscreen QPA platform
and guard on PySide6 being importable.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal  # noqa: E402
from PySide6.QtWidgets import QDialog, QPushButton  # noqa: E402

import aula_l99_gui.keyboard_tab as keyboard_tab  # noqa: E402
from aula_l99_gui.debug_log import DebugLog  # noqa: E402
from aula_l99_gui.key_assignment_dialog import KeyAssignmentDialog  # noqa: E402
from aula_l99_gui.keyboard_tab import KeyboardTab  # noqa: E402
from aula_l99_hacky import protocol as kb_protocol  # noqa: E402


class _StubSelector(QObject):
    """The slice of DeviceSelector KeyboardTab touches: `changed` and
    current_path()."""

    changed = Signal(str, bool)

    def __init__(self) -> None:
        super().__init__()
        self._path = "/dev/hidraw7"

    def current_path(self) -> str | None:
        return self._path


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def tab(app):
    tab = KeyboardTab(_StubSelector(), DebugLog())
    yield tab
    tab.shutdown()


def _mark_device_ready(tab) -> None:
    tab._selector.changed.emit("/dev/hidraw7", True)


# -- the dialog ---------------------------------------------------------------

def test_dialog_offers_one_key_type_and_names_the_clicked_key(app):
    dialog = KeyAssignmentDialog("capslock")
    assert dialog.windowTitle().endswith("capslock")
    assert dialog.type_combo.count() == 1
    assert dialog.type_combo.currentText() == "Key Function"
    assert dialog.type_combo.currentData() == kb_protocol.KEY_ENTRY_KEY


def test_dialog_apply_resolves_the_typed_key(app):
    dialog = KeyAssignmentDialog("capslock")
    dialog.key_edit.setText("esc")
    dialog.apply_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.hid_usage == 0x29


def test_dialog_apply_accepts_hex_too(app):
    dialog = KeyAssignmentDialog("pause")
    dialog.key_edit.setText("0x4c")
    dialog.apply_button.click()
    assert dialog.hid_usage == 0x4C


def test_dialog_apply_with_unknown_name_warns_and_stays_open(app, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        "aula_l99_gui.key_assignment_dialog.QMessageBox.warning",
        lambda *args: warnings.append(args))
    dialog = KeyAssignmentDialog("capslock")
    dialog.key_edit.setText("bogus")
    dialog.apply_button.click()
    assert len(warnings) == 1
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.hid_usage is None


def test_dialog_cancel_closes_without_applying(app):
    dialog = KeyAssignmentDialog("capslock")
    dialog.key_edit.setText("esc")
    dialog.cancel_button.click()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.hid_usage is None


def test_dialog_close_button_is_reject_too(app):
    """The title-bar X closes the dialog like Cancel -- QDialog turns a close
    into reject(), which must leave nothing applied."""
    dialog = KeyAssignmentDialog("capslock")
    dialog.key_edit.setText("esc")
    dialog.close()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.hid_usage is None


def test_dialog_is_frameless_with_a_close_only_title_bar(app):
    """The popup matches the main window's chrome: frameless (Qt cannot skin
    native title bars, so the dialog draws its own), with a close button and
    no minimise/maximise."""
    dialog = KeyAssignmentDialog("capslock")
    assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
    buttons = dialog.title_bar.findChildren(QPushButton)
    assert [b.objectName() for b in buttons] == ["TitleCloseButton"]


def test_dialog_title_bar_close_button_rejects(app):
    dialog = KeyAssignmentDialog("capslock")
    dialog.key_edit.setText("esc")
    dialog.title_bar.findChildren(QPushButton)[0].click()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.hid_usage is None


# -- the tab wiring -----------------------------------------------------------

class _StubDialog:
    """Stands in for KeyAssignmentDialog inside keyboard_tab: records what it
    was constructed with; exec() applies its canned outcome."""
    instances: list["_StubDialog"] = []
    accepted = True

    def __init__(self, key_name: str, parent=None) -> None:
        self.key_name = key_name
        self.parent = parent
        self.hid_usage = None
        _StubDialog.instances.append(self)

    def exec(self) -> int:
        if _StubDialog.accepted:
            self.hid_usage = 0x29
            return QDialog.DialogCode.Accepted
        return QDialog.DialogCode.Rejected


@pytest.fixture
def stub_dialog(monkeypatch):
    _StubDialog.instances = []
    _StubDialog.accepted = True
    monkeypatch.setattr(keyboard_tab, "KeyAssignmentDialog", _StubDialog)
    return _StubDialog


def test_clicking_a_key_opens_the_dialog_and_writes_the_remap(tab, stub_dialog):
    started: list = []
    tab._run_transactions = started.append
    _mark_device_ready(tab)
    tab.overlay.keyClicked.emit(55)

    assert len(stub_dialog.instances) == 1
    assert stub_dialog.instances[0].key_name == "capslock"  # HID name, not ".>"
    assert len(started) == 1
    transactions = started[0]
    assert [tx.name for tx in transactions] == (
        ["begin", "key-remap"]
        + [f"key-remap-block{i}" for i in range(kb_protocol.KEY_PROFILE_BLOCK_COUNT)]
        + ["commit", "end"])
    cmd = transactions[1].outgoing
    assert cmd[:2] == bytes([kb_protocol.CMD_PREFIX, kb_protocol.OP_KEY_PROFILE])
    payload = b"".join(tx.outgoing
                       for tx in transactions[2:2 + kb_protocol.KEY_PROFILE_BLOCK_COUNT])
    assert payload[55 * 4:55 * 4 + 4] == bytes([0x02, 0x00, 0x29, 0x00])


def test_dialog_reject_writes_nothing(tab, stub_dialog):
    started: list = []
    tab._run_transactions = started.append
    stub_dialog.accepted = False
    _mark_device_ready(tab)
    tab.overlay.keyClicked.emit(55)
    assert len(stub_dialog.instances) == 1
    assert started == []


def test_deselect_click_opens_nothing(tab, stub_dialog):
    started: list = []
    tab._run_transactions = started.append
    _mark_device_ready(tab)
    tab.overlay.keyClicked.emit(-1)
    assert stub_dialog.instances == []
    assert started == []


def test_no_dialog_while_a_write_is_in_flight(tab, stub_dialog):
    _mark_device_ready(tab)
    tab._set_busy(True)
    tab.overlay.keyClicked.emit(55)
    assert stub_dialog.instances == []
