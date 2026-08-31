from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aula_l99_gui import settings


def _config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "aula_l99" / "config.json"


def test_defaults_to_not_running_when_no_file(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    assert settings.monitor_running() is False


def test_round_trip(monkeypatch, tmp_path):
    path = _config(monkeypatch, tmp_path)
    settings.set_monitor_running(True)
    assert settings.monitor_running() is True
    assert path.exists()

    settings.set_monitor_running(False)
    assert settings.monitor_running() is False


def test_write_is_atomic_no_tmp_left_behind(monkeypatch, tmp_path):
    path = _config(monkeypatch, tmp_path)
    settings.set_monitor_running(True)
    assert path.exists()
    assert not path.with_name(path.name + ".tmp").exists()


def test_malformed_file_reads_as_not_running(monkeypatch, tmp_path):
    path = _config(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("not json at all")
    assert settings.monitor_running() is False
    # A later write recovers the file instead of failing on the garbage.
    settings.set_monitor_running(True)
    assert settings.monitor_running() is True


def test_unreadable_file_reads_as_not_running(monkeypatch, tmp_path):
    path = _config(monkeypatch, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text('{"monitor": {"running": true}}')
    path.chmod(0o000)
    try:
        assert settings.monitor_running() is False
    finally:
        path.chmod(0o644)


def test_file_is_plain_json_readable_without_qt(monkeypatch, tmp_path):
    import json

    path = _config(monkeypatch, tmp_path)
    settings.set_monitor_running(True)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data == {"monitor": {"running": True}}


def test_monitor_period_defaults_to_five_seconds_when_no_file(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    assert settings.monitor_period_seconds() == 5


def test_monitor_period_round_trip(monkeypatch, tmp_path):
    path = _config(monkeypatch, tmp_path)
    settings.set_monitor_period_seconds(30)
    assert settings.monitor_period_seconds() == 30
    assert path.exists()

    settings.set_monitor_period_seconds(1)
    assert settings.monitor_period_seconds() == 1


def test_monitor_period_and_running_share_the_monitor_key(monkeypatch, tmp_path):
    """Both fields live under the same "monitor" dict, and setting one must
    not clobber the other."""
    _config(monkeypatch, tmp_path)
    settings.set_monitor_running(True)
    settings.set_monitor_period_seconds(10)
    assert settings.monitor_running() is True
    assert settings.monitor_period_seconds() == 10


def test_music_settings_default_to_protocol_defaults(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    from aula_l99_hacky import protocol as kb_protocol

    saved = settings.music_settings()
    assert saved["rhythm"] == kb_protocol.AUDIO_RHYTHM_DEFAULT
    assert saved["background_mode"] == kb_protocol.AUDIO_BACKGROUND_MODE_DEFAULT
    assert saved["amplitude"] == kb_protocol.AUDIO_AMPLITUDE_DEFAULT
    assert saved["background_brightness"] == (
        kb_protocol.AUDIO_BACKGROUND_BRIGHTNESS_DEFAULT)


def test_music_settings_round_trip(monkeypatch, tmp_path):
    path = _config(monkeypatch, tmp_path)
    settings.set_music_settings({
        "rhythm": 3, "background_mode": 9,
        "amplitude": 40, "background_brightness": 77,
    })
    assert settings.music_settings() == {
        "rhythm": 3, "background_mode": 9,
        "amplitude": 40, "background_brightness": 77,
    }
    assert path.exists()


def test_music_settings_are_plain_json(monkeypatch, tmp_path):
    import json

    _config(monkeypatch, tmp_path)
    settings.set_music_settings({"rhythm": 5, "amplitude": 10})
    with open(settings.config_path(), encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["music"]["rhythm"] == 5
    assert data["music"]["amplitude"] == 10


def test_music_settings_merge_on_partial_write(monkeypatch, tmp_path):
    _config(monkeypatch, tmp_path)
    settings.set_music_settings({"rhythm": 2, "amplitude": 30})
    # A later write of only some keys keeps the earlier ones in place.
    settings.set_music_settings({"background_mode": 6})
    saved = settings.music_settings()
    assert saved["rhythm"] == 2
    assert saved["background_mode"] == 6
    assert saved["amplitude"] == 30
