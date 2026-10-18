#!/usr/bin/env python3
"""Inspect global and resident RG16F snow values in a Ski-E-O GVAS save."""

from __future__ import annotations

import argparse
import math
import statistics
import struct
import zlib
from pathlib import Path

from patch_save_snow import find_bulk_zlib_stream, find_fstring


def summarize(label: str, raw: bytes) -> None:
    channels = [[], []]
    for first, second in struct.iter_unpack("<ee", raw):
        if math.isfinite(first):
            channels[0].append(float(first))
        if math.isfinite(second):
            channels[1].append(float(second))
    fields = []
    for index, values in enumerate(channels):
        values.sort()
        fields.append(
            f"C{index}: min={values[0]:g}, median={statistics.median(values):g}, "
            f"p95={values[round((len(values) - 1) * .95)]:g}, "
            f"max={values[-1]:g}, mean={statistics.fmean(values):g}"
        )
    print(f"{label}: " + "; ".join(fields))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("save", type=Path)
    parser.add_argument("--tile", type=str)
    args = parser.parse_args()
    target = None
    if args.tile:
        target = tuple(int(value) for value in args.tile.split(","))
        if len(target) != 2:
            raise ValueError("tile must be X,Y")

    blob = args.save.read_bytes()
    snow_name = find_fstring(blob, b"SnowData")
    grid_name = find_fstring(blob, b"GPUTextureResolution")
    texture_name = find_fstring(blob, b"CompressedGPUTexture")
    snow_payload_start = grid_name - 4
    snow_size = struct.unpack_from("<I", blob, snow_payload_start - 5)[0]
    snow_end = snow_payload_start + snow_size
    resolution = struct.unpack_from("<I", blob, texture_name - 8)[0]
    global_zlib = find_bulk_zlib_stream(
        blob, texture_name, texture_name + 512, snow_end)
    global_size = struct.unpack_from("<I", blob, global_zlib - 4)[0]
    global_raw = zlib.decompress(blob[global_zlib:global_zlib + global_size])
    summarize(f"global {resolution}x{resolution}", global_raw)

    tile_entries_name = find_fstring(blob, b"TileEntries")
    first_coord_name = blob.find(b"VirtualCoord\0", tile_entries_name)
    array_start = first_coord_name - 8
    array_size = struct.unpack_from("<I", blob, array_start - 5)[0]
    array_end = array_start + array_size
    count = struct.unpack_from("<I", blob, array_start)[0]
    found = 0
    search_at = first_coord_name
    while True:
        coord_name = blob.find(b"VirtualCoord\0", search_at, array_end)
        if coord_name < 0:
            break
        coord = struct.unpack_from("<ii", blob, coord_name + 86)
        pixels_name = blob.find(b"CompressedPixels\0", coord_name, array_end)
        zlib_start = find_bulk_zlib_stream(
            blob, pixels_name, min(pixels_name + 512, array_end), array_end)
        compressed_size = struct.unpack_from("<I", blob, zlib_start - 4)[0]
        if target is None or coord == target:
            raw = zlib.decompress(blob[zlib_start:zlib_start + compressed_size])
            summarize(f"tile {coord[0]},{coord[1]}", raw)
            found += 1
            if target is not None:
                break
        search_at = zlib_start + compressed_size
    print(f"resident tiles: {count}; inspected: {found}")
    if target is not None and found == 0:
        raise ValueError(f"tile {target} is not resident")


if __name__ == "__main__":
    main()
