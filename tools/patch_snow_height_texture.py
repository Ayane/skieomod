#!/usr/bin/env python3
"""Rebuild Ski-E-O!'s 2017² coarse terrain-height texture for a custom map.

The terrain material uses this single-mip grayscale texture as a distant snow
fallback. Keeping the Sugar Bowl texture makes snow bands follow the source
relief even after the Landscape heightmaps have been replaced. Each grayscale
pixel is the high byte of the corresponding Unreal Landscape R16 sample.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import struct

import numpy as np

LANDSCAPE_SIDE = 2017


def snow_pixels(uexp_data: bytes) -> tuple[int, np.ndarray]:
    marker = struct.pack("<IIII", LANDSCAPE_SIDE, LANDSCAPE_SIDE, 1, 12)
    marker_offset = uexp_data.find(marker)
    if marker_offset < 0:
        raise ValueError("2017² snow-height texture header was not found")
    format_offset = marker_offset + len(marker)
    if uexp_data[format_offset:format_offset + 12] != b"PF_B8G8R8A8\0":
        raise ValueError("Snow-height texture is not PF_B8G8R8A8")
    pixel_offset = format_offset + 24
    byte_count = LANDSCAPE_SIDE * LANDSCAPE_SIDE * 4
    pixels = np.frombuffer(
        uexp_data, dtype=np.uint8, count=byte_count, offset=pixel_offset
    ).reshape(LANDSCAPE_SIDE, LANDSCAPE_SIDE, 4)
    if not (np.array_equal(pixels[..., 0], pixels[..., 1]) and
            np.array_equal(pixels[..., 0], pixels[..., 2]) and
            np.all(pixels[..., 3] == 255)):
        raise ValueError("Unexpected snow-height pixel channels")
    return pixel_offset, pixels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template_snow_uexp", type=Path)
    parser.add_argument("target_r16", type=Path)
    parser.add_argument("output_snow_uexp", type=Path)
    args = parser.parse_args()

    template = args.template_snow_uexp.read_bytes()
    pixel_offset, _ = snow_pixels(template)

    target = np.fromfile(args.target_r16, dtype="<u2")
    if target.size != LANDSCAPE_SIDE * LANDSCAPE_SIDE:
        parser.error(f"target R16 has {target.size} samples instead of 2017²")
    target = target.reshape(LANDSCAPE_SIDE, LANDSCAPE_SIDE)
    gray = (target >> 8).astype(np.uint8)

    output = bytearray(template)
    rgba = np.empty((LANDSCAPE_SIDE, LANDSCAPE_SIDE, 4), dtype=np.uint8)
    rgba[..., :3] = gray[..., None]
    rgba[..., 3] = 255
    output[pixel_offset:pixel_offset + rgba.nbytes] = rgba.tobytes()
    args.output_snow_uexp.parent.mkdir(parents=True, exist_ok=True)
    args.output_snow_uexp.write_bytes(output)

    print(
        f"Wrote {args.output_snow_uexp}: gray {int(gray.min())}-{int(gray.max())}, "
        f"{len(output)} bytes")


if __name__ == "__main__":
    main()
