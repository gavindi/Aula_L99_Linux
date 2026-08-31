"""Reads the app's own version out of pyproject.toml, once, at import time.

pyproject.toml is already the single source of truth for the version --
package.sh's tarball name and CHANGELOG.md's entries both key off it -- so
this reads the same file instead of adding a fourth place the number could
drift out of sync. It's colocated with this package (pyproject.toml sits
right next to __init__.py) so a dev checkout resolves it directly; package.sh
bundles the file at the same relative path for the compiled build, and every
downstream package (deb/rpm/snap/flatpak/AppImage) wraps that same build.

A plain regex rather than tomllib: this app's own requires-python floor is
3.10, and tomllib is 3.11+.
"""
from __future__ import annotations

import pathlib
import re

_PYPROJECT = pathlib.Path(__file__).resolve().parent / "pyproject.toml"
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _read_version() -> str:
    try:
        text = _PYPROJECT.read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    match = _VERSION_RE.search(text)
    return match.group(1) if match else "unknown"


APP_VERSION = _read_version()
