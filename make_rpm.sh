#!/usr/bin/env bash
# Packs the same build/deb-root tree make_deb.sh stages -- usr/bin wrapper,
# usr/lib dist, desktop entry, icon, udev rule, doc/copyright, changelog.gz,
# postinst -- into an .rpm via fpm, instead of restaging any of it. There is
# no .spec file because there is nothing here for rpmbuild to compile: like
# the .deb, this ships a prebuilt binary.
#
# Usage: ./make_rpm.sh [--rebuild]
#   Always (re)runs make_deb.sh first: it's the source of the staged tree,
#   and is itself cheap once build/aula-l99-gui exists (staging only, not a
#   Nuitka rebuild). --rebuild is forwarded to make_deb.sh, forcing a fresh
#   Nuitka compile before staging.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

"$SCRIPT_DIR/make_deb.sh" "$@"

ROOT="$SCRIPT_DIR/build/deb-root"
RPM_NAME="aula-l99-gui"
PACKAGE_VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' tools/aula_l99_gui/pyproject.toml)"

case "$(uname -m)" in
    x86_64) ARCH="x86_64" ;;
    aarch64) ARCH="aarch64" ;;
    *) ARCH="$(uname -m)"; echo "warning: unrecognised arch $ARCH" >&2 ;;
esac

if ! command -v fpm >/dev/null 2>&1; then
    echo "error: fpm not found; install with 'gem install fpm' (needs ruby, rpm)" >&2
    exit 1
fi

MAINTAINER="$(git config user.name 2>/dev/null) <$(git config user.email 2>/dev/null)>"
if [ -z "$MAINTAINER" ] || [ "$MAINTAINER" = " <>" ]; then
    MAINTAINER="AULA L99 project <$(git config user.email 2>/dev/null || echo none)>"
fi

RPM_PATH="$SCRIPT_DIR/build/${RPM_NAME}-${PACKAGE_VERSION}-1.${ARCH}.rpm"
rm -f "$RPM_PATH"

# --rpm-tag injects raw spec lines; RPM's weak-dependency tags need rpm>=4.12
# (any current Fedora/RHEL/openSUSE), matching the .deb's Recommends (soft,
# not Depends -- the app checks PATH itself and degrades gracefully).
# --after-install reuses the .deb's postinst verbatim: it's plain POSIX sh.
fpm -s dir -t rpm \
    -n "$RPM_NAME" -v "$PACKAGE_VERSION" -a "$ARCH" \
    --license "GPL-2.0-only" \
    --maintainer "$MAINTAINER" \
    --url "https://github.com/gavindi/Aula_L99_Linux" \
    --description "PySide6 GUI for the AULA L99 keyboard and touchscreen. Control the keyboard's lighting, per-key effects and saved profiles, drive its touchscreen panel, and put system-monitor readouts on the panel's display. Nuitka-compiled and self-contained, so no Python runtime is needed. ffmpeg is recommended for Touchscreen-tab video and alsa-utils for the Music tab. The bundled udev rule grants hidraw access to the logged-in desktop session." \
    --rpm-tag "Recommends: ffmpeg" \
    --rpm-tag "Recommends: alsa-utils" \
    --after-install "$ROOT/DEBIAN/postinst" \
    --directories "/usr/lib/$RPM_NAME" \
    --force \
    -C "$ROOT" \
    -p "$RPM_PATH" \
    usr

echo "built: $RPM_PATH ($(du -h "$RPM_PATH" | cut -f1))"
rpm -qip "$RPM_PATH" 2>/dev/null || true
