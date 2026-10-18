#!/usr/bin/env python3
"""Build a portable LiDAR heightmap from a configured rectangular extent.

The optional download is a spatial Cloud Optimized GeoTIFF read: it does not
download the complete 77 GB Isere source raster. The resulting R16 file is a
standard Unreal Landscape import source, not Ski-E-O's cooked custom texture.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path

import numpy as np
from osgeo import gdal, osr


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "maps/veymont/map.json"
DEFAULT_OUTPUT = ROOT / "build/terrain"
ISERE_COG = (
    "https://drive.opendata.craig.fr/public.php/webdav/altimetrie/"
    "lidar_hd/38_Isere/LHD_Isere_2021-2022_MNT_50cm_L93.cog.tif"
)


def read_config(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    terrain = data["terrain"]
    vertices = [terrain["vertices_x"], terrain["vertices_y"]]
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 2 for value in vertices):
        raise ValueError("Terrain dimensions must contain integers >= 2")
    spacing = terrain["spacing_meters"]
    if isinstance(spacing, bool) or not isinstance(spacing, (int, float)) or not math.isfinite(spacing) or spacing <= 0:
        raise ValueError("Terrain spacing must be a finite positive number")
    expected_extent = [(value - 1) * spacing for value in vertices]
    extent = terrain["extent_meters"]
    if isinstance(extent, (int, float)):
        extent = [extent, extent]  # Older square configurations remain valid.
    if (not isinstance(extent, (list, tuple)) or len(extent) != 2
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) for value in extent)
            or any(abs(a - b) > 1e-6 for a, b in zip(expected_extent, extent))):
        raise ValueError("Terrain extent and spacing disagree")
    x0, y0, x1, y1 = terrain["bounds_east_north"]
    if any(not math.isfinite(value) for value in (x0, y0, x1, y1)) or any(
            abs(a - b) > 1e-6 for a, b in zip(expected_extent, [x1 - x0, y1 - y0])):
        raise ValueError("Terrain bounds and dimensions disagree")
    return data


def expected_geotransform(config: dict) -> tuple[float, ...]:
    x0, y0, x1, y1 = config["terrain"]["bounds_east_north"]
    spacing = config["terrain"]["spacing_meters"]
    return (x0 - spacing / 2, spacing, 0.0, y1 + spacing / 2, 0.0, -spacing)


def validate_raster(dataset, config: dict) -> None:
    terrain = config["terrain"]
    if dataset.RasterXSize != terrain["vertices_x"] or dataset.RasterYSize != terrain["vertices_y"]:
        raise ValueError(
            f"Expected {terrain['vertices_x']}x{terrain['vertices_y']}, got "
            f"{dataset.RasterXSize}x{dataset.RasterYSize}"
        )
    actual = dataset.GetGeoTransform()
    expected = expected_geotransform(config)
    if any(abs(a - b) > 1e-6 for a, b in zip(actual, expected)):
        raise ValueError(f"Unexpected geotransform: {actual}; expected {expected}")
    spatial = osr.SpatialReference(wkt=dataset.GetProjection())
    if spatial.GetAuthorityCode(None) != "2154":
        raise ValueError("Terrain raster is not Lambert-93 / EPSG:2154")


def fetch_lidar(target: Path, config: dict, refresh: bool) -> None:
    if target.exists() and not refresh:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    terrain = config["terrain"]
    x0, y0, x1, y1 = terrain["bounds_east_north"]
    spacing = terrain["spacing_meters"]
    temporary = target.with_suffix(".partial.tif")

    gdal.UseExceptions()
    gdal.SetConfigOption("GDAL_HTTP_USERPWD", "opendata:")
    gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    gdal.SetConfigOption("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")
    gdal.SetConfigOption("GDAL_HTTP_TIMEOUT", "60")
    gdal.SetConfigOption("GDAL_HTTP_MAX_RETRY", "3")
    gdal.SetConfigOption("GDAL_HTTP_MULTIRANGE", "SERIAL")
    gdal.SetCacheMax(256 * 1024 * 1024)

    previous_decile = [-1]

    def progress(fraction, _message, _data):
        decile = int(fraction * 10)
        if decile > previous_decile[0]:
            print(f"LiDAR crop: {min(decile * 10, 100)}%", flush=True)
            previous_decile[0] = decile
        return 1

    result = gdal.Warp(
        str(temporary),
        "/vsicurl/" + ISERE_COG,
        dstSRS="EPSG:2154",
        outputBounds=(x0 - spacing / 2, y0 - spacing / 2, x1 + spacing / 2, y1 + spacing / 2),
        width=terrain["vertices_x"],
        height=terrain["vertices_y"],
        outputType=gdal.GDT_Float32,
        resampleAlg="bilinear",
        dstNodata=-32767,
        creationOptions=["COMPRESS=DEFLATE", "PREDICTOR=3", "TILED=YES", "BIGTIFF=IF_SAFER"],
        warpOptions=["NUM_THREADS=2"],
        callback=progress,
    )
    if result is None:
        raise RuntimeError("GDAL did not produce the LiDAR crop")
    result = None
    temporary.replace(target)


def read_elevations(path: Path, config: dict) -> np.ndarray:
    dataset = gdal.Open(str(path))
    if dataset is None:
        raise FileNotFoundError(path)
    validate_raster(dataset, config)
    values = dataset.ReadAsArray().astype(np.float64)
    dataset = None
    valid = np.isfinite(values) & (values > -1000) & (values < 10000)
    if not np.all(valid):
        count = int(np.count_nonzero(~valid))
        raise ValueError(f"LiDAR crop contains {count} missing or invalid samples")
    return values


def encode_unreal(values: np.ndarray, spacing: float = 4.0) -> tuple[np.ndarray, dict]:
    low = float(values.min())
    high = float(values.max())
    midpoint = (low + high) / 2
    # UE Landscape covers 512 * ZScale/100 metres across the complete uint16 range.
    required_scale = (high - low) * 1.02 * 100 / 512
    z_scale = max(1.0, math.ceil(required_scale / 5) * 5.0)
    encoded_f = 32768.0 + (values - midpoint) * 12800.0 / z_scale
    if encoded_f.min() < 0 or encoded_f.max() > 65535:
        raise ValueError("Chosen Unreal Z scale cannot represent the terrain")
    encoded = np.rint(encoded_f).astype("<u2")
    decoded = midpoint + (encoded.astype(np.float64) - 32768.0) * z_scale / 12800.0
    metadata = {
        "minimum_meters": low,
        "maximum_meters": high,
        "actor_location_z_centimeters": midpoint * 100,
        "landscape_scale_x_y": spacing * 100.0,
        "landscape_scale_z": z_scale,
        "maximum_quantization_error_meters": float(np.abs(decoded - values).max()),
        "encoding": "uint16 little-endian; Unreal Landscape midpoint is 32768",
    }
    return encoded, metadata


def write_preview(values: np.ndarray, target: Path, spacing: float) -> None:
    from PIL import Image

    dy, dx = np.gradient(values, spacing)
    slope = np.hypot(dx, dy)
    shade = 0.60 - 0.45 * dx + 0.35 * dy
    shade /= np.sqrt(1.0 + slope * slope)
    shade = np.clip((shade - np.percentile(shade, 1)) /
                    (np.percentile(shade, 99) - np.percentile(shade, 1)), 0, 1)
    normalized = np.clip((values - values.min()) / (values.max() - values.min()), 0, 1)
    low = np.array([46, 82, 52], dtype=np.float64)
    high = np.array([226, 232, 232], dtype=np.float64)
    rgb = low + normalized[..., None] * (high - low)
    rgb *= (0.55 + 0.65 * shade[..., None])
    image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    image.thumbnail((1008, 1008), Image.Resampling.LANCZOS)
    image.save(target, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--cache", type=Path, help="cached crop (default: filename derived from map dimensions and spacing)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fetch-lidar", action="store_true", help="fetch the spatial COG crop if absent")
    parser.add_argument("--refresh", action="store_true", help="replace the cached spatial crop")
    args = parser.parse_args()

    config = read_config(args.config)
    if args.cache is None:
        terrain = config['terrain']
        args.cache = DEFAULT_OUTPUT / (
            f"{config['id']}-mnt-{terrain['vertices_x']}x{terrain['vertices_y']}-"
            f"{terrain['spacing_meters']:g}m.tif")
    if args.fetch_lidar or args.refresh:
        fetch_lidar(args.cache, config, args.refresh)
    if not args.cache.exists():
        parser.error(f"missing {args.cache}; rerun with --fetch-lidar")

    values = read_elevations(args.cache, config)
    encoded, encoding = encode_unreal(values, config["terrain"]["spacing_meters"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    width, height = config["terrain"]["vertices_x"], config["terrain"]["vertices_y"]
    stem = f"{config['id']}-{width}x{height}"
    r16_path = args.output_dir / f"{stem}.r16"
    temporary = r16_path.with_suffix(".tmp")
    encoded.tofile(temporary)
    temporary.replace(r16_path)

    raw_sidecar = {"width": width, "height": height, "bbp": 16}
    (args.output_dir / f"{stem}.json").write_text(json.dumps(raw_sidecar, indent=2) + "\n")
    metadata = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "map": config["id"],
        "projection": config["projection"],
        "bounds_east_north": config["terrain"]["bounds_east_north"],
        "vertices": [width, height],
        "spacing_meters": config["terrain"]["spacing_meters"],
        "row_order": "north to south",
        "source": config["source"],
        **encoding,
    }
    (args.output_dir / f"{stem}.metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    write_preview(values, args.output_dir / f"{stem}-preview.png", config["terrain"]["spacing_meters"])
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
