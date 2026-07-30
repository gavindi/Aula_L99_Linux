#!/usr/bin/env bash
# Runs the aula_l99_gui PySide6 GUI (see tools/aula_l99_gui/README.md).
# aula_l99_gui.main is a package, not a standalone script, so it must be run
# as a module with tools/ as the working directory.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/tools"

if command -v uv >/dev/null 2>&1; then
    exec uv run --project aula_l99_gui python3 -m aula_l99_gui.main "$@"
elif [ -x ".venv/bin/python3" ]; then
    exec .venv/bin/python3 -m aula_l99_gui.main "$@"
else
    exec python3 -m aula_l99_gui.main "$@"
fi
