#!/usr/bin/env python3
"""Replace the SaveBytes payload of Ski-E-O's cooked InitialSaveAsset.

This intentionally targets the simple legacy asset emitted for
IS_Map_sugar_bowl.  Its export consists of the unversioned-property header,
the uint8 array length, the GVAS bytes and a four-byte export footer.  The
package summary and export map each contain one size that must grow with the
payload.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


GVAS_MAGIC = b"GVAS"


def replace_unique(blob: bytearray, old: bytes, new: bytes, label: str) -> None:
    offsets = []
    start = 0
    while True:
        offset = blob.find(old, start)
        if offset < 0:
            break
        offsets.append(offset)
        start = offset + 1
    if len(offsets) != 1:
        raise ValueError(
            f"expected one {label} field, found {len(offsets)} at {offsets}")
    offset = offsets[0]
    blob[offset : offset + len(old)] = new


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_asset", type=Path)
    parser.add_argument("source_export", type=Path)
    parser.add_argument("save_game", type=Path)
    parser.add_argument("output_asset", type=Path)
    parser.add_argument("output_export", type=Path)
    args = parser.parse_args()

    asset = bytearray(args.source_asset.read_bytes())
    source_export = args.source_export.read_bytes()
    save_game = args.save_game.read_bytes()

    if not save_game.startswith(GVAS_MAGIC):
        raise ValueError(f"{args.save_game} is not a GVAS archive")
    if len(source_export) < 10 or source_export[6:10] != GVAS_MAGIC:
        raise ValueError("source export is not the expected InitialSaveAsset")
    old_save_size = struct.unpack_from("<I", source_export, 2)[0]
    if old_save_size + 10 != len(source_export):
        raise ValueError(
            "unexpected InitialSaveAsset export layout: "
            f"count={old_save_size}, file={len(source_export)}")
    if len(save_game) > 0xFFFFFFFF:
        raise ValueError("SaveGame is too large for the uint8 array")

    new_export = (
        source_export[:2]
        + struct.pack("<I", len(save_game))
        + save_game
        + source_export[-4:]
    )
    old_export_size = len(source_export)
    new_export_size = len(new_export)
    old_package_size = len(asset) + old_export_size
    new_package_size = len(asset) + new_export_size

    replace_unique(
        asset,
        struct.pack("<Q", old_export_size),
        struct.pack("<Q", new_export_size),
        "export serial size",
    )
    replace_unique(
        asset,
        struct.pack("<Q", old_package_size),
        struct.pack("<Q", new_package_size),
        "package size",
    )

    args.output_asset.parent.mkdir(parents=True, exist_ok=True)
    args.output_export.parent.mkdir(parents=True, exist_ok=True)
    args.output_asset.write_bytes(asset)
    args.output_export.write_bytes(new_export)
    print(
        f"Embedded {len(save_game)} GVAS bytes; export "
        f"{old_export_size} -> {new_export_size}, package "
        f"{old_package_size} -> {new_package_size}"
    )


if __name__ == "__main__":
    main()
