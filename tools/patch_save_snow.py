#!/usr/bin/env python3
"""Seed Ski-E-O's serialized global snow texture with uniform native depths."""

from __future__ import annotations

import argparse
import math
import struct
import zlib
from pathlib import Path


def find_fstring(blob: bytes, value: bytes) -> int:
    needle = value + b"\0"
    position = blob.find(needle)
    if position < 4 or blob.find(needle, position + 1) >= 0:
        raise ValueError(f"expected one FString {value!r}")
    if struct.unpack_from("<I", blob, position - 4)[0] != len(needle):
        raise ValueError(f"invalid FString length before {value!r}")
    return position


def find_bulk_zlib_stream(
    blob: bytes, start: int, stop: int, payload_limit: int
) -> int:
    candidates = []
    for signature in (b"\x78\x9c", b"\x78\xda", b"\x78\x01"):
        search_at = start
        while True:
            position = blob.find(signature, search_at, stop)
            if position < 0:
                break
            if position >= 9:
                byte_count = struct.unpack_from("<I", blob, position - 4)[0]
                property_size = struct.unpack_from("<I", blob, position - 9)[0]
                if (
                    property_size == byte_count + 4
                    and byte_count > 0
                    and position + byte_count <= payload_limit
                ):
                    candidates.append(position)
            search_at = position + 1
    if len(candidates) != 1:
        raise ValueError(
            f"expected one SkiEOBulkBytes zlib stream, found {candidates}")
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--packed-cm", type=float, default=80.0)
    parser.add_argument("--fresh-cm", type=float, default=20.0)
    args = parser.parse_args()

    for label, value in (
        ("packed", args.packed_cm),
        ("fresh", args.fresh_cm),
    ):
        if not math.isfinite(value) or value < 0.0 or value > 2048.0:
            raise ValueError(f"invalid {label} snow depth: {value}")

    blob = bytearray(args.input.read_bytes())
    if not blob.startswith(b"GVAS"):
        raise ValueError(f"{args.input} is not a GVAS archive")

    snow_name = find_fstring(blob, b"SnowData")
    grid_name = find_fstring(blob, b"GPUTextureResolution")
    texture_name = find_fstring(blob, b"CompressedGPUTexture")
    if not snow_name < grid_name < texture_name:
        raise ValueError("unexpected SnowData property order")

    # The outer StructProperty size precedes its first nested property's
    # FString, with one property-tag flag byte between them.
    snow_payload_start = grid_name - 4
    snow_size_offset = snow_payload_start - 5
    snow_size = struct.unpack_from("<I", blob, snow_size_offset)[0]
    snow_payload_end = snow_payload_start + snow_size
    if snow_payload_end > len(blob):
        raise ValueError("SnowData payload extends past the SaveGame")

    # GPUTextureResolution is the first nested IntProperty. Its serialized
    # value is the four bytes immediately before the next property FString.
    resolution = struct.unpack_from("<I", blob, texture_name - 8)[0]
    if resolution <= 0 or resolution > 16384:
        raise ValueError(f"invalid snow grid resolution: {resolution}")

    zlib_start = find_bulk_zlib_stream(
        blob, texture_name, texture_name + 512, snow_payload_end)

    byte_count_offset = zlib_start - 4
    property_size_offset = zlib_start - 9
    compressed_size = struct.unpack_from("<I", blob, byte_count_offset)[0]
    property_size = struct.unpack_from("<I", blob, property_size_offset)[0]
    if property_size != compressed_size + 4:
        raise ValueError(
            "unexpected SkiEOBulkBytes size: "
            f"property={property_size}, bytes={compressed_size}")
    compressed_end = zlib_start + compressed_size
    if compressed_end > snow_payload_end:
        raise ValueError("compressed GPU texture extends past SnowData")

    decompressor = zlib.decompressobj()
    old_raw = decompressor.decompress(bytes(blob[zlib_start:compressed_end]))
    old_raw += decompressor.flush()
    expected_raw_size = resolution * resolution * 2 * 2
    if len(old_raw) != expected_raw_size:
        raise ValueError(
            f"decoded texture has {len(old_raw)} bytes instead of "
            f"{expected_raw_size} ({resolution}x{resolution} RG16F)")

    pixel = struct.pack("<ee", args.packed_cm, args.fresh_cm)
    new_raw = pixel * (resolution * resolution)
    new_compressed = zlib.compress(new_raw, level=6)
    delta = len(new_compressed) - compressed_size

    blob[zlib_start:compressed_end] = new_compressed
    struct.pack_into("<I", blob, byte_count_offset, len(new_compressed))
    struct.pack_into("<I", blob, property_size_offset, len(new_compressed) + 4)
    struct.pack_into("<I", blob, snow_size_offset, snow_size + delta)

    # The trail skiability query reads the resident high-resolution tile
    # cache, not only the coarse global texture. TileEntries is one tagged
    # struct array whose size covers every SnowTileSaveEntry. Patch every
    # CompressedPixels RG16F payload and then adjust the array and SnowData
    # sizes by the cumulative byte delta.
    tile_entries_name = find_fstring(blob, b"TileEntries")
    virtual_coord_name = blob.find(b"VirtualCoord\0", tile_entries_name)
    if virtual_coord_name < 8:
        raise ValueError("first SnowTileSaveEntry was not found")
    first_entry_start = virtual_coord_name - 4
    tile_array_start = first_entry_start - 4
    tile_size_offset = tile_array_start - 5
    tile_array_size = struct.unpack_from("<I", blob, tile_size_offset)[0]
    tile_count = struct.unpack_from("<I", blob, tile_array_start)[0]
    tile_array_end = tile_array_start + tile_array_size
    if tile_count <= 0 or tile_array_end > len(blob):
        raise ValueError(
            f"invalid TileEntries array: count={tile_count}, size={tile_array_size}")

    tile_replacements: list[tuple[int, int, int, int, bytes]] = []
    search_at = tile_array_start
    while True:
        pixels_name = blob.find(b"CompressedPixels\0", search_at, tile_array_end)
        if pixels_name < 0:
            break
        tile_zlib_start = find_bulk_zlib_stream(
            blob,
            pixels_name,
            min(pixels_name + 512, tile_array_end),
            tile_array_end,
        )
        tile_count_offset = tile_zlib_start - 4
        tile_property_size_offset = tile_zlib_start - 9
        tile_compressed_size = struct.unpack_from(
            "<I", blob, tile_count_offset)[0]
        tile_property_size = struct.unpack_from(
            "<I", blob, tile_property_size_offset)[0]
        if tile_property_size != tile_compressed_size + 4:
            raise ValueError("unexpected tile SkiEOBulkBytes size")
        tile_compressed_end = tile_zlib_start + tile_compressed_size
        if tile_compressed_end > tile_array_end:
            raise ValueError("compressed tile extends past TileEntries")

        tile_raw = zlib.decompress(
            bytes(blob[tile_zlib_start:tile_compressed_end]))
        tile_resolution = round(math.sqrt(len(tile_raw) / 4))
        if tile_resolution * tile_resolution * 4 != len(tile_raw):
            raise ValueError(
                f"tile decoded to unexpected RG16F size: {len(tile_raw)}")
        tile_new_raw = pixel * (tile_resolution * tile_resolution)
        tile_new_compressed = zlib.compress(tile_new_raw, level=6)
        tile_replacements.append((
            tile_zlib_start,
            tile_compressed_end,
            tile_count_offset,
            tile_property_size_offset,
            tile_new_compressed,
        ))
        search_at = tile_compressed_end

    if len(tile_replacements) != tile_count:
        raise ValueError(
            f"found {len(tile_replacements)} compressed tiles, expected {tile_count}")

    tile_delta = 0
    for (
        tile_zlib_start,
        tile_compressed_end,
        tile_count_offset,
        tile_property_size_offset,
        tile_new_compressed,
    ) in reversed(tile_replacements):
        old_size = tile_compressed_end - tile_zlib_start
        blob[tile_zlib_start:tile_compressed_end] = tile_new_compressed
        struct.pack_into(
            "<I", blob, tile_count_offset, len(tile_new_compressed))
        struct.pack_into(
            "<I", blob, tile_property_size_offset,
            len(tile_new_compressed) + 4)
        tile_delta += len(tile_new_compressed) - old_size

    struct.pack_into(
        "<I", blob, tile_size_offset, tile_array_size + tile_delta)
    struct.pack_into(
        "<I", blob, snow_size_offset, snow_size + delta + tile_delta)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(blob)
    print(
        f"Seeded {resolution}x{resolution} RG16F snow texture: "
        f"packed={args.packed_cm:g} cm, fresh={args.fresh_cm:g} cm; "
        f"zlib {compressed_size} -> {len(new_compressed)} bytes; "
        f"{tile_count} resident tile(s) seeded"
    )


if __name__ == "__main__":
    main()
