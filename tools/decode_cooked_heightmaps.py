#!/usr/bin/env python3
"""Decode Ski-E-O!'s 2017² Landscape base heightmap from its legacy UBULK."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from encode_cooked_heightmaps import PROVIDER_TILE_ORDER


BASE_MIP_SIZES = (512, 256, 128)
LANDSCAPE_SIDE = 2017


def decode_custom_mip(payload: bytes, full_side: int) -> np.ndarray:
    unique_side = full_side - 7
    sample_count = unique_side * unique_side
    deltas = np.frombuffer(payload, dtype=">u2", count=sample_count)
    values = (
        32768 + np.cumsum(deltas.astype(np.uint64), dtype=np.uint64)
    ) & 0xFFFF
    return values.astype(np.uint16).reshape(unique_side, unique_side)


def decode_ubulk(path: Path) -> np.ndarray:
    data = path.read_bytes()
    grid = np.empty((LANDSCAPE_SIDE, LANDSCAPE_SIDE), dtype=np.uint16)
    cursor = 0

    for provider_index, tile_number in enumerate(PROVIDER_TILE_ORDER):
        del provider_index
        for mip, side in enumerate(BASE_MIP_SIZES):
            payload_size = 2 * (side - 7) ** 2 + 2 * (4 * side - 4)
            payload = data[cursor:cursor + payload_size]
            if len(payload) != payload_size:
                raise ValueError("Truncated UBULK")
            cursor += payload_size
            if mip != 0:
                continue

            tile = decode_custom_mip(payload, side)
            tile_x, tile_y = tile_number % 4, tile_number // 4
            grid[
                tile_y * 504:tile_y * 504 + 505,
                tile_x * 504:tile_x * 504 + 505,
            ] = tile

    if cursor != len(data):
        raise ValueError(f"Consumed {cursor} bytes from a {len(data)}-byte UBULK")
    return grid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ubulk", type=Path)
    parser.add_argument("output_r16", type=Path)
    args = parser.parse_args()

    grid = decode_ubulk(args.ubulk)
    args.output_r16.parent.mkdir(parents=True, exist_ok=True)
    grid.astype("<u2").tofile(args.output_r16)
    print(
        f"Wrote {args.output_r16}: {grid.shape[1]}x{grid.shape[0]}, "
        f"R16 {int(grid.min())}-{int(grid.max())}"
    )


if __name__ == "__main__":
    main()
