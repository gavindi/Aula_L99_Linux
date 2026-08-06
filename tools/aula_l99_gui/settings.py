"""Persistent settings shared by the GUI and anything else that drives the
L99 keyboard -- a headless daemon, the CLI -- so that whichever component
runs next picks up the saved state instead of starting blank.

Plain JSON under the XDG config dir (`~/.config/aula_l99/config.json`) so a
non-Qt component can read it without importing PySide6. Writes go to a temp
file and then replace the real one, so a crash mid-write cannot leave a
half-written config behind. A missing, unreadable or malformed file simply
reads as defaults.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "aula_l99"


def config_path() -> Path:
    return config_dir() / "config.json"


def _read() -> dict:
    try:
        with open(config_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def monitor_running() -> bool:
    """Whether the system-monitor stream was left running the last time the
    GUI closed (or the toggle was last changed)."""
    return bool(_read().get("monitor", {}).get("running", False))


def set_monitor_running(running: bool) -> None:
    """Persist the system-monitor toggle state."""
    data = _read()
    data.setdefault("monitor", {})["running"] = bool(running)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    tmp.replace(path)


def music_settings() -> dict:
    """The Music tab's last-used Rhythm / Background Mode / Amplitude /
    Background Brightness values, keyed by control name. Unknown keys default
    to the protocol defaults so a fresh install starts with the vendor's."""
    from aula_l99_hacky import protocol as kb_protocol

    saved = _read().get("music", {})
    defaults = {
        "rhythm": kb_protocol.AUDIO_RHYTHM_DEFAULT,
        "background_mode": kb_protocol.AUDIO_BACKGROUND_MODE_DEFAULT,
        "amplitude": kb_protocol.AUDIO_AMPLITUDE_DEFAULT,
        "background_brightness": kb_protocol.AUDIO_BACKGROUND_BRIGHTNESS_DEFAULT,
    }
    return {
        key: int(saved.get(key, default))
        if key in defaults else default
        for key, default in defaults.items()
    }


def set_music_settings(settings: dict) -> None:
    """Persist the Music tab's control values (see music_settings()). Missing
    keys leave any previously saved values in place, so a partial write does
    not reset the others."""
    data = _read()
    data.setdefault("music", {}).update(
        {str(key): int(value) for key, value in settings.items()})
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    tmp.replace(path)
