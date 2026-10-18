#!/usr/bin/env python3
"""Convert an authoring image to a bounded portable terrain texture and mips."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def build(source: Path, output: Path, size: int = 512) -> list[Path]:
    if size < 1 or size > 512 or size & (size - 1):
        raise ValueError("size must be a power of two within 1..512")
    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as original:
        if original.width != original.height:
            raise ValueError("terrain textures must be square")
        image = original.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    paths = [output]
    image.save(output)
    level = 1
    while image.width > 1:
        side = image.width // 2
        image = image.resize((side, side), Image.Resampling.BOX)
        path = output.with_name(f"{output.stem}-mip{level:02d}.png")
        image.save(path)
        paths.append(path)
        level += 1
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--size", type=int, default=512)
    args = parser.parse_args()
    for path in build(args.source, args.output, args.size):
        print(path)
