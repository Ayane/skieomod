#!/usr/bin/env python3
"""Derive thin snow coats from a sculpted surface, with buried feathered edges."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from tools.implicit_rock import smooth
from tools.export_sculpted_massif import SurfaceTransition
from tools.prepare_sculpted_massif import NativeMassif


def coat_surface(points, normals, faces, transition, kind):
    cross = np.cross(points[faces[:, 1]]-points[faces[:, 0]],
                     points[faces[:, 2]]-points[faces[:, 0]])
    up = cross[:, 2]/np.maximum(np.linalg.norm(cross, axis=1), 1e-12)
    if kind == 'snow_deposits':
        weight = smooth((normals[:, 2]-.25)/.55)*smooth(transition/.08)
        maximum = .10
    elif kind == 'snow_transition':
        weight = (1-smooth(transition/.65))*smooth(transition/.04)
        maximum = .05
    else:
        raise ValueError('unknown snow coat')
    # Small world-space thickness variations break up a straight mask edge.
    # They do not vary with partition identity or turn the rock into stripes.
    variation = (.85+.15*np.sin(points[:, 0]*1.71+np.sin(points[:, 2]*2.13))
        *np.sin(points[:, 1]*1.37+points[:, 2]*.43))
    depth = (maximum+.04)*weight*variation-.04
    keep = depth[faces].max(axis=1)>0
    if kind == 'snow_deposits':
        # Smoothed vertex normals at a ledge also point upward on its adjacent
        # wall. That wall does not retain snow: test the actual facet as well.
        keep &= up>.5
    else:
        # Only steep faces need to bridge the native snow/rock color boundary.
        # A world-space stochastic coverage ramp softens color, rather than
        # hiding the entire gradient behind a single geometric clipping line.
        center = points[faces].mean(axis=1)
        phase = np.sin(center@np.array([12.9898,78.233,37.719]))*43758.5453
        random = phase-np.floor(phase)
        probability = weight[faces].mean(axis=1)
        keep = (up<.65) & (random<probability) & (probability>0)
        depth = np.where(weight>0, .012*variation, -.04)
    selected = faces[keep]
    used, inverse = np.unique(selected, return_inverse=True)
    positions = points[used]+normals[used]*depth[used, None]
    return positions, normals[used], inverse.reshape(-1, 3).astype(np.uint32), used


def prepare(sources, meshes, output):
    native = NativeMassif(sources)
    transition = SurfaceTransition(native, 24.)
    results = []
    for directory in sorted(meshes.glob('s*-p*')):
        reference = json.loads((directory/'snow/mesh.json').read_text())
        width = reference.get('surface_transition', {}).get('width_meters')
        if width != transition.width:
            raise ValueError('snow coat and rock transition widths differ')
        with np.load(directory/'geometry.npz', allow_pickle=False) as data:
            points, baseline, faces = [data[k].copy() for k in ('points','baseline','faces')]
        normals = np.fromfile(directory/'snow/normals.bin', dtype='<f4').reshape(-1, 3).astype(float)
        fade = transition.weight(baseline)
        for kind in ('snow_deposits','snow_transition'):
            p, n, f, used = coat_surface(points, normals, faces, fade, kind)
            if not len(f):
                continue
            stage = output/directory.name/kind
            stage.mkdir(parents=True, exist_ok=True)
            origin = np.array(reference['origin_meters'])
            buffers = {}
            for name, value, dtype in (('positions',p-origin,'<f4'),('normals',n,'<f4'),
                    ('uvs',p[:, :2]/2,'<f4'),('indices',f,'<u4')):
                path = stage/(name+'.bin');value.astype(dtype).tofile(path)
                buffers[name] = {'file':path.name,'bytes':path.stat().st_size,
                    'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            suffix = 'SnowDeposits' if kind=='snow_deposits' else 'SnowTransition'
            package = (f"/Game/CustomMaps/Veymont/Nanite/SM_SculptedMassifS{reference['source_section']}"
                f"P{reference['part']:02d}{suffix}")
            source_origin = np.array(reference['source_origin_centimeters'][:2])/100
            extent = (np.array(reference['source_definition']['vertices'])-1)*reference['source_definition']['spacing_meters']
            uv = (baseline[used, :2]-source_origin)/extent
            # Bounds locate the continuous cliff's regional snow samples.
            uv_bounds = [uv.min(0).tolist(), uv.max(0).tolist()]
            result = dict(reference,layer=kind,package=package,buffers=buffers,
                vertices=len(p),triangles=len(f),primary_surface_triangles=0,
                interior_backing_triangles=0,interior_backing_meters=0,
                snow_uv_bounds=uv_bounds,
                coat_model='facet-slope-coat-with-buried-edges-and-stochastic-rim-v2',
                coat_maximum_thickness_meters=.1 if kind=='snow_deposits' else .05,
                coat_material='/Game/Materials/Backgrounds/M_Snow.M_Snow',
                nanite_built=False)
            (stage/'mesh.json').write_text(json.dumps(result,indent=2)+'\n')
            results.append({'mesh':str(stage/'mesh.json'),'kind':kind,'triangles':len(f)})
    report = {'assets':len(results),'triangles':sum(r['triangles'] for r in results),'meshes':results,
        'weather_source':'native coarse snow render target; rendering coat only',
        'collision_changed':False}
    output.mkdir(parents=True,exist_ok=True)
    (output/'deposits.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', type=Path, nargs='+')
    parser.add_argument('--meshes-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = prepare(args.sources, args.meshes_dir, args.output_dir)
    print(json.dumps({k:v for k,v in result.items() if k!='meshes'},indent=2))


if __name__=='__main__': main()
