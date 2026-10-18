#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
x86_64-w64-mingw32-gcc -shared -O2 -s -Wall -Wextra \
  native/SkiEOTrailRatings/trail_ratings.c \
  native/SkiEOTrailRatings/vendor/minhook/src/hook.c \
  native/SkiEOTrailRatings/vendor/minhook/src/buffer.c \
  native/SkiEOTrailRatings/vendor/minhook/src/trampoline.c \
  native/SkiEOTrailRatings/vendor/minhook/src/hde/hde64.c \
  -o mod/SkiEO-CustomMaps/Scripts/skieo_trail_ratings.dll
