#!/usr/bin/env python3
"""Prepare a bounded, portable dense rock mesh for the Unreal Nanite cooker.

Subdivision samples an existing surface; it is not a new terrain measurement.
The small procedural relief represents a limestone style, not measured cracks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.ndimage import map_coordinates, distance_transform_edt


def normals(points: np.ndarray) -> np.ndarray:
    rows, columns = np.gradient(points, axis=(0, 1))
    result = np.cross(columns, -rows)
    return result / np.maximum(np.linalg.norm(result, axis=-1, keepdims=True), 1e-12)


def limestone_detail(uv_meters: np.ndarray, seed: int, spacing: float) -> np.ndarray:
    """Smooth coherent relief, with subtle horizontal beds and sparse joints."""
    rng = np.random.default_rng(seed)
    u, v = uv_meters[..., 0], uv_meters[..., 1]
    value = np.zeros_like(u)
    # Continuous world coordinates, rather than independent random vertex noise.
    for wavelength, weight in ((1.4, 1.0), (.55, .35), (.22, .10)):
        if wavelength < 4*spacing:
            continue  # Do not alias sub-grid detail into diagonal stripes.
        for _ in range(4):
            angle, phase = rng.uniform(0, 2*math.pi, 2)
            value += weight/4*np.sin(2*math.pi/wavelength *
                                    (math.cos(angle)*u+math.sin(angle)*v)+phase)
    beds = v + .15*np.sin(u/9) + .06*np.sin(u/2.3)
    bed_width = max(.075, 2*spacing*math.pi/4.5)
    value -= .20*np.exp(-((np.sin(math.pi*beds/4.5))/bed_width)**2)
    # White compact limestone: discontinuous, restrained joints, no tiled brick pattern.
    joints = np.sin(math.pi*(u+.30*np.sin(v/11))/17)
    joint_width = max(.025, 2*spacing*math.pi/17)
    value -= .25*np.exp(-(joints/joint_width)**2)*(.5+.5*np.sin(v/8))**2
    return value


def prepare(source: Path, output: Path, spacing: float = .25, amplitude: float = .025,
            seed: int = 17, corrected: bool = False, max_vertices: int = 1_000_000,
            package: str = '/Game/CustomMaps/Veymont/Nanite/SM_GrandVeymontProof') -> dict:
    if not math.isfinite(spacing) or not .05 <= spacing <= 4:
        raise ValueError('spacing must be between 0.05 and 4 metres')
    if not math.isfinite(amplitude) or not 0 <= amplitude <= .10:
        raise ValueError('procedural amplitude must be between 0 and 0.10 metres')
    if type(seed) is not int or seed < 0:
        raise ValueError('seed must be a nonnegative integer')
    if not package.startswith('/Game/') or not all(
            part and part.replace('_', '').isalnum() for part in package[6:].split('/')):
        raise ValueError('package must be an Unreal /Game/ package with simple names')
    if output.resolve() == source.resolve() or source.resolve() in output.resolve().parents:
        raise ValueError('output must be outside the source extraction directory')
    report = json.loads((source/'surface.json').read_text())
    with np.load(source/'surface-data.npz', allow_pickle=False) as data:
        original = data['corrected_meters' if corrected else 'base_meters'].copy()
        mask = data['geometry_mask'].astype(bool)
    if (original.ndim != 3 or original.shape[-1] != 3 or original.shape[:2] != mask.shape
            or min(mask.shape) < 2 or not mask.any()):
        raise ValueError('invalid source mesh dimensions')
    if not np.isfinite(original).all():
        raise ValueError('non-finite source mesh')
    source_spacing = np.asarray(report['spacing_meters'], dtype=float)
    if source_spacing.shape != (2,) or not np.isfinite(source_spacing).all() or (source_spacing <= 0).any():
        raise ValueError('invalid source spacing')
    h, w = mask.shape
    width = math.ceil((w-1)*source_spacing[0]/spacing)+1
    height = math.ceil((h-1)*source_spacing[1]/spacing)+1
    if type(max_vertices) is not int or max_vertices < 4 or width*height > max_vertices:
        raise ValueError(f'vertex budget exceeded: {width*height} > {max_vertices}')
    rows, columns = np.meshgrid(np.linspace(0, h-1, height), np.linspace(0, w-1, width), indexing='ij')
    coordinates = [rows, columns]
    dense = np.stack([map_coordinates(original[..., axis], coordinates, order=1, mode='nearest')
                      for axis in range(3)], axis=-1)
    # Keep only cells whose entire source footprint is usable; never bridge mask holes.
    usable = map_coordinates(mask.astype(float), coordinates, order=1, mode='nearest') >= 1-1e-8
    metric_spacing = [(w-1)*source_spacing[0]/(width-1), (h-1)*source_spacing[1]/(height-1)]
    padded = np.pad(usable, 1)
    edge_distance = distance_transform_edt(padded, sampling=metric_spacing[::-1])[1:-1, 1:-1]
    fade = np.clip((edge_distance-max(metric_spacing))/2, 0, 1)
    base_normals = normals(dense)
    basis = np.asarray(report['basis_columns'], dtype=float)
    if (basis.shape != (3, 3) or not np.isfinite(basis).all()
            or not np.allclose(basis.T@basis, np.eye(3), atol=1e-6)
            or np.linalg.det(basis) < .999):
        raise ValueError('invalid source basis')
    front = basis[:, 2]
    if np.min(np.sum(base_normals[usable]*front, axis=-1)) < 0:
        raise ValueError('source mesh orientation is inconsistent')
    uv_meters = np.stack([columns*source_spacing[0], (h-1-rows)*source_spacing[1]], axis=-1)
    relief = limestone_detail(uv_meters, seed, max(metric_spacing))
    relief *= amplitude/max(float(np.max(np.abs(relief))), 1e-12)
    relief *= fade
    detailed = dense+base_normals*relief[..., None]
    final_normals = normals(detailed)
    angle = np.degrees(np.arccos(np.clip(np.sum(final_normals*base_normals, axis=-1), -1, 1)))
    # Guard steep subpixel relief using actual final geometry, rather than shading normals.
    for _ in range(24):
        if float(angle[usable].max()) <= 20:
            break
        relief *= .75
        detailed = dense+base_normals*relief[..., None]
        final_normals = normals(detailed)
        angle = np.degrees(np.arccos(np.clip(np.sum(final_normals*base_normals, axis=-1), -1, 1)))
    else:
        raise ValueError('unable to satisfy the geometric normal limit')
    cell = usable[:-1, :-1] & usable[1:, :-1] & usable[:-1, 1:] & usable[1:, 1:]
    start = np.arange(width*height, dtype=np.uint32).reshape(height, width)[:-1, :-1][cell]
    if not start.size:
        raise ValueError('no complete source cells remain')
    triangles = np.stack([start, start+width, start+1, start+1, start+width, start+width+1], axis=-1).reshape(-1, 3)
    # Source OBJ is counterclockwise. Unreal winding is reversed by the cooker.
    origin = (detailed[usable].min(axis=0)+detailed[usable].max(axis=0))/2
    output.mkdir(parents=True, exist_ok=True)
    buffers = {
        'positions': (detailed-origin).reshape(-1, 3).astype('<f4'),
        'normals': final_normals.reshape(-1, 3).astype('<f4'),
        'uvs': (uv_meters.reshape(-1, 2)/20).astype('<f4'),
        'indices': triangles.astype('<u4'),
    }
    files = {}
    for name, values in buffers.items():
        path = output/(name+'.bin')
        values.tofile(path)
        files[name] = {'file': path.name, 'bytes': path.stat().st_size,
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    info = {'version': 1, 'package': package, 'coordinate_system': 'east-south-up-metres',
        'winding': 'counterclockwise', 'origin_meters': origin.tolist(),
        'vertices': width*height, 'triangles': len(triangles), 'grid_size': [width, height],
        'spacing_meters': metric_spacing, 'buffers': files,
        'source_npz_sha256': hashlib.sha256((source/'surface-data.npz').read_bytes()).hexdigest(),
        'photographic_correction_applied': corrected, 'source_calibration': report.get('calibration'),
        'procedural': {'profile': 'compact-white-limestone', 'seed': seed,
                       'maximum_displacement_meters': float(np.abs(relief).max()),
                       'maximum_normal_change_degrees': float(angle[usable].max()),
                       'measured_fractures': False},
        'material': report['material'], 'nanite_built': False}
    (output/'mesh.json').write_text(json.dumps(info, indent=2)+'\n')
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='extract_rock_surface output directory')
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--spacing', type=float, default=.25)
    parser.add_argument('--amplitude', type=float, default=.025)
    parser.add_argument('--seed', type=int, default=17)
    parser.add_argument('--corrected', action='store_true', help='include the candidate photographic correction')
    parser.add_argument('--max-vertices', type=int, default=1_000_000)
    parser.add_argument('--package', default='/Game/CustomMaps/Veymont/Nanite/SM_GrandVeymontProof')
    args = parser.parse_args()
    try:
        result = prepare(args.source, args.output_dir, args.spacing, args.amplitude,
                         args.seed, args.corrected, args.max_vertices, args.package)
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps({key: result[key] for key in ('vertices', 'triangles', 'spacing_meters', 'procedural')}, indent=2))


if __name__ == '__main__':
    main()
