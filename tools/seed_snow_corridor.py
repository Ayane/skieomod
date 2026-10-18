#!/usr/bin/env python3
"""Replace Ski-E-O saved snow tiles with tiles covering a quadratic trail.

The global snow texture is not sufficient for trail skiability.  Ski-E-O also
serializes a cache of 256x256 RG16F tiles and queries that cache along a trail.
This tool preserves a previously seeded tile payload, but assigns the resident
tile budget to a requested quadratic Bezier corridor.
"""

from __future__ import annotations

import argparse
import math
import struct
from pathlib import Path


def find_fstring(blob: bytes, value: bytes) -> int:
    needle = value + b"\0"
    position = blob.find(needle)
    if position < 4 or blob.find(needle, position + 1) >= 0:
        raise ValueError(f"expected one FString {value!r}")
    if struct.unpack_from("<I", blob, position - 4)[0] != len(needle):
        raise ValueError(f"invalid FString length before {value!r}")
    return position


def point(value: str) -> tuple[float, float]:
    fields = value.split(",")
    if len(fields) != 2:
        raise argparse.ArgumentTypeError("expected X,Y")
    try:
        return float(fields[0]), float(fields[1])
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected numeric X,Y") from error


def corridor_tiles(
    start: tuple[float, float],
    control: tuple[float, float],
    end: tuple[float, float],
    world_size: float,
    offset_x: int,
    offset_y: int,
) -> list[tuple[int, int]]:
    # Oversample relative to a tile so every crossed tile is retained.  Add a
    # four-neighbour cross to cover the full painted corridor and rounding at
    # tile boundaries without spending the 256-tile cache on its four corners.
    chord = math.dist(start, control) + math.dist(control, end)
    steps = max(1024, math.ceil(chord / world_size) * 32)
    centerline: set[tuple[int, int]] = set()
    for index in range(steps + 1):
        t = index / steps
        u = 1.0 - t
        x = u * u * start[0] + 2.0 * u * t * control[0] + t * t * end[0]
        y = u * u * start[1] + 2.0 * u * t * control[1] + t * t * end[1]
        centerline.add((
            math.floor(x / world_size) + offset_x,
            math.floor(y / world_size) + offset_y,
        ))

    shifts = ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1))
    tiles = {
        (x + shift_x, y + shift_y)
        for x, y in centerline
        for shift_x, shift_y in shifts
    }
    return sorted(tiles, key=lambda item: (item[1], item[0]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=point, required=True)
    parser.add_argument("--control", type=point, required=True)
    parser.add_argument("--end", type=point, required=True)
    parser.add_argument("--tile-world-size", type=float, default=3200.0)
    parser.add_argument("--tile-offset-x", type=int, default=132)
    parser.add_argument("--tile-offset-y", type=int, default=132)
    parser.add_argument("--max-tiles", type=int, default=256)
    args = parser.parse_args()

    blob = bytearray(args.input.read_bytes())
    if not blob.startswith(b"GVAS"):
        raise ValueError(f"{args.input} is not a GVAS archive")
    if not math.isfinite(args.tile_world_size) or args.tile_world_size <= 0.0:
        raise ValueError("tile world size must be positive")

    snow_name = find_fstring(blob, b"SnowData")
    grid_name = find_fstring(blob, b"GPUTextureResolution")
    if not snow_name < grid_name:
        raise ValueError("unexpected SnowData property order")
    snow_payload_start = grid_name - 4
    snow_size_offset = snow_payload_start - 5
    snow_size = struct.unpack_from("<I", blob, snow_size_offset)[0]

    tile_entries_name = find_fstring(blob, b"TileEntries")
    virtual_coord_name = blob.find(b"VirtualCoord\0", tile_entries_name)
    if virtual_coord_name < 8:
        raise ValueError("first SnowTileSaveEntry was not found")
    first_entry_start = virtual_coord_name - 4
    array_start = first_entry_start - 4
    array_size_offset = array_start - 5
    old_array_size = struct.unpack_from("<I", blob, array_size_offset)[0]
    old_count = struct.unpack_from("<I", blob, array_start)[0]
    array_end = array_start + old_array_size
    if old_count < 2 or array_end > len(blob):
        raise ValueError("invalid SnowTileSaveEntry array")

    second_coord_name = blob.find(
        b"VirtualCoord\0", virtual_coord_name + 1, array_end)
    if second_coord_name < 4:
        raise ValueError("second SnowTileSaveEntry was not found")
    second_entry_start = second_coord_name - 4
    template = bytes(blob[first_entry_start:second_entry_start])
    coord_offset = virtual_coord_name + len(b"VirtualCoord\0") - first_entry_start
    # The two int32 values occur after the StructProperty type information.
    coord_offset = template.find(struct.pack(
        "<ii",
        *struct.unpack_from("<ii", blob, virtual_coord_name + 86),
    ))
    if coord_offset < 0:
        raise ValueError("could not locate VirtualCoord values in tile entry")
    if len(template) * old_count != array_end - first_entry_start:
        raise ValueError("SnowTileSaveEntry records are not fixed-size")

    tiles = corridor_tiles(
        args.start,
        args.control,
        args.end,
        args.tile_world_size,
        args.tile_offset_x,
        args.tile_offset_y,
    )
    if len(tiles) > args.max_tiles:
        raise ValueError(
            f"corridor needs {len(tiles)} tiles, exceeding {args.max_tiles}")

    serialized_entries = bytearray()
    for x, y in tiles:
        entry = bytearray(template)
        struct.pack_into("<ii", entry, coord_offset, x, y)
        serialized_entries.extend(entry)

    old_entries_size = array_end - first_entry_start
    blob[first_entry_start:array_end] = serialized_entries
    delta = len(serialized_entries) - old_entries_size
    new_array_size = 4 + len(serialized_entries)
    struct.pack_into("<I", blob, array_start, len(tiles))
    struct.pack_into("<I", blob, array_size_offset, new_array_size)
    struct.pack_into("<I", blob, snow_size_offset, snow_size + delta)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(blob)
    print(
        f"Replaced {old_count} saved snow tiles with {len(tiles)} corridor "
        f"tiles; virtual bounds X={min(x for x, _ in tiles)}.."
        f"{max(x for x, _ in tiles)}, Y={min(y for _, y in tiles)}.."
        f"{max(y for _, y in tiles)}"
    )


if __name__ == "__main__":
    main()
