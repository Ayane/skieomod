#!/usr/bin/env python3
"""Verify Ski-E-O!'s 1024 serialized Chaos heightfields against a 2017² R16."""
from __future__ import annotations

import argparse
from pathlib import Path
import struct

import numpy as np


COMPONENT_SIDE = 64
COMPONENT_QUADS = 63
COMPONENT_COUNT = 32 * 32
EXTRAS_SIZE = 12825
HEIGHTS_OFFSET = 50
MINIMUM_OFFSET = 8254
MAXIMUM_OFFSET = 8262
RANGE_OFFSET = 8274
HEIGHT_PER_UNIT_OFFSET = 8282
LOW_RESOLUTION_OFFSET = 12267
LOCAL_BOUNDS_MINIMUM_Z_OFFSET = 12809
LOCAL_BOUNDS_MAXIMUM_Z_OFFSET = 12821
HEIGHTFIELD_PREFIX = bytes.fromhex(
    "000000000100000001000000093200000000000001000000000000000c000000"
    "00010000000c080000000200000000100000"
)


def find_heightfields(data: bytes) -> list[int]:
    offsets: list[int] = []
    cursor = 0
    while True:
        offset = data.find(HEIGHTFIELD_PREFIX, cursor)
        if offset < 0:
            return offsets
        offsets.append(offset)
        cursor = offset + 1


def expected_quantized(raw: np.ndarray) -> tuple[np.ndarray, int, int, float]:
    minimum = int(raw.min())
    maximum = int(raw.max())
    value_range = maximum - minimum
    if value_range == 0:
        return np.zeros(raw.shape, dtype=np.uint16), minimum, maximum, 0.0
    height_per_unit = value_range / 65535.0
    quantized = np.floor((raw - minimum) / height_per_unit).astype(np.uint16)
    return quantized, minimum, maximum, height_per_unit


def expected_low_resolution(quantized: np.ndarray) -> np.ndarray:
    result = np.empty((11, 11, 2), dtype="<u2")
    for low_y in range(11):
        for low_x in range(11):
            block = quantized[
                low_y * 6:min(low_y * 6 + 7, 64),
                low_x * 6:min(low_x * 6 + 7, 64),
            ]
            result[low_y, low_x] = (block.min(), block.max())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("uexp", type=Path)
    parser.add_argument("heightmap", type=Path)
    args = parser.parse_args()

    heightmap = np.fromfile(args.heightmap, dtype="<u2")
    if heightmap.size != 2017 * 2017:
        parser.error(f"heightmap has {heightmap.size} samples instead of 2017²")
    heightmap = heightmap.reshape(2017, 2017).astype(np.int32) - 32768

    data = args.uexp.read_bytes()
    offsets = find_heightfields(data)
    if len(offsets) != COMPONENT_COUNT:
        raise ValueError(f"found {len(offsets)} Chaos heightfields instead of 1024")

    for component, offset in enumerate(offsets):
        blob = data[offset:offset + EXTRAS_SIZE]
        if len(blob) != EXTRAS_SIZE:
            raise ValueError(f"component {component}: truncated heightfield")
        component_y, component_x = divmod(component, 32)
        raw = heightmap[
            component_y * COMPONENT_QUADS:
            component_y * COMPONENT_QUADS + COMPONENT_SIDE,
            component_x * COMPONENT_QUADS:
            component_x * COMPONENT_QUADS + COMPONENT_SIDE,
        ]
        expected, minimum, maximum, height_per_unit = expected_quantized(raw)
        actual = np.frombuffer(
            blob, dtype="<u2", count=COMPONENT_SIDE ** 2,
            offset=HEIGHTS_OFFSET,
        ).reshape(COMPONENT_SIDE, COMPONENT_SIDE)
        if not np.array_equal(actual, expected):
            raise ValueError(f"component {component}: height samples differ")

        values = (
            struct.unpack_from("<d", blob, MINIMUM_OFFSET)[0],
            struct.unpack_from("<d", blob, MAXIMUM_OFFSET)[0],
            struct.unpack_from("<d", blob, RANGE_OFFSET)[0],
            struct.unpack_from("<d", blob, HEIGHT_PER_UNIT_OFFSET)[0],
        )
        expected_values = (
            float(minimum), float(maximum), float(maximum - minimum),
            height_per_unit,
        )
        if values != expected_values:
            raise ValueError(
                f"component {component}: range fields {values} != {expected_values}"
            )

        actual_low = np.frombuffer(
            blob, dtype="<u2", count=11 * 11 * 2,
            offset=LOW_RESOLUTION_OFFSET,
        ).reshape(11, 11, 2)
        if not np.array_equal(actual_low, expected_low_resolution(expected)):
            raise ValueError(f"component {component}: low-resolution bounds differ")

        decoded_minimum = minimum + int(expected.min()) * height_per_unit
        decoded_maximum = minimum + int(expected.max()) * height_per_unit
        expected_minimum_bytes = struct.pack("<f", decoded_minimum - 0.0001)
        expected_maximum_bytes = struct.pack("<f", decoded_maximum + 0.0001)
        if blob[
            LOCAL_BOUNDS_MINIMUM_Z_OFFSET:LOCAL_BOUNDS_MINIMUM_Z_OFFSET + 4
        ] != expected_minimum_bytes:
            raise ValueError(f"component {component}: local minimum bound differs")
        if blob[
            LOCAL_BOUNDS_MAXIMUM_Z_OFFSET:LOCAL_BOUNDS_MAXIMUM_Z_OFFSET + 4
        ] != expected_maximum_bytes:
            raise ValueError(f"component {component}: local maximum bound differs")

    print(f"Verified {len(offsets)} Chaos heightfields against {args.heightmap}")


if __name__ == "__main__":
    main()
