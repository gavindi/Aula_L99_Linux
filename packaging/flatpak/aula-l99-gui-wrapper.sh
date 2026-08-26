#!/bin/sh
# /app/bin entry point installed by the flatpak manifest. Execs the real
# binary by its absolute /app path, never a symlink -- Nuitka resolves its
# own resource paths from the binary's location, the same reasoning as the
# wrapper make_deb.sh stages at /usr/bin.
exec /app/lib/aula-l99-gui/aula-l99-gui "$@"
