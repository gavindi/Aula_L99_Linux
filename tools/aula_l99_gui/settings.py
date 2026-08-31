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


def monitor_period_seconds() -> int:
    """The system-monitor stream's last-set update frequency, in seconds."""
    return int(_read().get("monitor", {}).get("period", 5))


def set_monitor_period_seconds(period: int) -> None:
    """Persist the system-monitor stream's update frequency."""
    data = _read()
    data.setdefault("monitor", {})["period"] = int(period)
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


def keyboard_settings() -> dict:
    """The Settings tab's keyboard-panel dropdowns' last-used values: sleep
    time 0..3 and response-time level 1..5. Unknown keys default to the
    lowest wire value so a fresh install starts at the first dropdown entry.

    This is the shared ledger for the panel: the GUI writes it on every
    dropdown change and the CLI records its --settings writes here too, so
    entering the Config tab (see ConfigTab.refresh) always shows what was
    last applied. The keyboard stores the panel itself, so nothing is
    written to hardware just by loading these.
    """
    from aula_l99_hacky import protocol as kb_protocol

    saved = _read().get("keyboard", {})
    defaults = {
        "sleep_time": 0,
        "response_time": kb_protocol.RESPONSE_TIME_MIN,
    }
    return {
        key: int(saved.get(key, default))
        if key in defaults else default
        for key, default in defaults.items()
    }


def set_keyboard_settings(settings: dict) -> None:
    """Persist the Settings tab's keyboard-panel dropdown values (see
    keyboard_settings()). Missing keys leave any previously saved values in
    place."""
    data = _read()
    data.setdefault("keyboard", {}).update(
        {str(key): int(value) for key, value in settings.items()})
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    tmp.replace(path)


def start_on_login() -> bool:
    """Whether the last-saved preference is to autostart this app at login.
    ~/.config/autostart/aula-l99-gui.desktop (see autostart.py) is the file
    every desktop environment actually reads; this is only so the Config
    tab's checkbox can restore its state on the next launch."""
    return bool(_read().get("startup", {}).get("login", False))


def set_start_on_login(enabled: bool) -> None:
    """Persist the start-on-login toggle state (see start_on_login())."""
    data = _read()
    data.setdefault("startup", {})["login"] = bool(enabled)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    tmp.replace(path)


def start_hidden() -> bool:
    """Whether an autostart-launched instance starts hidden in the tray
    (--start-hidden) rather than with its window shown. Defaults to True:
    the natural "start on login" experience is to appear silently in the
    tray, not pop a window open at login."""
    return bool(_read().get("startup", {}).get("hidden", True))


def set_start_hidden(hidden: bool) -> None:
    """Persist the start-hidden toggle state (see start_hidden())."""
    data = _read()
    data.setdefault("startup", {})["hidden"] = bool(hidden)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    tmp.replace(path)
