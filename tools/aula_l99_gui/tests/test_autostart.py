import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aula_l99_gui import autostart


def _clean_env(monkeypatch, tmp_path):
    """Dev-mode, non-packaged environment: none of the packaging signals
    autostart._launch_command() looks for are set."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for var in ("FLATPAK_ID", "SNAP_INSTANCE_NAME", "SNAP_NAME", "APPIMAGE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delattr(autostart, "__compiled__", raising=False)


def _exec_line(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("Exec="):
            return line[len("Exec="):]
    raise AssertionError("no Exec= line found")


def _make_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


# -- location -----------------------------------------------------------

def test_autostart_dir_honors_xdg_config_home(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    assert autostart.autostart_dir() == tmp_path / "autostart"
    assert autostart.autostart_path() == tmp_path / "autostart" / "aula-l99-gui.desktop"


# -- install/uninstall plumbing -----------------------------------------

def test_is_installed_false_when_no_file(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    assert autostart.is_installed() is False


def test_is_installed_true_after_install(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(autostart, "__compiled__", True, raising=False)
    fake_bin = tmp_path / "aula-l99-gui"
    _make_executable(fake_bin)
    monkeypatch.setattr(sys, "argv", [str(fake_bin)])

    autostart.install(hidden=True)
    assert autostart.is_installed() is True


def test_install_is_atomic_no_tmp_left_behind(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(autostart, "__compiled__", True, raising=False)
    fake_bin = tmp_path / "aula-l99-gui"
    _make_executable(fake_bin)
    monkeypatch.setattr(sys, "argv", [str(fake_bin)])

    autostart.install(hidden=True)
    path = autostart.autostart_path()
    assert path.exists()
    assert not path.with_name(path.name + ".tmp").exists()


def test_uninstall_is_idempotent_when_file_missing(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    autostart.uninstall()  # must not raise
    assert autostart.is_installed() is False


def test_uninstall_removes_existing_file(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(autostart, "__compiled__", True, raising=False)
    fake_bin = tmp_path / "aula-l99-gui"
    _make_executable(fake_bin)
    monkeypatch.setattr(sys, "argv", [str(fake_bin)])

    autostart.install(hidden=True)
    autostart.uninstall()
    assert autostart.is_installed() is False


# -- Exec= content --------------------------------------------------------

def test_install_always_includes_tray_flag(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(autostart, "__compiled__", True, raising=False)
    fake_bin = tmp_path / "aula-l99-gui"
    _make_executable(fake_bin)
    monkeypatch.setattr(sys, "argv", [str(fake_bin)])

    autostart.install(hidden=False)
    content = autostart.autostart_path().read_text(encoding="utf-8")
    assert "--tray" in _exec_line(content)


def test_install_includes_start_hidden_flag_only_when_hidden_true(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(autostart, "__compiled__", True, raising=False)
    fake_bin = tmp_path / "aula-l99-gui"
    _make_executable(fake_bin)
    monkeypatch.setattr(sys, "argv", [str(fake_bin)])

    autostart.install(hidden=True)
    assert "--start-hidden" in _exec_line(
        autostart.autostart_path().read_text(encoding="utf-8"))

    autostart.install(hidden=False)
    assert "--start-hidden" not in _exec_line(
        autostart.autostart_path().read_text(encoding="utf-8"))


def test_install_sets_gnome_autostart_enabled_key(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(autostart, "__compiled__", True, raising=False)
    fake_bin = tmp_path / "aula-l99-gui"
    _make_executable(fake_bin)
    monkeypatch.setattr(sys, "argv", [str(fake_bin)])

    autostart.install(hidden=True)
    content = autostart.autostart_path().read_text(encoding="utf-8")
    assert "X-GNOME-Autostart-enabled=true" in content


# -- relaunch-command resolution per environment ---------------------------

def test_dev_mode_uses_python_dash_m_and_sets_path_to_tools_dir(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)

    autostart.install(hidden=True)
    content = autostart.autostart_path().read_text(encoding="utf-8")
    exec_line = _exec_line(content)
    assert sys.executable in exec_line
    assert "-m aula_l99_gui.main" in exec_line
    tools_dir = Path(autostart.__file__).resolve().parent.parent
    assert f"Path={tools_dir}" in content


def test_compiled_mode_uses_resolved_argv0(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(autostart, "__compiled__", True, raising=False)
    fake_bin = tmp_path / "aula-l99-gui"
    _make_executable(fake_bin)
    monkeypatch.setattr(sys, "argv", [str(fake_bin)])

    autostart.install(hidden=True)
    exec_line = _exec_line(autostart.autostart_path().read_text(encoding="utf-8"))
    assert str(fake_bin) in exec_line


def test_flatpak_env_var_overrides_everything_else(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(autostart, "__compiled__", True, raising=False)
    fake_bin = tmp_path / "aula-l99-gui"
    _make_executable(fake_bin)
    monkeypatch.setattr(sys, "argv", [str(fake_bin)])
    monkeypatch.setenv("FLATPAK_ID", "io.github.gavindi.AulaL99Gui")

    autostart.install(hidden=True)
    content = autostart.autostart_path().read_text(encoding="utf-8")
    exec_line = _exec_line(content)
    assert exec_line == "flatpak run io.github.gavindi.AulaL99Gui --tray --start-hidden"
    assert "Icon=io.github.gavindi.AulaL99Gui" in content


def test_snap_env_var_uses_snap_bin_not_revision_path(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SNAP_INSTANCE_NAME", "aula-l99-gui")
    monkeypatch.setattr(sys, "argv", ["/snap/aula-l99-gui/123/bin/aula-l99-gui"])

    autostart.install(hidden=True)
    exec_line = _exec_line(autostart.autostart_path().read_text(encoding="utf-8"))
    assert exec_line.startswith("/snap/bin/aula-l99-gui")
    assert "/snap/aula-l99-gui/123" not in exec_line


def test_appimage_env_var_uses_appimage_path_not_mounted_argv0(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("APPIMAGE", "/home/user/Apps/aula-l99-gui.AppImage")
    monkeypatch.setattr(sys, "argv", ["/tmp/.mount_abcdef/AppRun"])

    autostart.install(hidden=True)
    exec_line = _exec_line(autostart.autostart_path().read_text(encoding="utf-8"))
    assert "/home/user/Apps/aula-l99-gui.AppImage" in exec_line
    assert ".mount_" not in exec_line


# -- is_supported / failure modes -----------------------------------------

def test_is_supported_false_when_compiled_argv0_not_executable(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(autostart, "__compiled__", True, raising=False)
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "does-not-exist")])

    assert autostart.is_supported() is False


def test_install_raises_runtime_error_when_unsupported(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(autostart, "__compiled__", True, raising=False)
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "does-not-exist")])

    import pytest
    with pytest.raises(RuntimeError):
        autostart.install(hidden=True)


# -- icon copy ---------------------------------------------------------

def test_install_best_effort_copies_sibling_icon_into_hicolor(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(autostart, "__compiled__", True, raising=False)
    fake_bin = tmp_path / "aula-l99-gui"
    _make_executable(fake_bin)
    (tmp_path / "icon.png").write_bytes(b"not a real png but fine for a copy test")
    monkeypatch.setattr(sys, "argv", [str(fake_bin)])
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    autostart.install(hidden=True)
    copied = home / ".local/share/icons/hicolor/256x256/apps/aula-l99-gui.png"
    assert copied.is_file()


def test_install_icon_copy_failure_does_not_raise(monkeypatch, tmp_path):
    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setattr(autostart, "__compiled__", True, raising=False)
    fake_bin = tmp_path / "aula-l99-gui"
    _make_executable(fake_bin)
    (tmp_path / "icon.png").write_bytes(b"icon")
    monkeypatch.setattr(sys, "argv", [str(fake_bin)])

    def _raise_oserror():
        raise OSError("no home")

    monkeypatch.setattr(Path, "home", _raise_oserror)

    # The desktop file write still succeeds even though the icon copy blew up.
    autostart.install(hidden=True)
    assert autostart.is_installed() is True
