#!/usr/bin/env bash
# Packs the Nuitka-compiled GUI (the build/ tree that package.sh produces) into
# a proper .deb, for apt-based distribution: the dist lands in /usr/lib, a
# launcher wrapper on PATH, the desktop entry and icon under /usr/share, and a
# udev rule granting the logged-in desktop session access to the keyboard's
# hidraw node -- so "install once, it just works" is actually true.
#
# The .deb is built with `dpkg-deb --build` on a staged tree rather than with
# debhelper/debuild: those expect to compile from source, and what we are
# shipping is a self-contained binary. The binary carries its own CPython and
# Qt, so the only dependencies declared are the subprocess tools the app
# shells out to (ffmpeg for video, arecord for the Music tab), and as
# Recommends rather than Depends because the app degrades gracefully without
# them (it checks PATH and shows a targeted error).
#
# Read-only /usr/lib is fine for every file in the dist: the skin assets and
# the layout XML are parsed at import time, never written back.
#
# Usage: ./make_deb.sh [--rebuild]
#   Reuses build/aula-l99-gui when it exists and already matches
#   tools/aula_l99_gui/pyproject.toml's version; --rebuild forces a fresh
#   Nuitka compile (~80s, needs a C compiler and internet for the Nuitka
#   downloads) regardless.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DIST_DIR="$SCRIPT_DIR/build/aula-l99-gui"
DEB_NAME="aula-l99-gui"
PACKAGE_VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' tools/aula_l99_gui/pyproject.toml)"

# --- arguments ---------------------------------------------------------------
for arg in "$@"; do
    case "$arg" in
        --rebuild) REBUILD=1 ;;
        --help|-h) echo "usage: $0 [--rebuild]" >&2; exit 0 ;;
        *) echo "error: unknown argument: $arg" >&2; exit 1 ;;
    esac
done

# --- compiled build ----------------------------------------------------------
# A stale build/aula-l99-gui from an earlier checkout would otherwise get
# reused silently -- right version number on the .deb's own metadata below,
# old code actually inside it. package.sh bundles its own pyproject.toml into
# the dist (see its own comment on that) specifically so this can tell the
# two apart instead of trusting the directory's mere existence.
DIST_VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' \
    "$DIST_DIR/aula_l99_gui/pyproject.toml" 2>/dev/null || true)"
if [ "${REBUILD:-}" = "1" ]; then
    "$SCRIPT_DIR/package.sh"
elif [ ! -d "$DIST_DIR" ]; then
    echo "note: $DIST_DIR not found; running package.sh to compile it." >&2
    "$SCRIPT_DIR/package.sh"
elif [ "$DIST_VERSION" != "$PACKAGE_VERSION" ]; then
    echo "note: $DIST_DIR is version ${DIST_VERSION:-<unknown>}, not" \
        "$PACKAGE_VERSION; running package.sh to recompile it." >&2
    "$SCRIPT_DIR/package.sh"
fi

if [ ! -x "$DIST_DIR/$DEB_NAME" ]; then
    echo "error: $DIST_DIR/$DEB_NAME not found; run package.sh first" >&2
    exit 1
fi

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "error: dpkg-deb not found; install dpkg-dev" >&2
    exit 1
fi

# --- metadata ----------------------------------------------------------------
# uname -m is kernel-speak; map the two architectures we build for to the
# Debian names, and pass anything else through with a warning.
case "$(uname -m)" in
    x86_64) ARCH="amd64" ;;
    aarch64) ARCH="arm64" ;;
    *) ARCH="$(uname -m)"; echo "warning: unrecognised arch $ARCH" >&2 ;;
esac

MAINTAINER="$(git config user.name 2>/dev/null) <$(git config user.email 2>/dev/null)>"
if [ -z "$MAINTAINER" ] || [ "$MAINTAINER" = " <>" ]; then
    MAINTAINER="AULA L99 project <$(git config user.email 2>/dev/null || echo none)>"
fi

# --- stage -------------------------------------------------------------------
ROOT="$SCRIPT_DIR/build/deb-root"
rm -rf "$ROOT"
mkdir -p "$ROOT/DEBIAN" \
    "$ROOT/usr/bin" \
    "$ROOT/usr/lib/$DEB_NAME" \
    "$ROOT/usr/lib/udev/rules.d" \
    "$ROOT/usr/share/applications" \
    "$ROOT/usr/share/icons/hicolor/256x256/apps" \
    "$ROOT/usr/share/doc/$DEB_NAME"

# The dist is copied wholesale minus the tarball's own install.sh and @EXEC@
# .desktop template: the .deb provides both properly under /usr/share, and a
# per-user installer that overwrites them would be wrong.
cp -a "$DIST_DIR/." "$ROOT/usr/lib/$DEB_NAME/"
rm -f "$ROOT/usr/lib/$DEB_NAME/install.sh" "$ROOT/usr/lib/$DEB_NAME/$DEB_NAME.desktop"

# A wrapper rather than a symlink: Nuitka resolves its resource paths from the
# binary's location, and argv[0] of a symlink is the *link's* path, not the
# target's. Three lines of shell are cheaper than betting on that.
cat > "$ROOT/usr/bin/$DEB_NAME" <<'SH'
#!/bin/sh
exec /usr/lib/aula-l99-gui/aula-l99-gui "$@"
SH
chmod +x "$ROOT/usr/bin/$DEB_NAME"

cp "$SCRIPT_DIR/packaging/90-aula-l99.rules" "$ROOT/usr/lib/udev/rules.d/"

# Fixed paths, so no @EXEC@ placeholder: the deb owns where it lives.
cat > "$ROOT/usr/share/applications/$DEB_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=AULA L99 GUI
GenericName=Keyboard control
Comment=Control the AULA L99 keyboard lighting and touchscreen
Exec=/usr/bin/$DEB_NAME
Icon=$DEB_NAME
Terminal=false
Categories=Settings;HardwareSettings;
EOF

cp "$ROOT/usr/lib/$DEB_NAME/icon.png" \
    "$ROOT/usr/share/icons/hicolor/256x256/apps/$DEB_NAME.png"

cp "$SCRIPT_DIR/LICENSE" "$ROOT/usr/share/doc/$DEB_NAME/copyright"
gzip -9 -c "$SCRIPT_DIR/CHANGELOG.md" > "$ROOT/usr/share/doc/$DEB_NAME/changelog.gz"

# Refresh the desktop database (harmless to run anyway) and reload/trigger
# udev so the new hidraw rule takes effect for a freshly plugged keyboard
# without requiring a reboot. All best-effort.
cat > "$ROOT/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
fi
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger --subsystem-match=hidraw 2>/dev/null || true
exit 0
SH
chmod +x "$ROOT/DEBIAN/postinst"

INSTALLED_SIZE="$(du -sk "$ROOT/usr" | cut -f1)"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: $DEB_NAME
Version: $PACKAGE_VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: $MAINTAINER
Recommends: ffmpeg, alsa-utils
Installed-Size: $INSTALLED_SIZE
Description: PySide6 GUI for the AULA L99 keyboard and touchscreen
 Control the AULA L99 keyboard's lighting, per-key effects and saved
 profiles, drive its touchscreen panel (images, GIFs, video), and put
 CPU/GPU/weather readouts on the panel's system-monitor display.
 .
 This package is the Nuitka-compiled build and carries its own CPython and
 Qt, so no Python runtime is needed. ffmpeg is required for video sources
 on the Touchscreen tab and arecord (from alsa-utils) for the Music tab's
 live spectrum capture; apt installs both by default.
 .
 The bundled udev rule grants the logged-in desktop session access to the
 keyboard's hidraw node, so no manual setup is needed.
EOF

# --- build -------------------------------------------------------------------
DEB_PATH="$SCRIPT_DIR/build/${DEB_NAME}_${PACKAGE_VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$ROOT" "$DEB_PATH" >/dev/null

echo "built: $DEB_PATH ($(du -h "$DEB_PATH" | cut -f1))"

# --- verify ------------------------------------------------------------------
dpkg-deb --info "$DEB_PATH"
dpkg-deb -c "$DEB_PATH" >/dev/null
echo "files: $(dpkg-deb -c "$DEB_PATH" | wc -l)"
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$ROOT/usr/share/applications/$DEB_NAME.desktop"
fi
if command -v lintian >/dev/null 2>&1; then
    lintian --no-tag-display-limit "$DEB_PATH" 2>/dev/null || true
fi
