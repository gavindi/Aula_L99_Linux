#!/usr/bin/env bash
# Stages the Nuitka dist package.sh produces into an AppDir and packs it with
# appimagetool. Unlike the deb/rpm/snap/flatpak, AppImage does no sandboxing
# of its own, so there's no /dev/hidraw caveat here: it just runs.
#
# Usage: ./make_appimage.sh [--rebuild]
#   Runs package.sh first if build/aula-l99-gui is missing, or if --rebuild
#   is passed. Downloads appimagetool into build/ if not already there.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DIST_DIR="$SCRIPT_DIR/build/aula-l99-gui"
APP_NAME="aula-l99-gui"
APPDIR="$SCRIPT_DIR/build/AppDir"

if [ "${1:-}" = "--rebuild" ] || [ ! -d "$DIST_DIR" ]; then
    "$SCRIPT_DIR/package.sh"
fi

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' tools/aula_l99_gui/pyproject.toml)"
ARCH="$(uname -m)"

# --- stage AppDir ------------------------------------------------------------
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib/$APP_NAME" "$APPDIR/usr/share/doc/$APP_NAME"

# Copied wholesale minus the tarball-only install.sh and @EXEC@ desktop
# template, same as make_deb.sh -- AppRun and the AppDir-root desktop file
# below take over both roles properly.
cp -a "$DIST_DIR/." "$APPDIR/usr/lib/$APP_NAME/"
rm -f "$APPDIR/usr/lib/$APP_NAME/install.sh" "$APPDIR/usr/lib/$APP_NAME/$APP_NAME.desktop"

cp "$SCRIPT_DIR/packaging/appimage/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"

# AppImage requires the .desktop and icon at the AppDir root, not nested --
# fixed Exec, no @EXEC@ needed since AppRun resolves the binary itself.
sed 's|@EXEC@|aula-l99-gui|' "$SCRIPT_DIR/packaging/aula-l99-gui.desktop" > "$APPDIR/$APP_NAME.desktop"
cp "$APPDIR/usr/lib/$APP_NAME/icon.png" "$APPDIR/$APP_NAME.png"
cp "$SCRIPT_DIR/LICENSE" "$APPDIR/usr/share/doc/$APP_NAME/copyright"

# --- appimagetool ------------------------------------------------------------
APPIMAGETOOL="$SCRIPT_DIR/build/appimagetool-x86_64.AppImage"
if [ ! -x "$APPIMAGETOOL" ]; then
    curl -fsSL -o "$APPIMAGETOOL" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$APPIMAGETOOL"
fi

OUT="$SCRIPT_DIR/build/$APP_NAME-$VERSION-$ARCH.AppImage"
rm -f "$OUT"
# GitHub-hosted runners often lack a usable FUSE mount for appimagetool's own
# default self-extraction, so extract-and-run is used proactively here
# rather than only as a fallback if the plain form fails.
ARCH="$ARCH" "$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" "$OUT"

echo "built: $OUT ($(du -h "$OUT" | cut -f1))"
