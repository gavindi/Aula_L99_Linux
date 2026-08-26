#!/usr/bin/env bash
# Packs the Nuitka dist package.sh produces into a classic-confinement snap.
# Classic confinement is required because this app needs direct /dev/hidraw
# access with no store-side interface auto-connection to lean on -- see
# packaging/snap/snapcraft.yaml for the full rationale. A classic snap still
# needs packaging/90-aula-l99.rules installed separately for hidraw access,
# same as the tarball, and is installed with `snap install --classic
# --dangerous` since it isn't headed to the Snap Store.
#
# snapcraft only looks for snap/snapcraft.yaml relative to the current
# directory, so the manifest is kept under packaging/ (alongside the other
# static packaging metadata) and copied into place here rather than living
# where snapcraft expects it in the working tree.
#
# Usage: ./make_snap.sh [--rebuild]
#   Runs package.sh first if build/aula-l99-gui is missing, or if --rebuild
#   is passed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DIST_DIR="$SCRIPT_DIR/build/aula-l99-gui"

if [ "${1:-}" = "--rebuild" ] || [ ! -d "$DIST_DIR" ]; then
    "$SCRIPT_DIR/package.sh"
fi

if ! command -v snapcraft >/dev/null 2>&1; then
    echo "error: snapcraft not found; install with 'sudo snap install snapcraft --classic'" >&2
    exit 1
fi

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' tools/aula_l99_gui/pyproject.toml)"

rm -rf "$SCRIPT_DIR/snap"
mkdir -p "$SCRIPT_DIR/snap"
sed "s/^version: .*/version: '$VERSION'/" \
    "$SCRIPT_DIR/packaging/snap/snapcraft.yaml" > "$SCRIPT_DIR/snap/snapcraft.yaml"

# Cleaned up on both normal exit and failure, so a broken build never leaves
# a stray snap/ dir sitting in the working tree.
trap 'rm -rf "$SCRIPT_DIR/snap"' EXIT

SNAP_PATH="$SCRIPT_DIR/build/aula-l99-gui_${VERSION}_amd64.snap"
snapcraft pack --destructive-mode --output "$SNAP_PATH"

echo "built: $SNAP_PATH ($(du -h "$SNAP_PATH" | cut -f1))"
