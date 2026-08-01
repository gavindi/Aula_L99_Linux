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
