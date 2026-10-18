#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
x86_64-w64-mingw32-gcc -shared -O2 -Wall -Wextra -DMINIZ_NO_ARCHIVE_APIS -DMINIZ_NO_STDIO \
  native/SkiEORepository/repository.c native/SkiEORepository/miniz_tinfl.c \
  -lwinhttp -lbcrypt -o mod/SkiEO-CustomMaps/Scripts/skieo_repository.dll
