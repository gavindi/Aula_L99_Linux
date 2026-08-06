#!/usr/bin/env bash
# Installs a desktop launcher and icon for the unpacked build this script
# ships in. Uses the per-user locations (~/.local/share/applications and
# ~/.local/share/icons/hicolor), so no root is needed and every desktop
# environment picks them up. Run with --uninstall to remove them again.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$HERE/aula-l99-gui"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
ICON_NAME="aula-l99-gui"
DESKTOP_FILE="$APP_DIR/aula-l99-gui.desktop"

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$DESKTOP_FILE" "$ICON_DIR/$ICON_NAME.png"
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$APP_DIR" 2>/dev/null || true
    fi
    echo "removed $DESKTOP_FILE"
    exit 0
fi

if [ ! -x "$BIN" ]; then
    echo "error: $BIN not found; run this from inside the unpacked build" >&2
    exit 1
fi

mkdir -p "$APP_DIR" "$ICON_DIR"
cp "$HERE/icon.png" "$ICON_DIR/$ICON_NAME.png"

# The .desktop file carries @EXEC@, which is only known here. & and \ in the
# path need escaping for sed; spaces are handled by quoting Exec.
esc="$(printf '%s' "$BIN" | sed 's/[&\\]/\\&/g')"
sed "s|@EXEC@|$esc|" "$HERE/aula-l99-gui.desktop" > "$DESKTOP_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" 2>/dev/null || true
fi
echo "installed: $DESKTOP_FILE (Exec=$BIN)"
