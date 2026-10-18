#!/usr/bin/env python3
"""Replace the 16 cooked Landscape heightmap textures in a Ski-E-O level.

This is an experimental UE 5.8 demo-specific encoder. It reproduces the
ULandscapeTextureStorageProviderFactory layout found in build 25551097:
505x505 unique samples plus duplicated component boundaries in every 512 mip.
It deliberately does not rebuild Chaos collision, the terrain skirt, or the
64 snow-shell meshes. Baked obstacle elevations are handled separately by
UAssetPatcher.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import struct

import numpy as np


MIP_SIZES = (512, 256, 128, 64, 32, 16, 8, 4, 2, 1)
PROVIDER_TILE_ORDER = (0, 1, 10, 11, 12, 13, 14, 15, 2, 3, 4, 5, 6, 7, 8, 9)


def resize_bilinear(source: np.ndarray, side: int) -> np.ndarray:
    if source.shape == (side, side):
        return source.copy()
    positions = np.linspace(0, source.shape[0] - 1, side)
    low = np.floor(positions).astype(np.int32)
    high = np.minimum(low + 1, source.shape[0] - 1)
    share = positions - low
    horizontal = (source[:, low] * (1 - share)[None, :] +
                  source[:, high] * share[None, :])
    result = horizontal[low, :] * (1 - share)[:, None] + horizontal[high, :] * share[:, None]
    return np.rint(result).clip(0, 65535).astype(np.uint16)


def expand_component_boundaries(unique: np.ndarray, full_side: int) -> np.ndarray:
    boundary_offset = full_side // 8
    indices = np.arange(full_side) - np.arange(full_side) // boundary_offset
    if indices.max() != unique.shape[0] - 1:
        raise ValueError("Unexpected landscape boundary geometry")
    return unique[np.ix_(indices, indices)]


def packed_normals(height: np.ndarray, xy_scale: float, z_scale: float) -> tuple[np.ndarray, np.ndarray]:
    if min(height.shape) < 2:
        neutral = np.full(height.shape, 128, dtype=np.uint8)
        return neutral, neutral.copy()
    world_height = (height.astype(np.float64) - 32768.0) * z_scale / 128.0
    dy, dx = np.gradient(world_height, xy_scale)
    length = np.sqrt(dx * dx + dy * dy + 1.0)
    nx = np.rint(128.0 - 127.0 * dx / length).clip(0, 255).astype(np.uint8)
    ny = np.rint(128.0 - 127.0 * dy / length).clip(0, 255).astype(np.uint8)
    return nx, ny


def perimeter_coordinates(side: int):
    for x in range(side):
        yield 0, x
    for y in range(1, side):
        yield y, side - 1
    for x in range(side - 2, -1, -1):
        yield side - 1, x
    for y in range(side - 2, 0, -1):
        yield y, 0


def encode_custom_mip(unique: np.ndarray, full_side: int, xy_scale: float, z_scale: float) -> bytes:
    flat = unique.astype(np.int64).ravel()
    previous = np.concatenate((np.array([32768], dtype=np.int64), flat[:-1]))
    deltas = ((flat - previous) & 0xFFFF).astype(">u2").tobytes()

    full = expand_component_boundaries(unique, full_side)
    nx, ny = packed_normals(full, xy_scale, z_scale)
    perimeter = list(perimeter_coordinates(full_side))
    channels = np.array([(nx[y, x], ny[y, x]) for y, x in perimeter], dtype=np.int16)
    prior = np.vstack((np.array([[128, 128]], dtype=np.int16), channels[:-1]))
    normal_deltas = ((channels - prior) & 0xFF).astype(np.uint8).tobytes()
    result = deltas + normal_deltas
    expected = 2 * (full_side - 7) ** 2 + 2 * (4 * full_side - 4)
    if len(result) != expected:
        raise AssertionError((len(result), expected))
    return result


def encode_raw_mip(height: np.ndarray, xy_scale: float, z_scale: float) -> bytes:
    nx, ny = packed_normals(height, xy_scale, z_scale)
    pixels = np.empty((*height.shape, 4), dtype=np.uint8)
    pixels[..., 0] = nx
    pixels[..., 1] = height & 0xFF
    pixels[..., 2] = height >> 8
    pixels[..., 3] = ny
    return pixels.tobytes()


def build_tile_mips(grid: np.ndarray, tile_number: int, xy_scale: float, z_scale: float) -> list[bytes]:
    tile_x, tile_y = tile_number % 4, tile_number // 4
    unique = grid[tile_y * 504:tile_y * 504 + 505,
                  tile_x * 504:tile_x * 504 + 505]
    if unique.shape != (505, 505):
        raise ValueError(f"Tile {tile_number} falls outside the 2017 grid")
    full_base = expand_component_boundaries(unique, 512)
    result = []
    for mip, side in enumerate(MIP_SIZES):
        mip_xy_scale = xy_scale * (2 ** mip)
        if mip <= 4:
            unique_side = side - 7
            mip_unique = resize_bilinear(unique, unique_side)
            result.append(encode_custom_mip(mip_unique, side, mip_xy_scale, z_scale))
        else:
            mip_height = resize_bilinear(full_base, side)
            result.append(encode_raw_mip(mip_height, mip_xy_scale, z_scale))
    return result


def provider_offsets(data: bytearray) -> list[int]:
    signature = struct.pack("<II", 10, 7)
    results = []
    start = 0
    while True:
        candidate = data.find(signature, start)
        if candidate < 0:
            break
        start = candidate + 1
        try:
            if struct.unpack_from("<I", data, candidate + 32)[0] != 10:
                continue
            offset = candidate + 36
            for mip, side in enumerate(MIP_SIZES):
                width, height, compressed, index = struct.unpack_from("<4I", data, offset)
                if ((width, height, compressed, index % 10) !=
                        (side, side, int(mip <= 4), mip)):
                    raise ValueError
                offset += 16
                if mip >= 3:
                    if mip <= 4:
                        offset += 2 * (side - 7) ** 2 + 2 * (4 * side - 4)
                    else:
                        offset += 4 * side * side
            results.append(candidate)
        except (ValueError, struct.error):
            continue
    if len(results) != 16:
        raise ValueError(f"Expected 16 storage providers in .uexp, found {len(results)}")
    return results


def patch_uexp(path: Path, all_mips: dict[int, list[bytes]], xy_scale: float, z_scale: float) -> None:
    data = bytearray(path.read_bytes())
    offsets = provider_offsets(data)
    for provider_index, offset in enumerate(offsets):
        tile_number = PROVIDER_TILE_ORDER[provider_index]
        mips = all_mips[tile_number]
        struct.pack_into("<ddd", data, offset + 8, xy_scale, xy_scale, z_scale)
        cursor = offset + 36
        for mip, side in enumerate(MIP_SIZES):
            cursor += 16
            if mip >= 3:
                payload = mips[mip]
                data[cursor:cursor + len(payload)] = payload
                cursor += len(payload)
    path.write_bytes(data)


def patch_ubulk(path: Path, all_mips: dict[int, list[bytes]]) -> None:
    original = path.read_bytes()
    result = bytearray()
    cursor = 0
    for provider_index in range(16):
        tile_number = PROVIDER_TILE_ORDER[provider_index]
        for mip in range(3):
            payload = all_mips[tile_number][mip]
            old = original[cursor:cursor + len(payload)]
            if len(old) != len(payload):
                raise ValueError("Truncated .ubulk")
            result.extend(payload)
            cursor += len(payload)
    if cursor != len(original):
        raise ValueError(f"Unexpected .ubulk length: consumed {cursor}, file has {len(original)}")
    path.write_bytes(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("heightmap", type=Path, help="2017x2017 little-endian R16")
    parser.add_argument("uexp", type=Path, help="legacy level export file to patch in place")
    parser.add_argument("ubulk", type=Path, help="legacy level bulk file to patch in place")
    parser.add_argument("--xy-scale", type=float, default=400.0, help="Unreal centimetres per vertex")
    parser.add_argument("--z-scale", type=float, default=320.0, help="Unreal Landscape Z scale")
    args = parser.parse_args()

    grid = np.fromfile(args.heightmap, dtype="<u2")
    if grid.size != 2017 * 2017:
        parser.error(f"heightmap has {grid.size} samples instead of {2017 * 2017}")
    grid = grid.reshape(2017, 2017)
    all_mips = {
        tile: build_tile_mips(grid, tile, args.xy_scale, args.z_scale)
        for tile in range(16)
    }
    patch_uexp(args.uexp, all_mips, args.xy_scale, args.z_scale)
    patch_ubulk(args.ubulk, all_mips)
    print(f"Patched 16 heightmap textures in {args.uexp.name} and {args.ubulk.name}")


if __name__ == "__main__":
    main()
