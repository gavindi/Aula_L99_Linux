"""Music tab widget tests: the four Music Rhythm controls exist, default to the
protocol's captured values, feed the worker that starts the stream, and the
keyboard's lighting is restored when the stream stops.

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

from aula_l99_gui import audio_spectrum, settings  # noqa: E402
from aula_l99_gui.debug_log import DebugLog  # noqa: E402
from aula_l99_gui.music_tab import MusicTab  # noqa: E402
from aula_l99_gui.workers import AudioSpectrumWorker, KeyboardWorker  # noqa: E402
from aula_l99_hacky import protocol as kb_protocol  # noqa: E402


class _NoopSignal:
    def connect(self, *args, **kwargs):
        pass


class _FakeThread:
    """Returned by the patched start_worker: carries a connectable `finished`
    and a `wait`, so the restore path's bookkeeping has something to talk to
    without ever starting a real QThread."""

    finished = _NoopSignal()

    def wait(self, *args, **kwargs):
        return True


def _capture_start_worker(captured):
    def _start(worker):
        captured["worker"] = worker
        return _FakeThread()

    return _start


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
    assert tab.rhythm_combo.itemText(0) == "Off"
    assert tab.background_mode_combo.itemText(0) == "Off"


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
        {"rhythm": 3, "background_mode": 8,
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


def test_stream_end_restores_the_keyboard_lighting(tab, monkeypatch):
    """Stopping the stream hands the keyboard back to the lighting it had
    before the spectrum feed overrode it: select EFFECT_CUSTOM, then write the
    snapshot's colours -- the same restore shape user_lighting_tab uses."""
    colors = {key_id: (0, 255, 0) for key_id in kb_protocol.KEY_IDS}
    tab._restore_colors = colors
    captured = {}
    monkeypatch.setattr(
        "aula_l99_gui.music_tab.start_worker", _capture_start_worker(captured))

    tab._on_stream_finished(True, "audio spectrum stopped after 5 frame(s)")

    worker = captured.get("worker")
    assert isinstance(worker, KeyboardWorker)
    outgoings = [bytes(tx.outgoing) for tx in worker._transactions]
    # The effect block starts with EFFECT_CUSTOM (0x80): this is what pulls
    # the keyboard out of the feed's music mode so the colour write lands.
    assert any(o.startswith(bytes([kb_protocol.EFFECT_CUSTOM])) for o in outgoings)
    # The colour write is the persistent OP_COLOR_SET transfer.
    assert any(len(o) == 64 and o[1] == kb_protocol.OP_COLOR_SET for o in outgoings)
    assert tab._restore_colors is None
    tab._restore_active = False
    tab._restore_thread = None


def test_stream_failure_does_not_restore_the_keyboard(tab, monkeypatch):
    """A stream that never ran (e.g. arecord failed to start) must not write
    colours back over a keyboard the spectrum feed never touched."""
    tab._restore_colors = {key_id: (1, 2, 3) for key_id in kb_protocol.KEY_IDS}
    captured = {}
    monkeypatch.setattr(
        "aula_l99_gui.music_tab.start_worker", _capture_start_worker(captured))
    monkeypatch.setattr(
        "aula_l99_gui.music_tab.QMessageBox.critical",
        staticmethod(lambda *a, **k: None))

    tab._on_stream_finished(False, "could not start arecord: boom")

    assert captured.get("worker") is None
    assert tab._restore_colors is None


def test_shutdown_skips_the_keyboard_restore(tab, monkeypatch):
    """The keyboard returns to its own stored pattern once the app quits and
    the host session ends, so shutdown must not start a restore write (and a
    thread the teardown would then have to wait for)."""
    tab._restore_colors = {key_id: (0, 0, 255) for key_id in kb_protocol.KEY_IDS}
    captured = {}
    monkeypatch.setattr(
        "aula_l99_gui.music_tab.start_worker", _capture_start_worker(captured))

    tab._shutting_down = True
    tab._on_stream_finished(True, "audio spectrum stopped after 5 frame(s)")

    assert captured.get("worker") is None
    assert tab._restore_colors is None


def test_starting_a_stream_snapshots_the_keyboard_lighting(tab, monkeypatch, tmp_path):
    """The lighting to restore on stop is captured before the spectrum feed
    overrides it, so stop has something to hand the keyboard back."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    colors = {key_id: (255, 0, 0) for key_id in kb_protocol.KEY_IDS}
    monkeypatch.setattr(
        "aula_l99_gui.music_tab.read_colors", lambda *a, **k: colors)
    captured = {}
    monkeypatch.setattr(
        "aula_l99_gui.music_tab.start_worker", _capture_start_worker(captured))

    tab._device_ready = True
    device = audio_spectrum.CaptureDevice("dummy", "plughw:1,0")
    tab._devices = [device]
    tab.device_combo.clear()
    tab.device_combo.addItem("dummy", device)
    tab._start_stream()

    assert tab._restore_colors == colors
    assert isinstance(captured.get("worker"), AudioSpectrumWorker)
    # The captured worker was never run; clear the references so the
    # fixture's shutdown() doesn't reach a real thread.
    tab._stream_worker = None
    tab._stream_thread = None
    tab._streaming = False


def test_starting_a_stream_on_a_pipewire_device_uses_pw_record(tab, monkeypatch, tmp_path):
    """A PipeWire-kind device (loopback or application source) must build a
    pw-record argv, not the ALSA arecord one."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(
        "aula_l99_gui.music_tab.read_colors", lambda *a, **k: {})
    captured = {}
    monkeypatch.setattr(
        "aula_l99_gui.music_tab.start_worker", _capture_start_worker(captured))

    tab._device_ready = True
    device = audio_spectrum.CaptureDevice("App: Firefox", "573", kind="pipewire")
    tab._devices = [device]
    tab.device_combo.clear()
    tab.device_combo.addItem(device.label, device)
    tab._start_stream()

    worker = captured.get("worker")
    assert isinstance(worker, AudioSpectrumWorker)
    assert worker._arecord_cmd == audio_spectrum.pw_record_command("573")
    # The captured worker was never run; clear the references so the
    # fixture's shutdown() doesn't reach a real thread.
    tab._stream_worker = None
    tab._stream_thread = None
    tab._streaming = False
