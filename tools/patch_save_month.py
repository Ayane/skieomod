#!/usr/bin/env python3
"""Patch the root GameTime month in a Ski-E-O GVAS save."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


MONTHS = (
    "July", "August", "September", "October", "November", "December",
    "January", "February", "March", "April", "May", "June",
)


def find_fstring(blob: bytes, value: bytes, start: int = 0) -> int:
    needle = value + b"\0"
    position = blob.find(needle, start)
    if position < 4:
        raise ValueError(f"FString {value!r} not found")
    if struct.unpack_from("<I", blob, position - 4)[0] != len(needle):
        raise ValueError(f"invalid FString length before {value!r}")
    return position


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("month", choices=MONTHS)
    args = parser.parse_args()

    blob = bytearray(args.input.read_bytes())
    if not blob.startswith(b"GVAS"):
        raise ValueError(f"{args.input} is not a GVAS archive")

    game_time_name = find_fstring(blob, b"GameTime")
    month_name = find_fstring(blob, b"Month", game_time_name)
    month_phase_name = find_fstring(blob, b"MonthPhase", month_name)
    game_time_size_offset = month_name - 9
    game_time_size = struct.unpack_from("<I", blob, game_time_size_offset)[0]
    game_time_end = month_name - 4 + game_time_size
    if month_phase_name >= game_time_end:
        raise ValueError("MonthPhase falls outside the root GameTime struct")

    enum_prefix = b"EFiscalMonth::"
    enum_position = blob.find(enum_prefix, month_name, month_phase_name)
    if enum_position < 4:
        raise ValueError("serialized GameTime month enum was not found")
    old_length = struct.unpack_from("<I", blob, enum_position - 4)[0]
    old_end = enum_position + old_length
    if old_end > month_phase_name or blob[old_end - 1] != 0:
        raise ValueError("invalid serialized GameTime month enum")
    old_value = bytes(blob[enum_position:old_end - 1])

    new_value = enum_prefix + args.month.encode("ascii")
    new_serialized = new_value + b"\0"
    blob[enum_position:old_end] = new_serialized
    struct.pack_into("<I", blob, enum_position - 4, len(new_serialized))
    delta = len(new_serialized) - old_length
    struct.pack_into(
        "<I", blob, game_time_size_offset, game_time_size + delta)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(blob)
    print(
        f"Patched root GameTime month: {old_value.decode('ascii')} -> "
        f"{new_value.decode('ascii')} ({delta:+d} byte)"
    )


if __name__ == "__main__":
    main()
