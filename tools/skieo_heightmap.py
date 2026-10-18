#!/usr/bin/env python3
"""Prepare raw R16LE/R16BE and PNG16 sources while building a portable map."""
from __future__ import annotations

import copy
from contextlib import contextmanager
from array import array
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import zlib
from types import SimpleNamespace

if __package__ == 'tools':
    from . import skieo_bake as bake
else:
    import skieo_bake as bake


def decode_png(data, width, height):
    """Decode bounded, non-interlaced grayscale PNG16 without losing precision."""
    cursor, compressed = 8, bytearray()
    seen_header = seen_end = False
    while cursor < len(data):
        if cursor + 12 > len(data):
            raise ValueError("Truncated PNG chunk.")
        size = struct.unpack_from(">I", data, cursor)[0]
        tag = data[cursor + 4:cursor + 8]
        end = cursor + 12 + size
        if end > len(data):
            raise ValueError("Truncated PNG chunk.")
        payload = data[cursor + 8:cursor + 8 + size]
        if zlib.crc32(tag + payload) & 0xffffffff != struct.unpack_from(">I", data, cursor + 8 + size)[0]:
            raise ValueError("PNG checksum mismatch.")
        if not seen_header and tag != b"IHDR":
            raise ValueError("PNG must start with IHDR.")
        if tag == b"IHDR":
            if seen_header or size != 13 or payload != struct.pack(">IIBBBBB", width, height, 16, 0, 0, 0, 0):
                raise ValueError("Use a non-interlaced 16-bit grayscale PNG (no alpha).")
            seen_header = True
        elif tag == b"IDAT":
            compressed.extend(payload)
        elif tag == b"IEND":
            if size != 0 or end != len(data):
                raise ValueError("Invalid PNG end chunk.")
            seen_end = True
            break
        elif tag[0] & 32 == 0:
            raise ValueError("Unsupported critical PNG chunk.")
        cursor = end
    if not seen_header or not seen_end or not compressed:
        raise ValueError("Incomplete PNG.")
    expected = height * (width * 2 + 1)
    decoder = zlib.decompressobj()
    try:
        decoded = decoder.decompress(compressed, expected + 1)
    except zlib.error as error:
        raise ValueError("Invalid PNG compression.") from error
    if len(decoded) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("PNG decompressed size does not match its dimensions.")
    stride, previous, samples = width * 2, bytearray(width * 2), array("H")
    for y in range(height):
        start = y * (stride + 1)
        filtering = decoded[start]
        if filtering not in range(5):
            raise ValueError("Invalid PNG filter.")
        row = bytearray(decoded[start + 1:start + 1 + stride])
        if filtering:
            for x in range(stride):
                left = row[x - 2] if x >= 2 else 0
                above = previous[x]
                corner = previous[x - 2] if x >= 2 else 0
                if filtering == 1:
                    predictor = left
                elif filtering == 2:
                    predictor = above
                elif filtering == 3:
                    predictor = (left + above) // 2
                else:
                    p = left + above - corner
                    distances = (abs(p - left), abs(p - above), abs(p - corner))
                    predictor = (left, above, corner)[distances.index(min(distances))]
                row[x] = (row[x] + predictor) & 255
        samples.frombytes(row)
        previous = row
    # PNG samples are always big-endian, regardless of the host's byte order.
    if sys.byteorder == "little":
        samples.byteswap()
    return samples


def read_samples(args, *, assumptions=None):
    source = args.heightmap.resolve(strict=True)
    if source.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("Choose a source file of at most 64 MiB for heightmap builds.")
    input_data = source.read_bytes()
    if source.suffix.lower() == ".png":
        if args.big_endian:
            raise ValueError("r16be applies to raw R16, not PNG.")
        header = input_data[:33]
        if (len(header) != 33 or header[:8] != b"\x89PNG\r\n\x1a\n"
                or header[12:16] != b"IHDR" or header[24:26] != bytes([16, 0])):
            raise ValueError("Use a true 16-bit grayscale PNG without an alpha channel.")
        width, height = struct.unpack(">II", header[16:24])
        check_dimensions(width, height)
        if ((args.width is not None and args.width != width)
                or (args.height is not None and args.height != height)):
            raise ValueError("The supplied dimensions do not match the PNG.")
        samples = decode_png(input_data, width, height)
    else:
        width, height = args.width, args.height
        if len(input_data) % 2:
            raise ValueError("Raw R16 must contain an even number of bytes: two bytes per sample, with no header.")
        count = len(input_data) // 2
        for value in (width, height):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 2 <= value <= 16384):
                raise ValueError("Raw dimensions must be integer sample counts from 2 to 16384.")
        if width is None and height is None:
            side = math.isqrt(count)
            if side * side != count:
                raise ValueError("Raw R16 sample count is not a square. Supply build.heightmap.vertices: [width, height], or [width, null] / [null, height] to derive the other side.")
            width = height = side
            if assumptions is not None:
                assumptions.append(f"Raw R16 dimensions assumed square: {side} x {side} samples from file size. Set vertices explicitly for rectangular terrain.")
        elif width is None or height is None:
            known = width if width is not None else height
            if count % known:
                raise ValueError("Raw R16 sample count is not divisible by the supplied dimension. Check build.heightmap.vertices.")
            width, height = (width, count // width) if width is not None else (count // height, height)
        check_dimensions(width, height)
        expected = width * height * 2
        if len(input_data) != expected:
            raise ValueError(f"Raw file has {len(input_data):,} bytes; expected {expected:,} = {width} x {height} x 2. It must have no header.")
        samples = array("H")
        samples.frombytes(input_data)
        if (sys.byteorder == "little") == args.big_endian:
            samples.byteswap()
    return width, height, samples, input_data


def check_dimensions(width, height):
    if min(width, height) < 2 or max(width, height) > 16384 or width * height > 16 * 1024 * 1024:
        raise ValueError("Use at least 2 samples per axis, at most 16384 per axis and at most 32 MiB of raw samples.")


def prepare_map(project, manifest, *, report=None):
    """Calculate a portable terrain from build.heightmap without changing sources."""
    build = manifest.get("build", {})
    if not isinstance(build, dict):
        raise ValueError("build must be an object.")
    settings = build.get("heightmap")
    if settings is None:
        if 'vegetation' in build:
            raise ValueError('build.vegetation requires build.heightmap: vegetation is baked from the source terrain.')
        return manifest, None
    if manifest.get("format", {}).get("name") != "skieo-map":
        raise ValueError("build.heightmap only applies to map projects.")
    if not isinstance(settings, dict):
        raise ValueError("build.heightmap must be an object.")
    bake.object_settings(settings, 'build.heightmap', ('file', 'format', 'vertices', 'spacing_meters',
        'elevation_meters', 'height_scale_meters', 'height_offset_meters', 'row_order', 'sample_step', 'processing'))
    if __package__ == "tools":
        from .custom_maps import validate_manifest, safe_relative_path
    else:
        from custom_maps import validate_manifest, safe_relative_path
    file = safe_relative_path(settings["file"], "build.heightmap.file")
    input_path = (project / file).resolve(strict=True)
    if not input_path.is_relative_to(project):
        raise ValueError("The build heightmap must stay inside the project.")
    if file == Path("Terrain/heightmap.r16"):
        raise ValueError("Keep the original heightmap under a different name, such as Terrain/source.r16; Terrain/heightmap.r16 is generated by the build.")
    source_format = settings.get("format", "png16" if input_path.suffix.lower() == ".png" else "r16le")
    if source_format not in {"png16", "r16le", "r16be"} or (source_format == "png16") != (input_path.suffix.lower() == ".png"):
        raise ValueError("Use png16 for .png, or r16le/r16be for headerless raw input.")
    vertices = settings.get("vertices", [None, None])
    if not isinstance(vertices, list) or len(vertices) != 2:
        raise ValueError("build.heightmap.vertices must contain width and height samples.")
    if any(value is not None and (isinstance(value, bool) or not isinstance(value, int)) for value in vertices):
        raise ValueError("Raw dimensions must be integer sample counts.")
    endpoints = settings.get("elevation_meters", [None, None])
    if not isinstance(endpoints, list) or len(endpoints) != 2:
        raise ValueError("build.heightmap.elevation_meters must contain the actual minimum and maximum elevations.")
    if 'elevation_meters' in settings and any(value is None for value in endpoints):
        raise ValueError("Supply two numeric elevation_meters endpoints, or omit the field for relative test elevations.")
    if any(key in settings and settings[key] is None for key in ('height_scale_meters', 'height_offset_meters')):
        raise ValueError("Exporter scale and offset must be numeric when supplied.")
    for value in [*endpoints, settings.get("height_scale_meters"), settings.get("height_offset_meters")]:
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
            raise ValueError("Heightmap elevation values must be finite numbers.")
    options = SimpleNamespace(heightmap=input_path, width=vertices[0], height=vertices[1],
        spacing=settings.get("spacing_meters"), min_elevation=endpoints[0], max_elevation=endpoints[1],
        height_scale=settings.get("height_scale_meters"), height_offset=settings.get("height_offset_meters"),
        big_endian=source_format == "r16be", row_order=settings.get("row_order", "north_to_south"))
    if options.row_order not in {"north_to_south", "south_to_north"}:
        raise ValueError("Invalid heightmap row order.")
    if (isinstance(options.spacing, bool) or not isinstance(options.spacing, (int, float))
            or not math.isfinite(options.spacing) or options.spacing <= 0):
        raise ValueError("Heightmap spacing must be finite and positive.")
    assumptions = []
    width, height, samples, _ = read_samples(options, assumptions=assumptions)
    raw_min, raw_max = min(samples), max(samples)
    endpoints = (options.min_elevation, options.max_elevation)
    elevation_mode = 'actual_range'
    if all(value is None for value in (*endpoints, options.height_scale, options.height_offset)):
        # Pixel values have no absolute altitude or vertical-unit metadata.
        # This explicit relative range lets creators test their own relief.
        options.min_elevation, options.max_elevation = 0, 1000
        endpoints = (options.min_elevation, options.max_elevation)
        elevation_mode = 'relative_range'
        assumptions.append("No elevation encoding supplied: using a relative 0 to 1000 m relief for testing. Real altitudes are unknown; set elevation_meters or the exporter's scale and offset for accurate terrain.")
    if any(value is not None for value in endpoints):
        if any(value is None for value in endpoints) or options.height_scale is not None or options.height_offset is not None:
            raise ValueError("Specify elevation_meters OR height_scale_meters and height_offset_meters in build.heightmap.")
        if options.max_elevation <= options.min_elevation:
            raise ValueError("The maximum elevation must exceed the minimum.")
        scale = (options.max_elevation - options.min_elevation) / max(1, raw_max - raw_min)
        offset = options.min_elevation - raw_min * scale
    else:
        if options.height_scale is None or options.height_offset is None:
            raise ValueError("Supply both height_scale_meters and height_offset_meters, or elevation_meters; omit all three to use relative test elevations.")
        scale, offset = options.height_scale, options.height_offset
        elevation_mode = 'exporter_encoding'
    low, high = offset + raw_min * scale, offset + raw_max * scale
    if raw_min == raw_max:
        # Flat sculpted terrain is valid. Keep its exact sample heights while
        # reserving a positive encoding envelope for native Landscape metadata.
        high = low + max(scale, 1)
    size = [(width - 1) * options.spacing, (height - 1) * options.spacing]
    if not all(math.isfinite(value) for value in [scale, offset, low, high, *size]) or scale <= 0 or low >= high:
        raise ValueError("The decoded size and elevation must be finite, with a positive height range.")
    if 'processing' in settings:
        values = array('d', (sample * scale + offset for sample in samples))
        if options.row_order == 'south_to_north':
            values = array('d', (v for y in range(height - 1, -1, -1) for v in values[y * width:(y + 1) * width]))
        processed, statistics = bake.terrain_processing(values, width, height, options.spacing, settings['processing'])
        if report is not None:
            report['processing'] = statistics
        if statistics['measured_max_delta_meters'] > 0:
            low, high = min(processed), max(processed)
            if not all(math.isfinite(v) for v in (low, high)) or high < low:
                raise ValueError('Terrain processing produced an invalid height range.')
            if high == low: high = low + 1
            scale, offset = (high - low) / 65535, low
            if options.row_order == 'south_to_north':
                processed = array('d', (v for y in range(height - 1, -1, -1) for v in processed[y * width:(y + 1) * width]))
            samples = array('H', (round((value - offset) / scale) for value in processed))
            raw_min, raw_max = min(samples), max(samples)
    rows = []
    for row in range(17):
        y = round(row * (height - 1) / 16)
        if options.row_order == "south_to_north":
            y = height - 1 - y
        rows.append([round((samples[y * width + round(column * (width - 1) / 16)] - raw_min)
                           / max(1, raw_max - raw_min), 5) for column in range(17)])
    portable = copy.deepcopy(manifest)
    portable.pop("build", None)
    terrain = portable["terrain"]
    terrain.update(size_meters=size, elevation_meters=[low, high],
                   origin_centimeters=[-size[0] * 50, -size[1] * 50, 0])
    terrain["source"] = {"file": "Terrain/heightmap.r16", "format": "r16le",
                         "vertices": [width, height], "spacing_meters": options.spacing,
                         "row_order": options.row_order, "height_scale_meters": scale,
                         "height_offset_meters": offset}
    terrain["preview"] = {"samples": rows}
    if report is not None:
        report['heightmap'] = {'vertices': [width, height], 'elevation_mode': elevation_mode,
                              'assumptions': assumptions}
    runtime = terrain.setdefault("runtime", {})
    runtime["sample_step"] = settings.get("sample_step", max(1, math.ceil(math.sqrt((width - 1) * (height - 1) / (512 * 512)))))
    runtime.setdefault("tile_quads", 32)
    validate_manifest(portable)
    if sys.byteorder != "little":
        samples.byteswap()
    return portable, samples.tobytes()


@contextmanager
def save_generated(project, manifest_path, working, terrain_bytes, generated=None, *, save_manifest=False):
    """Commit all generated files and metadata after validation; roll back together."""
    if terrain_bytes is None and not generated and not save_manifest:
        yield
        return
    manifest_data = (json.dumps(working, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    files = {**({'Terrain/heightmap.r16': terrain_bytes} if terrain_bytes is not None else {}),
             **(generated or {}), manifest_path.name: manifest_data}
    changed = {}
    for relative, data in files.items():
        target = project / relative
        if target.is_symlink() or not target.resolve().is_relative_to(project):
            raise ValueError('Generated files must stay inside the project and must not be symlinks.')
        if not target.is_file() or target.read_bytes() != data:
            changed[relative] = data
    if not changed:
        yield
        return
    backup_root = project / ".heightmap-backups"
    if backup_root.is_symlink():
        raise ValueError("The backup directory must not be a symlink.")
    backup = backup_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup.mkdir(parents=True)
    originals = {}
    for relative in changed:
        target = project / relative
        originals[relative] = target.read_bytes() if target.exists() else None
        if originals[relative] is not None:
            saved = backup / ('heightmap.r16' if relative == 'Terrain/heightmap.r16' else relative)
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(originals[relative])
    with tempfile.TemporaryDirectory(prefix=".heightmap-build-", dir=project) as temporary:
        stage = Path(temporary)
        for relative, data in changed.items():
            staged = stage / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(data)
        try:
            for relative in changed:
                target = project / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                (stage / relative).replace(target)
            yield
        except BaseException:
            for relative, data in originals.items():
                target = project / relative
                if data is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(data)
            raise
    print(f"Calculated terrain and generated files updated; previous files in {backup.relative_to(project)}")
