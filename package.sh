#!/usr/bin/env bash
# Compiles the GUI into a self-contained directory with Nuitka and packs it as
# a tarball, so the app can be handed to someone who has no Python, no venv and
# no intention of acquiring either. The result carries its own CPython, its own
# Qt, and the skin assets; the only outside requirement left is ffmpeg, and
# only for video sources on the Touchscreen tab. The dist also ships an
# install.sh that adds a .desktop launcher and icon for the unpacked build to
# the user's ~/.local/share (see packaging/).
#
# This buys distribution, not speed. Measured against `./run.sh` on the same
# machine, the packaged binary reaches its first window in ~0.37s versus ~0.34s
# interpreted, and sits at ~126MB RSS versus ~130MB. Qt dominates both numbers,
# so compiling the Python moves neither. Package this because it is easier to
# install, not because it is expected to run better.
#
# Two things about the build that are not obvious:
#
#   * Nuitka 4.1.3 calls Python 3.14 "experimental" and names 3.13 as the
#     version to use. The build venv is therefore pinned to 3.13 even though
#     the app itself runs fine on 3.14 -- see PY_VERSION below.
#   * The build venv is deliberately not the dev venv. tools/aula_l99_gui/.venv
#     has ~500MB of packages nothing imports (onnxruntime, opencv, numpy...),
#     and Nuitka follows imports, so building from it risks dragging them in.
#     This creates a clean one from the declared dependencies only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/tools"

PY_VERSION="3.13"
BUILD_VENV=".venv-build"
DIST_NAME="aula-l99-gui"
OUT_DIR="$SCRIPT_DIR/build"

# --- interpreter ------------------------------------------------------------
# uv can fetch a pinned CPython without root, which is the tidy path. Without
# it we fall back to whatever python3 is around and warn if Nuitka is going to
# grumble about the version.
if command -v uv >/dev/null 2>&1; then
    uv venv --python "$PY_VERSION" "$BUILD_VENV"
    uv pip install --python "$BUILD_VENV/bin/python" \
        PySide6_Essentials Pillow defusedxml nuitka patchelf
else
    echo "note: uv not found; building against the system python3." >&2
    SYS_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if [ "$SYS_VERSION" != "$PY_VERSION" ]; then
        echo "warning: python3 is $SYS_VERSION, not $PY_VERSION. Nuitka only" >&2
        echo "         supports $SYS_VERSION experimentally and the build may" >&2
        echo "         fail or misbehave. Install uv to pin $PY_VERSION." >&2
    fi
    python3 -m venv "$BUILD_VENV"
    "$BUILD_VENV/bin/pip" install --quiet --upgrade pip
    # PySide6_Essentials, not PySide6: the code imports only QtCore, QtGui and
    # QtWidgets, and skipping Addons is the largest size saving available.
    "$BUILD_VENV/bin/pip" install --quiet \
        PySide6_Essentials Pillow defusedxml nuitka patchelf
fi

# Nuitka shells out to patchelf for standalone RPATH rewriting on Linux and
# does not vendor it. The pip wheel above puts one in the venv's bin, which is
# why that goes on PATH rather than requiring a system package.
export PATH="$PWD/$BUILD_VENV/bin:$PATH"

# --- compile ----------------------------------------------------------------
# Run from tools/ so aula_l99_hacky and aula_l99_screen resolve at compile
# time: main.py only puts them on sys.path at *runtime*, which does nothing for
# Nuitka's static analysis.
#
# The three assets subdirectories are named individually rather than including
# assets/ wholesale, because assets/gif/ is 113MB of vendor reference GIFs that
# no code path opens (saved animations live under QStandardPaths'
# AppDataLocation instead). Listing them explicitly means a new asset directory
# shows up as a missing file at runtime rather than silently re-inflating the
# tarball by two orders of magnitude.
#
# aula_l99_gui/font/ is separate from assets/ and easy to overlook. Leaving it
# out fails *silently* -- theme.load_font() returns "" by design and Qt falls
# back to the platform font -- so the build would look fine while quietly
# losing the skin's typography.
#
# The .desktop launcher template (packaging/aula-l99-gui.desktop) ships in the
# dist so the install.sh beside it can rewrite its @EXEC@ placeholder with the
# real binary path at install time; the launcher icon is derived from the
# vendor's DeviceDriver.ico at pack time below.
"$BUILD_VENV/bin/python" -m nuitka \
    --standalone \
    --enable-plugin=pyside6 \
    --include-package=aula_l99_hacky \
    --include-package=aula_l99_screen \
    --include-data-dir=aula_l99_gui/assets/skins=aula_l99_gui/assets/skins \
    --include-data-dir=aula_l99_gui/assets/layouts=aula_l99_gui/assets/layouts \
    --include-data-dir=aula_l99_gui/assets/device=aula_l99_gui/assets/device \
    --include-data-dir=aula_l99_gui/font=aula_l99_gui/font \
    --include-data-files=aula_l99_gui/pyproject.toml=aula_l99_gui/pyproject.toml \
    --include-data-files="$SCRIPT_DIR/packaging/aula-l99-gui.desktop"=aula-l99-gui.desktop \
    --noinclude-qt-translations \
    --output-dir="$OUT_DIR" \
    --output-filename="$DIST_NAME" \
    --assume-yes-for-downloads \
    aula_l99_gui/main.py

# --- pack -------------------------------------------------------------------
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' aula_l99_gui/pyproject.toml)"
ARCH="$(uname -m)"
TARBALL="$OUT_DIR/$DIST_NAME-$VERSION-$ARCH.tar.gz"

# Nuitka names the output after the entry module (main.dist); rename it so the
# tarball unpacks into something a human recognises.
rm -rf "$OUT_DIR/$DIST_NAME"
mv "$OUT_DIR/main.dist" "$OUT_DIR/$DIST_NAME"

# Derive the 256x256 launcher icon from the vendor's DeviceDriver.ico (whose
# largest frame is 64x64; the upscale is Lanczos, and the venv's Pillow is the
# same one the app pins). The .desktop template came in via --include-data-files
# above; install.sh rewrites its @EXEC@ and drops both into ~/.local/share.
"$BUILD_VENV/bin/python" - "$OUT_DIR/$DIST_NAME" <<'PY'
import sys
from pathlib import Path

from PIL import Image

dist = Path(sys.argv[1])
ico = Image.open(dist / "aula_l99_gui/assets/skins/theme1/DeviceDriver.ico").convert("RGBA")
ico.resize((256, 256), Image.Resampling.LANCZOS).save(dist / "icon.png")
PY
cp "$SCRIPT_DIR/packaging/install.sh" "$OUT_DIR/$DIST_NAME/install.sh"
chmod +x "$OUT_DIR/$DIST_NAME/install.sh"

tar -czf "$TARBALL" -C "$OUT_DIR" "$DIST_NAME"

echo
echo "built:   $OUT_DIR/$DIST_NAME/$DIST_NAME"
echo "tarball: $TARBALL ($(du -h "$TARBALL" | cut -f1))"
echo "unpacked: $(du -sh "$OUT_DIR/$DIST_NAME" | cut -f1)"
