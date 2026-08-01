#!/usr/bin/env bash
# Byte-compiles every Python file under tools/ -- a syntax check for the whole
# project, which is worth having because most of this code only runs with a
# keyboard plugged in, so a typo in a rarely-taken branch would otherwise sit
# there until the hardware was in front of someone.
#
# Compiling is not importing: it catches syntax and indentation errors only,
# not bad imports or names. Run the tests for those.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/tools"

# Same interpreter search as run.sh, so this checks the code against whatever
# Python actually runs it.
if command -v uv >/dev/null 2>&1; then
    PYTHON=(uv run --project aula_l99_gui python3)
elif [ -x ".venv/bin/python3" ]; then
    PYTHON=(.venv/bin/python3)
elif [ -x "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON=("$SCRIPT_DIR/.venv/bin/python3")
else
    PYTHON=(python3)
fi

# -q once, not twice: a second -q suppresses the error output as well as the
# progress, which for a checker means a silent non-zero exit. "$@" lets a
# caller narrow this to one package (./compile.sh aula_l99_gui).
# The venv must be excluded: it lives under tools/aula_l99_gui/.venv and
# PySide6 ships non-Python files (Jinja templates) with .py suffixes that are
# not valid Python and would fail the syntax check.
"${PYTHON[@]}" -m compileall -q -x '(__pycache__|\.venv)' "${@:-.}"
echo "compiled ok: ${*:-tools/}"
