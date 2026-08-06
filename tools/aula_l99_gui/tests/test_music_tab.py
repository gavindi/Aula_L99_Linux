"""Music tab widget tests: the four Music Rhythm controls exist, default to the
protocol's captured values, and feed the worker that starts the stream.

These instantiate real Qt widgets, so they run under an offscreen QPA platform
and guard on PySide6 being importable -- the rest of this test suite only
exercises pure functions and deliberately avoids a QApplication.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal  # noqa: E402

from aula_l99_gui import settings  # noqa: E402
from aula_l99_gui.debug_log import DebugLog  # noqa: E402
from aula_l99_gui.music_tab import MusicTab  # noqa: E402
from aula_l99_hacky import protocol as kb_protocol  # noqa: E402


class _StubSelector(QObject):
    """The slice of DeviceSelector MusicTab touches: its `changed` signal and
    current_path()."""

    changed = Signal(str, bool, bool, str)

    def __init__(self) -> None:
        super().__init__()
        self._path = "/dev/hidraw6"

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
    # Don't let the constructor's deferred device listing start a real worker
    # thread (arecord subprocess) in a widget test -- the controls don't need
    # it.
    monkeypatch.setattr(
        "aula_l99_gui.music_tab.QTimer.singleShot", staticmethod(lambda *a, **k: None))
    tab = MusicTab(_StubSelector(), DebugLog())
    yield tab
    tab.shutdown()


def test_four_music_rhythm_controls_exist(tab):
    assert tab.rhythm_combo.count() == len(kb_protocol.AUDIO_RHYTHM_NAMES)
    assert tab.background_mode_combo.count() == len(
        kb_protocol.AUDIO_BACKGROUND_MODE_NAMES)
    assert tab.rhythm_combo.itemText(0) == "Green/Yellow/Red"
    assert tab.background_mode_combo.itemText(0) == "Green/Yellow/Red"


def test_controls_default_to_the_captured_wire_values(tab):
    """An untouched tab must send exactly the single captured frame's header
    bytes (04 08 64, zero tail), so defaults track the protocol constants."""
    assert tab.rhythm_combo.currentIndex() == kb_protocol.AUDIO_RHYTHM_DEFAULT
    assert tab.background_mode_combo.currentIndex() == (
        kb_protocol.AUDIO_BACKGROUND_MODE_DEFAULT)
    assert tab.amplitude_slider.value() == kb_protocol.AUDIO_AMPLITUDE_DEFAULT
    assert tab.background_brightness_slider.value() == (
        kb_protocol.AUDIO_BACKGROUND_BRIGHTNESS_DEFAULT)


def test_slider_ranges_are_the_panel_scale(tab):
    assert tab.amplitude_slider.minimum() == 0
    assert tab.amplitude_slider.maximum() == 100
    assert tab.background_brightness_slider.minimum() == 0
    assert tab.background_brightness_slider.maximum() == 100


def test_changing_controls_persists_them(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    tab.rhythm_combo.setCurrentIndex(3)
    tab.background_mode_combo.setCurrentIndex(9)
    tab.amplitude_slider.setValue(40)
    tab.background_brightness_slider.setValue(77)
    assert settings.music_settings() == {
        "rhythm": 3, "background_mode": 9,
        "amplitude": 40, "background_brightness": 77,
    }


def test_changing_controls_pushes_them_to_the_running_stream(tab):
    """While a capture is live, moving the four controls must reach the
    stream worker immediately (mid-stream, no restart) as well as persist."""
    calls = []

    class _StubWorker:
        def set_music_settings(self, **kwargs):
            calls.append(kwargs)

        def stop(self):
            pass

    tab._stream_worker = _StubWorker()
    tab._streaming = True
    tab.rhythm_combo.setCurrentIndex(3)
    tab.background_mode_combo.setCurrentIndex(9)
    tab.amplitude_slider.setValue(40)
    tab.background_brightness_slider.setValue(77)
    assert calls == [
        {"rhythm": 3, "background_mode": 4,
         "amplitude": 100, "background_brightness": 0},
        {"rhythm": 3, "background_mode": 9,
         "amplitude": 100, "background_brightness": 0},
        {"rhythm": 3, "background_mode": 9,
         "amplitude": 40, "background_brightness": 0},
        {"rhythm": 3, "background_mode": 9,
         "amplitude": 40, "background_brightness": 77},
    ]


def test_changing_controls_does_not_touch_a_stopped_stream(tab):
    """With no worker running, a control change only persists -- it must not
    crash on a None worker."""
    tab._stream_worker = None
    tab._streaming = False
    tab.rhythm_combo.setCurrentIndex(2)


def test_controls_restore_from_saved_settings(tab, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    settings.set_music_settings({
        "rhythm": 2, "background_mode": 6,
        "amplitude": 30, "background_brightness": 55,
    })
    restored = MusicTab(_StubSelector(), DebugLog())
    try:
        assert restored.rhythm_combo.currentIndex() == 2
        assert restored.background_mode_combo.currentIndex() == 6
        assert restored.amplitude_slider.value() == 30
        assert restored.background_brightness_slider.value() == 55
    finally:
        restored.shutdown()
