#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
gcc -shared -fPIC -O2 -Wall -Wextra -o wine_ioctl_shim.so wine_ioctl_shim.c -ldl
echo "built: $(pwd)/wine_ioctl_shim.so"
