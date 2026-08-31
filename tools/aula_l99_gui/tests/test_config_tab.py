"""Config tab tests: the Response Time and Sleep Time dropdowns are populated
from the protocol's decoded tables, changing one writes both slots and
persists, and restoring a saved state never writes to hardware.

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

from aula_l99_gui import settings  # noqa: E402
from aula_l99_gui.config_tab import ConfigTab  # noqa: E402
from aula_l99_gui.debug_log import DebugLog  # noqa: E402
from aula_l99_hacky import protocol as kb_protocol  # noqa: E402


class _StubSelector(QObject):
    """The slice of DeviceSelector ConfigTab touches: `changed` and
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
def tab(app, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    tab = ConfigTab(_StubSelector(), DebugLog())
    yield tab


def test_dropdowns_cover_every_wire_value(tab):
    assert tab.response_combo.count() == kb_protocol.RESPONSE_TIME_MAX
    assert tab.sleep_combo.count() == len(kb_protocol.SLEEP_TIME_MINUTES)
    assert [tab.response_combo.itemData(i) for i in range(tab.response_combo.count())] == list(
        range(kb_protocol.RESPONSE_TIME_MIN, kb_protocol.RESPONSE_TIME_MAX + 1))
    assert [tab.sleep_combo.itemData(i) for i in range(tab.sleep_combo.count())] == list(
        range(len(kb_protocol.SLEEP_TIME_MINUTES)))


def test_dropdown_labels(tab):
    assert tab.sleep_combo.itemText(0) == "No sleep"
    assert tab.sleep_combo.itemText(1) == "1 minute"
    assert tab.sleep_combo.itemText(2) == "5 minutes"
    assert tab.sleep_combo.itemText(3) == "30 minutes"
    assert tab.response_combo.itemText(0) == "Level 1"
    assert tab.response_combo.itemText(4) == "Level 5"
    assert "ms" in tab.response_combo.itemData(0, role=Qt.ToolTipRole)


def test_change_emits_both_wire_values(tab):
    received = []
    tab.settings_changed.connect(lambda response, sleep: received.append((response, sleep)))
    tab.response_combo.setCurrentIndex(3)   # level 4
    tab.sleep_combo.setCurrentIndex(2)      # 5 minutes
    assert received[-1] == (4, 2)


def test_change_persists(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    tab.response_combo.setCurrentIndex(4)   # level 5
    tab.sleep_combo.setCurrentIndex(3)      # 30 minutes
    assert settings.keyboard_settings() == {"response_time": 5, "sleep_time": 3}


def test_restores_saved_values_without_writing(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings.set_keyboard_settings({"response_time": 4, "sleep_time": 3})

    writes = []
    monkeypatch.setattr("aula_l99_gui.config_tab.settings.set_keyboard_settings",
                        lambda values: writes.append(values))
    fresh = ConfigTab(_StubSelector(), DebugLog())

    assert fresh.response_combo.currentData() == 4
    assert fresh.sleep_combo.currentData() == 3
    assert writes == [], "constructing the tab must not write to the keyboard"


def test_refresh_reloads_ledger_without_emitting(tab, monkeypatch, tmp_path):
    """Entering the tab re-reads the shared settings ledger -- written by the
    CLI or a previous GUI run -- and moves the dropdowns to match, with no
    signal and no write."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings.set_keyboard_settings({"response_time": 3, "sleep_time": 2})

    received = []
    writes = []
    tab.settings_changed.connect(lambda response, sleep: received.append((response, sleep)))
    monkeypatch.setattr("aula_l99_gui.config_tab.settings.set_keyboard_settings",
                        lambda values: writes.append(values))
    tab.refresh()

    assert tab.response_combo.currentData() == 3
    assert tab.sleep_combo.currentData() == 2
    assert received == []
    assert writes == []


def test_refresh_is_a_noop_when_values_unchanged(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    tab.response_combo.setCurrentIndex(2)
    tab.refresh()
    assert tab.response_combo.currentData() == 3


def test_defaults_to_first_dropdown_entries(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert tab.response_combo.currentData() == kb_protocol.RESPONSE_TIME_MIN
    assert tab.sleep_combo.currentData() == 0


def test_monitor_period_spinner_range_is_one_to_sixty_seconds(tab):
    assert tab.monitor_period_spin.minimum() == 1
    assert tab.monitor_period_spin.maximum() == 60


def test_monitor_period_defaults_to_five_seconds(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert tab.monitor_period_spin.value() == 5


def test_changing_monitor_period_persists_and_emits(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    received = []
    tab.monitor_period_changed.connect(received.append)
    tab.monitor_period_spin.setValue(20)
    assert received == [20]
    assert settings.monitor_period_seconds() == 20


def test_monitor_period_spinner_restores_saved_value(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings.set_monitor_period_seconds(45)
    fresh = ConfigTab(_StubSelector(), DebugLog())
    assert fresh.monitor_period_spin.value() == 45


def test_startup_checkboxes_default_state(tab):
    assert tab.start_on_login_check.isChecked() is False
    assert tab.start_hidden_check.isChecked() is True
    assert tab.start_hidden_check.isEnabled() is False


def test_startup_checkboxes_restore_saved_values(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings.set_start_on_login(True)
    settings.set_start_hidden(False)
    fresh = ConfigTab(_StubSelector(), DebugLog())
    assert fresh.start_on_login_check.isChecked() is True
    assert fresh.start_hidden_check.isChecked() is False
    assert fresh.start_hidden_check.isEnabled() is True


def test_constructing_tab_does_not_call_autostart_install_or_uninstall(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings.set_start_on_login(True)

    calls = []
    monkeypatch.setattr("aula_l99_gui.config_tab.autostart.install",
                        lambda hidden: calls.append(("install", hidden)))
    monkeypatch.setattr("aula_l99_gui.config_tab.autostart.uninstall",
                        lambda: calls.append(("uninstall",)))
    ConfigTab(_StubSelector(), DebugLog())

    assert calls == [], "constructing the tab must not write the autostart file"


def test_toggling_start_on_login_on_calls_install_and_persists(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr("aula_l99_gui.config_tab.autostart.install",
                        lambda hidden: calls.append(hidden))
    tab.start_on_login_check.setChecked(True)
    assert calls == [True]  # start_hidden defaults to True
    assert settings.start_on_login() is True


def test_toggling_start_on_login_off_calls_uninstall_and_persists(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("aula_l99_gui.config_tab.autostart.install", lambda hidden: None)
    tab.start_on_login_check.setChecked(True)

    calls = []
    monkeypatch.setattr("aula_l99_gui.config_tab.autostart.uninstall",
                        lambda: calls.append(True))
    tab.start_on_login_check.setChecked(False)
    assert calls == [True]
    assert settings.start_on_login() is False


def test_toggling_start_hidden_while_login_checked_reinstalls_with_new_flag(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("aula_l99_gui.config_tab.autostart.install", lambda hidden: None)
    tab.start_on_login_check.setChecked(True)

    calls = []
    monkeypatch.setattr("aula_l99_gui.config_tab.autostart.install",
                        lambda hidden: calls.append(hidden))
    tab.start_hidden_check.setChecked(False)
    assert calls == [False]
    assert settings.start_hidden() is False


def test_toggling_start_hidden_while_login_unchecked_only_persists_no_autostart_call(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    calls = []
    monkeypatch.setattr("aula_l99_gui.config_tab.autostart.install",
                        lambda hidden: calls.append(hidden))
    tab.start_hidden_check.setChecked(False)
    assert calls == []
    assert settings.start_hidden() is False


def test_start_hidden_checkbox_enablement_follows_login_checkbox(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("aula_l99_gui.config_tab.autostart.install", lambda hidden: None)
    monkeypatch.setattr("aula_l99_gui.config_tab.autostart.uninstall", lambda: None)

    tab.start_on_login_check.setChecked(True)
    assert tab.start_hidden_check.isEnabled() is True
    tab.start_on_login_check.setChecked(False)
    assert tab.start_hidden_check.isEnabled() is False


def test_checkboxes_disabled_with_tooltip_when_autostart_unsupported(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr("aula_l99_gui.config_tab.autostart.is_supported", lambda: False)
    fresh = ConfigTab(_StubSelector(), DebugLog())
    assert fresh.start_on_login_check.isEnabled() is False
    assert fresh.start_hidden_check.isEnabled() is False
    assert fresh.start_on_login_check.toolTip() != ""


def test_install_failure_reverts_checkbox_and_logs_to_debug_log(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(
        "aula_l99_gui.config_tab.autostart.install",
        lambda hidden: (_ for _ in ()).throw(OSError("permission denied")))

    messages = []
    tab._debug_log.message.connect(messages.append)
    tab.start_on_login_check.setChecked(True)

    assert tab.start_on_login_check.isChecked() is False
    assert settings.start_on_login() is False
    assert any("permission denied" in message for message in messages)
