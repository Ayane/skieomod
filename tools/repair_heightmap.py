#!/usr/bin/env python3
"""Replace documented bad DEM tiles with authoritative terrain data.

Read the original R16, preserve its encoding and all samples outside each
repair, and blend only the narrow margin around the replacement footprint.
Sources and expected input digest are recorded in the geographic map config.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

import numpy as np
from osgeo import gdal


def replace_region(values, geotransform, source, bounds, blend_meters):
    """Return corrected heights; reject missing data before modifying anything."""
    west, south, east, north = bounds
    if not west < east or not south < north or blend_meters <= 0:
        raise ValueError("Repair bounds and blend distance must be positive")
    left, spacing, _, top, _, row_spacing = geotransform
    if spacing <= 0 or row_spacing != -spacing:
        raise ValueError("Repairs require a square, north-to-south sample grid")
    xs = left + spacing / 2 + np.arange(values.shape[1]) * spacing
    ys = top - spacing / 2 - np.arange(values.shape[0]) * spacing
    columns = np.flatnonzero((xs >= west - blend_meters) & (xs <= east + blend_meters))
    rows = np.flatnonzero((ys >= south - blend_meters) & (ys <= north + blend_meters))
    if not len(columns) or not len(rows):
        raise ValueError("Repair does not intersect the heightmap")
    c0, c1 = int(columns[0]), int(columns[-1]) + 1
    r0, r1 = int(rows[0]), int(rows[-1]) + 1
    # The source is aligned in Lambert-93; force this CRS because the WMS
    # GeoTIFF uses a custom WKT without an EPSG authority code.
    warped = gdal.Warp("", str(source), format="MEM", srcSRS="EPSG:2154",
                       dstSRS="EPSG:2154", outputType=gdal.GDT_Float64,
                       outputBounds=(xs[c0] - spacing / 2, ys[r1 - 1] - spacing / 2,
                                     xs[c1 - 1] + spacing / 2, ys[r0] + spacing / 2),
                       width=c1 - c0, height=r1 - r0, resampleAlg="bilinear",
                       dstNodata=-32767)
    replacement = warped.ReadAsArray()
    distance_x = np.maximum(np.maximum(west - xs[c0:c1], xs[c0:c1] - east), 0)
    distance_y = np.maximum(np.maximum(south - ys[r0:r1], ys[r0:r1] - north), 0)
    fraction = np.clip(1 - np.maximum(distance_x[None, :], distance_y[:, None]) / blend_meters, 0, 1)
    weight = fraction * fraction * (3 - 2 * fraction)
    affected = weight > 0
    valid = np.isfinite(replacement) & (replacement > -1000) & (replacement < 10000)
    if not np.all(valid[affected]):
        raise ValueError("Repair source contains missing or invalid elevations")
    result = values.copy()
    region = result[r0:r1, c0:c1]
    region[affected] += weight[affected] * (replacement[affected] - region[affected])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("maps/veymont/map.json"))
    parser.add_argument("--manifest", type=Path, default=Path("mod/SkiEO-Veymont/custom-map.json"))
    parser.add_argument("--input", type=Path, required=True, help="unmodified original R16")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path("build/terrain/repairs"))
    parser.add_argument("--fetch", action="store_true", help="download missing repair sources")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    source = json.loads(args.manifest.read_text())["terrain"]["source"]
    repairs = config["source"]["repairs"]
    original = args.input.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    if digest != config["source"]["repair_input_sha256"]:
        parser.error("Input is not the original heightmap; repairs must not be applied twice")
    width, height = source["vertices"]
    if len(original) != width * height * 2:
        parser.error("Input dimensions disagree with the manifest")
    scale, offset = source["height_scale_meters"], source["height_offset_meters"]
    values = np.frombuffer(original, dtype="<u2").reshape(height, width).astype(float) * scale + offset
    terrain = config["terrain"]
    west, _, _, north = terrain["bounds_east_north"]
    spacing = terrain["spacing_meters"]
    transform = (west - spacing / 2, spacing, 0, north + spacing / 2, 0, -spacing)
    args.cache.mkdir(parents=True, exist_ok=True)
    gdal.UseExceptions()
    for repair in repairs:
        path = args.cache / repair["file"]
        if not path.exists() and args.fetch:
            temporary = path.with_suffix(".partial.tif")
            print("Downloading", repair["name"], flush=True)
            with urllib.request.urlopen(repair["url"], timeout=120) as response, temporary.open("wb") as out:
                while block := response.read(1024 * 1024):
                    out.write(block)
            temporary.replace(path)
        if not path.exists():
            parser.error(f"Missing {path}; rerun with --fetch")
        if hashlib.sha256(path.read_bytes()).hexdigest() != repair["sha256"]:
            parser.error(f"Repair source changed: {path}; inspect it before updating its recorded digest")
        values = replace_region(values, transform, path, repair["bounds_east_north"], repair["blend_meters"])
    encoded = np.rint((values - offset) / scale)
    if encoded.min() < 0 or encoded.max() > 65535:
        parser.error("Replacement elevations do not fit the existing R16 encoding")
    output = encoded.astype("<u2").tobytes()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".partial.r16")
    temporary.write_bytes(output)
    temporary.replace(args.output)
    print("Corrected heightmap:", args.output)
    print("SHA256:", hashlib.sha256(output).hexdigest())
    print("Changed samples:", np.count_nonzero(np.frombuffer(original, dtype="<u2") != encoded.ravel()))


if __name__ == "__main__":
    main()
