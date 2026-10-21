#!/bin/sh
set -eu
cd "$(dirname "$0")"
out=../../mod/SkiEO-CustomMaps/Scripts
# No timestamps: immutable bootstrap bytes must remain reproducible.
flags='-O2 -s -Wall -Wextra -Wno-misleading-indentation -Wno-unused-function -Wl,--no-insert-timestamp'
x86_64-w64-mingw32-gcc $flags -shared bootstrap.c -o "$out/skieo_update_bootstrap.dll" -lbcrypt
x86_64-w64-mingw32-gcc $flags -municode updater.c -o "$out/skieo_updater.exe" -lbcrypt
