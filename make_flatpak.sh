#!/usr/bin/env bash
# Builds the flatpak from the same Nuitka dist package.sh produces, copying
# it into /app rather than recompiling inside flatpak-builder's sandbox --
# the same "ship a prebuilt binary" choice make_deb.sh makes, and it avoids
# duplicating a build that already happened once. Produces a single-file
# .flatpak bundle since there's no hosted flatpak repo to point users at.
#
# Needs the org.freedesktop.Platform/Sdk runtime pinned in the manifest
# already installed (`flatpak install flathub org.freedesktop.Platform//23.08
# org.freedesktop.Sdk//23.08`) -- not done here, since CI installs it once up
# front rather than on every invocation.
#
# Usage: ./make_flatpak.sh [--rebuild]
#   Runs package.sh first if build/aula-l99-gui is missing, or if --rebuild
#   is passed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DIST_DIR="$SCRIPT_DIR/build/aula-l99-gui"
APP_ID="io.github.gavindi.AulaL99Gui"
MANIFEST="$SCRIPT_DIR/packaging/flatpak/$APP_ID.yml"

if [ "${1:-}" = "--rebuild" ] || [ ! -d "$DIST_DIR" ]; then
    "$SCRIPT_DIR/package.sh"
fi

if ! command -v flatpak-builder >/dev/null 2>&1; then
    echo "error: flatpak-builder not found; install with 'apt install flatpak flatpak-builder'" >&2
    exit 1
fi

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' tools/aula_l99_gui/pyproject.toml)"
BUILD_DIR="$SCRIPT_DIR/build/flatpak-build"
REPO_DIR="$SCRIPT_DIR/build/flatpak-repo"
BUNDLE="$SCRIPT_DIR/build/aula-l99-gui-$VERSION.flatpak"

rm -rf "$BUILD_DIR" "$REPO_DIR"
# --repo builds and exports to a local repo in one step; build-bundle then
# flattens that repo into the single distributable file.
flatpak-builder --force-clean --repo="$REPO_DIR" "$BUILD_DIR" "$MANIFEST"
flatpak build-bundle "$REPO_DIR" "$BUNDLE" "$APP_ID"

echo "built: $BUNDLE ($(du -h "$BUNDLE" | cut -f1))"
