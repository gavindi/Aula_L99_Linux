"""XDG autostart entry for "start on login": writes/removes
~/.config/autostart/aula-l99-gui.desktop (XDG_CONFIG_HOME-aware, same as
settings.py) so the app can be launched at the next graphical login with
--tray (always) and --start-hidden (per the "start hidden" preference).

Unlike the launcher .desktop packaging/install.sh writes once at install
time from a known absolute path, this has to work at *runtime*, from
whichever of the app's five package forms happens to be running right now,
and the toggle can be flipped at any time after install. See
_launch_command() for why each package form needs its own case rather than
a single sys.argv[0] heuristic:

  * A flatpak's own /app/bin/... path is meaningless outside the sandbox;
    the host has to relaunch it via `flatpak run <app-id>`.
  * A snap's argv[0] is under /snap/<name>/<revision>/..., which changes on
    every refresh; the stable entry point is /snap/bin/<name>.
  * An AppImage's argv[0] is under a random per-run FUSE mount that is gone
    by the next login; the AppImage runtime exports APPIMAGE with the
    stable path to the .AppImage file itself.
  * A Nuitka-compiled deb/rpm/tarball binary's argv[0] is the real thing.
  * A plain dev checkout has no compiled binary at all -- relaunch through
    the interpreter with -m, from the tools/ directory main.py itself
    bootstraps from.
"""
from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

_DESKTOP_FILE_NAME = "aula-l99-gui.desktop"
_ICON_NAME = "aula-l99-gui"


def autostart_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "autostart"


def autostart_path() -> Path:
    return autostart_dir() / _DESKTOP_FILE_NAME


def _launch_command() -> tuple[list[str], str | None] | None:
    """(argv, working_dir) to relaunch *this exact running instance*, or
    None if that can't be determined -- see module docstring for why each
    branch exists rather than one generic heuristic."""
    flatpak_id = os.environ.get("FLATPAK_ID")
    if flatpak_id:
        return ([flatpak_id], None)  # install() prefixes ["flatpak", "run", ...]

    snap_name = os.environ.get("SNAP_INSTANCE_NAME") or os.environ.get("SNAP_NAME")
    if snap_name:
        return ([f"/snap/bin/{snap_name}"], None)

    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return ([appimage], None)

    if "__compiled__" in globals():
        exe = Path(sys.argv[0]).resolve()
        if exe.is_file() and os.access(exe, os.X_OK):
            return ([str(exe)], None)
        return None

    python = Path(sys.executable).resolve()
    if python.is_file():
        tools_dir = Path(__file__).resolve().parent.parent
        return ([str(python), "-m", "aula_l99_gui.main"], str(tools_dir))
    return None


def is_supported() -> bool:
    """Whether install() can currently compute a working relaunch command."""
    return _launch_command() is not None


def is_installed() -> bool:
    return autostart_path().is_file()


def _icon_source() -> Path | None:
    """Best-effort: an icon.png next to the resolved binary right now, for
    the one-time copy into the user's icon theme (see _install_icon)."""
    launch = _launch_command()
    if launch is None:
        return None
    argv, _ = launch
    candidate = Path(argv[0])
    if candidate.is_absolute():
        icon = candidate.parent / "icon.png"
        if icon.is_file():
            return icon
    return None


def _install_icon_best_effort() -> None:
    """Copies icon.png into ~/.local/share/icons/hicolor, the same fixed
    location and name packaging/install.sh already uses for the launcher
    entry -- covers the tarball-without-install.sh and AppImage cases,
    neither of which registers this icon name into the theme any other way.
    Best-effort and silent: a missing icon is cosmetic, never worth failing
    the actual autostart toggle over."""
    source = _icon_source()
    if source is None:
        return
    try:
        icon_dir = Path.home() / ".local/share/icons/hicolor/256x256/apps"
        icon_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, icon_dir / f"{_ICON_NAME}.png")
    except OSError:
        pass


def install(hidden: bool) -> None:
    """Writes the autostart entry. Raises OSError/RuntimeError on failure --
    the caller (ConfigTab) is responsible for reverting UI state and
    reporting it; this function does not swallow that one."""
    launch = _launch_command()
    if launch is None:
        raise RuntimeError("cannot determine how to relaunch this installation")
    argv, workdir = launch

    flatpak_id = os.environ.get("FLATPAK_ID")
    if flatpak_id:
        argv = ["flatpak", "run", flatpak_id]
        icon = flatpak_id
    else:
        icon = _ICON_NAME
        _install_icon_best_effort()

    args = list(argv) + ["--tray"]
    if hidden:
        args.append("--start-hidden")
    exec_line = " ".join(shlex.quote(a) for a in args)

    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.0",
        "Name=AULA L99 GUI",
        "Comment=Control the AULA L99 keyboard lighting and touchscreen",
        f"Exec={exec_line}",
    ]
    if workdir:
        lines.append(f"Path={workdir}")
    lines += [
        f"Icon={icon}",
        "Terminal=false",
        "X-GNOME-Autostart-enabled=true",
    ]
    content = "\n".join(lines) + "\n"

    path = autostart_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def uninstall() -> None:
    """Removes the autostart entry. Never raises if it's already gone."""
    autostart_path().unlink(missing_ok=True)
