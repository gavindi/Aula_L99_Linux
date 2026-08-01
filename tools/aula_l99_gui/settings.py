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
