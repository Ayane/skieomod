#!/usr/bin/env python3
"""Densify an exact runtime terrain section as a derived Nanite mesh.

Shared edges are subdivided together; tile borders stay on the source geometry.
This permits hiding a visible PMC section while retaining its collision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.ndimage import map_coordinates

from tools.prepare_nanite_rock import limestone_detail


def subdivide(points, normals, uvs, faces):
    edges = np.stack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=1)
    unique, inverse = np.unique(np.sort(edges.reshape(-1, 2), axis=1), axis=0, return_inverse=True)
    midpoint = inverse.reshape(-1, 3)+len(points)
    a, b, c = faces.T
    ab, bc, ca = midpoint.T
    children = np.stack([np.stack([a, ab, ca], axis=-1), np.stack([ab, b, bc], axis=-1),
                         np.stack([ca, bc, c], axis=-1), np.stack([ab, bc, ca], axis=-1)], axis=1).reshape(-1, 3)
    return (np.concatenate([value, value[unique].mean(axis=1)]) for value in (points, normals, uvs)), children


def mesh_normals(points, faces, fallback, weld=None):
    # Runtime UV projections duplicate cliff vertices. Accumulate by geometric
    # position so a UV seam never opens when the surface is displaced.
    if weld is None:
        _, weld = np.unique(points, axis=0, return_inverse=True)
    face_normals = np.cross(points[faces[:, 1]]-points[faces[:, 0]], points[faces[:, 2]]-points[faces[:, 0]])
    result = np.zeros((int(weld.max())+1, 3))
    for corner in range(3):
        np.add.at(result, weld[faces[:, corner]], face_normals)
    result = result[weld]
    lengths = np.linalg.norm(result, axis=-1)
    result[lengths < 1e-10] = fallback[lengths < 1e-10]
    return result/np.maximum(np.linalg.norm(result, axis=-1, keepdims=True), 1e-12)


def refine_walls(points, normals, uvs, faces, spacing, rock_weights=None):
    """Conforming splits measured along the wall, rather than in DEM XY.

    A four-metre heightfield cell can span tens of metres vertically. Refine
    its long rock edges and their neighbours; ordinary ground stays coarse.
    Geometrically duplicate UV edges share the split decision.
    """
    if rock_weights is not None:
        rock_weights=np.asarray(rock_weights,dtype=float).copy()
        if rock_weights.shape!=(len(points),) or not np.isfinite(rock_weights).all() or (rock_weights<0).any():
            raise ValueError('invalid wall refinement weights')
    templates = {0: [(0, 1, 2)], 1: [(0, 3, 2), (3, 1, 2)],
        2: [(0, 1, 4), (0, 4, 2)], 4: [(0, 1, 5), (5, 1, 2)],
        3: [(3, 1, 4), (0, 3, 2), (3, 4, 2)],
        5: [(0, 3, 5), (3, 1, 2), (3, 2, 5)],
        6: [(2, 5, 4), (0, 1, 5), (1, 4, 5)],
        7: [(0, 3, 5), (3, 1, 4), (5, 4, 2), (3, 4, 5)]}
    for _ in range(32):
        _, weld = np.unique(points, axis=0, return_inverse=True)
        edges, inverse = np.unique(np.sort(np.stack([faces[:, [0, 1]], faces[:, [1, 2]],
            faces[:, [2, 0]]], axis=1).reshape(-1, 2), axis=1), axis=0, return_inverse=True)
        _, geometry = np.unique(np.sort(weld[edges], axis=1), axis=0, return_inverse=True)
        long = np.linalg.norm(points[edges[:, 1]]-points[edges[:, 0]], axis=-1) > spacing*(1+1e-8)
        rock = (np.min(normals[edges, 2], axis=1) < .65 if rock_weights is None
                else np.max(rock_weights[edges],axis=1)>1e-4)
        geometric_split = np.zeros(int(geometry.max())+1, dtype=bool)
        np.logical_or.at(geometric_split, geometry, long & rock)
        split = geometric_split[geometry]
        if not split.any(): return points, normals, uvs, faces
        flags = split[inverse].reshape(-1, 3)
        masks = flags@np.array([1, 2, 4])
        new_faces = int(sum(np.count_nonzero(masks == mask)*len(pattern) for mask, pattern in templates.items()))
        if new_faces > 2_000_000 or len(points)+int(split.sum()) > 1_000_000:
            raise ValueError('adaptive wall budget exceeded; increase edge spacing')
        midpoint = np.full(len(edges), -1, dtype=np.int64)
        midpoint[split] = np.arange(int(split.sum()))+len(points)
        vertices = np.column_stack([faces, midpoint[inverse].reshape(-1, 3)])
        children = []
        for mask, pattern in templates.items():
            selected = vertices[masks == mask]
            if len(selected):
                children.append(selected[:, np.asarray(pattern)].reshape(-1, 3))
        faces = np.concatenate(children).astype(np.uint32)
        points, normals, uvs = [np.concatenate([value, value[edges[split]].mean(axis=1)])
                                for value in (points, normals, uvs)]
        if rock_weights is not None:
            rock_weights=np.concatenate([rock_weights,rock_weights[edges[split]].mean(axis=1)])
    raise ValueError('adaptive wall refinement did not converge')


def surface_detail(world: np.ndarray, surface: Path) -> tuple[np.ndarray, dict]:
    """Periodic style inferred from a photo, never its baked lighting/color."""
    report = json.loads((surface/'surface.json').read_text())
    if report.get('procedural', {}).get('periodic') is not True:
        raise ValueError('surface profile must be periodic')
    with np.load(surface/'surface-data.npz', allow_pickle=False) as data:
        displacement = data['procedural_displacement_meters'].copy()
    basis = np.asarray(report['basis_columns'], dtype=float)
    spacing = np.asarray(report['spacing_meters'], dtype=float)
    if (displacement.ndim != 2 or min(displacement.shape) < 2
            or not np.isfinite(displacement).all() or np.abs(displacement).max() > .5
            or basis.shape != (3, 3) or not np.isfinite(basis).all()
            or not np.allclose(basis.T@basis, np.eye(3), atol=1e-6)
            or spacing.shape != (2,) or not np.isfinite(spacing).all() or (spacing <= 0).any()):
        raise ValueError('invalid bounded surface profile')
    uv = world@basis[:, :2]
    # The FFT profile repeats without a seam. Using global metres also keeps
    # phase identical between adjacent terrain tiles and duplicated UV vertices.
    sampled = map_coordinates(displacement, [-uv[:, 1]/spacing[1], uv[:, 0]/spacing[0]],
                              order=1, mode='grid-wrap')
    return sampled, {'method': report['procedural']['method'],
        'source_npz_sha256': hashlib.sha256((surface/'surface-data.npz').read_bytes()).hexdigest(),
        'maximum_displacement_meters': float(np.abs(displacement).max()),
        'photographic_registration_verified': False, 'measured_fractures': False}


def prepare(source: Path, output: Path, levels: int = 2, amplitude: float = .025,
            surface: Path | None = None, edge_spacing: float | None = None) -> dict:
    if type(levels) is not int or not 0 <= levels <= 3 or not np.isfinite(amplitude) or not 0 <= amplitude <= .1:
        raise ValueError('invalid subdivision level or limestone amplitude')
    if edge_spacing is not None and (not np.isfinite(edge_spacing) or not .5 <= edge_spacing <= 8):
        raise ValueError('wall edge spacing must be between 0.5 and 8 metres')
    info = json.loads((source/'tile-source.json').read_text())
    if (info.get('version') != 1 or info.get('coordinate_system') != 'east-south-up-metres'
            or info.get('winding') != 'counterclockwise'):
        raise ValueError('unsupported source section coordinates')
    points = np.loadtxt(source/'positions.txt').reshape(-1, 3)
    normal_prior = np.loadtxt(source/'normals.txt').reshape(-1, 3)
    uvs = np.loadtxt(source/'uvs.txt').reshape(-1, 2)
    faces = np.loadtxt(source/'indices.txt', dtype=np.uint32).reshape(-1, 3)
    if (len(points) < 3 or not len(faces)
            or len(points) != info['vertices'] or len(faces) != info['triangles']
            or len(normal_prior) != len(points) or len(uvs) != len(points)
            or not np.isfinite(points).all() or not np.isfinite(normal_prior).all()
            or not np.isfinite(uvs).all() or faces.max() >= len(points)):
        raise ValueError('invalid source section buffers')
    if len(faces)*4**levels > 2_000_000:
        raise ValueError('triangle budget exceeded before subdivision')
    bounds = [points[:, :2].min(axis=0), points[:, :2].max(axis=0)]
    for _ in range(levels):
        data, faces = subdivide(points, normal_prior, uvs, faces)
        points, normal_prior, uvs = data
        if len(points) > 1_000_000:
            raise ValueError('vertex budget exceeded')
    if edge_spacing is not None:
        points, normal_prior, uvs, faces = refine_walls(points, normal_prior, uvs, faces, edge_spacing)
    _, weld = np.unique(points, axis=0, return_inverse=True)
    prior = mesh_normals(points, faces, normal_prior, weld)
    # World coordinates keep the geological phase consistent across sections.
    world = points+info['origin_meters']
    minimum_edge = float(np.min(np.linalg.norm(points[faces[:, 0]]-points[faces[:, 1]], axis=-1)))
    detail = limestone_detail(world[:, [1, 2]], 17, max(.25, minimum_edge))
    # Only rock walls; ordinary ground and the shared tile edges stay unchanged.
    slope_weight = np.clip((.65-prior[:, 2])/.30, 0, 1)
    distance = np.minimum(points[:, :2]-bounds[0], bounds[1]-points[:, :2]).min(axis=-1)
    fade = np.clip(distance/8, 0, 1)
    relief = detail*amplitude/max(float(np.abs(detail).max()), 1e-12)
    photo_profile = None
    if surface is not None:
        photo_detail, photo_profile = surface_detail(world, surface)
        relief += photo_detail
    displacement = relief*slope_weight*fade
    changed = points+prior*displacement[:, None]
    final = mesh_normals(changed, faces, prior, weld)
    angles = np.degrees(np.arccos(np.clip(np.sum(prior*final, axis=-1), -1, 1)))
    for _ in range(24):
        if float(angles.max()) <= 20: break
        displacement *= .75
        changed = points+prior*displacement[:, None]
        final = mesh_normals(changed, faces, prior, weld)
        angles = np.degrees(np.arccos(np.clip(np.sum(prior*final, axis=-1), -1, 1)))
    else: raise ValueError('geometric normal limit could not be satisfied')
    # Match the existing terrain's normals as well as its positions at borders.
    normal_prior /= np.maximum(np.linalg.norm(normal_prior, axis=-1, keepdims=True), 1e-12)
    # Subdivision alone must preserve the runtime's smooth shading. Add the
    # normal change caused by relief, rather than replacing that shading with
    # area-weighted DEM triangle normals (which reveal vertical stripes).
    final = normal_prior+(final-prior)*fade[:, None]
    final /= np.maximum(np.linalg.norm(final, axis=-1, keepdims=True), 1e-12)
    output.mkdir(parents=True, exist_ok=True)
    buffers = {}
    for name, value, dtype in [('positions', changed, '<f4'), ('normals', final, '<f4'),
                               ('uvs', uvs, '<f4'), ('indices', faces, '<u4')]:
        path = output/(name+'.bin')
        value.astype(dtype).tofile(path)
        buffers[name] = {'file': path.name, 'bytes': path.stat().st_size,
                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    result = dict(info, buffers=buffers, vertices=len(points), triangles=len(faces),
        # Package FNames must not split a numeric suffix: the UE4SS soft-path
        # round trip currently loses that number on the package field.
        package=f'/Game/CustomMaps/Veymont/Nanite/SM_Terrain_T{info["source_section"]}',
        nanite_built=False, source_r16_sha256=hashlib.sha256(Path(info['source_file']).read_bytes()).hexdigest(),
        source_mesh_sha256=hashlib.sha256((source/'positions.txt').read_bytes()).hexdigest(),
        photographic_correction_applied=False,
        photographic_procedural_profile=photo_profile,
        wall_edge_spacing_meters=edge_spacing,
        procedural={'profile': 'compact-white-limestone', 'seed': 17,
                    'maximum_displacement_meters': float(np.abs(displacement).max()),
                    'maximum_normal_change_degrees': float(angles.max()), 'measured_fractures': False},
        tile_edges_unchanged=True)
    (output/'mesh.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--levels', type=int, default=2)
    parser.add_argument('--amplitude', type=float, default=.025)
    parser.add_argument('--surface-profile', type=Path,
                        help='bounded periodic spectrum from extract_rock_surface; not a geographic correction')
    parser.add_argument('--edge-spacing', type=float, help='refine rock edges by actual 3D length in metres')
    args = parser.parse_args()
    try:
        result = prepare(args.source, args.output_dir, args.levels, args.amplitude,
                         args.surface_profile, args.edge_spacing)
    except (ValueError, OSError, KeyError) as error: parser.error(str(error))
    print(json.dumps({key: result[key] for key in ('vertices', 'triangles', 'source_section', 'procedural')}, indent=2))


if __name__ == '__main__':
    main()
