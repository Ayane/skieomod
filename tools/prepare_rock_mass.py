#!/usr/bin/env python3
"""Reproduce the rejected banded-relief experiment with matching snow.

Its altitude-driven recession leaves smooth walls with conspicuous bands.
This experiment is not the selected geological approach for Veymont.
The profile is a synthetic interpretation, not measured photographic geometry.
See docs/rock-surface-extraction.md for the block-and-fracture research direction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from tools.prepare_nanite_tile import refine_walls, mesh_normals


def smooth(value):
    t = np.clip(value, 0, 1)
    return t*t*t*(10+t*(-15+6*t))


def hashed(index, seed):
    # Deterministic per bed/joint; independent of tile or evaluation order.
    return np.mod(np.sin(index*127.1+seed*311.7)*43758.5453, 1)


def stone_noise(u, z, scale, seed):
    """Continuous non-periodic rock field; no image lighting or tile resets."""
    x, y = u/scale, z/scale
    ix, iy = np.floor(x), np.floor(y)
    tx, ty = smooth(x-ix), smooth(y-iy)
    def corner(dx, dy):
        return hashed((ix+dx)*17.31+(iy+dy)*71.73, seed)
    low = corner(0,0)*(1-tx)+corner(1,0)*tx
    high = corner(0,1)*(1-tx)+corner(1,1)*tx
    return low*(1-ty)+high*ty


def recession(world, profile):
    axis = np.asarray(profile['horizontal_axis'], dtype=float)
    axis /= np.linalg.norm(axis)
    u, z = world[:, :2]@axis, world[:, 2]
    seed = profile['seed']
    # A slow undulation and slight bed dip, rather than perfectly ruled bands.
    bed_height = z+.018*u+1.8*np.sin(u/95)+.8*np.sin(u/29)
    phase = bed_height/profile['bed_spacing_meters']
    phase += .17*np.sin(phase*.73+seed)
    bed = np.floor(phase)
    phase -= bed
    # A broad rock face and a short setback make an actual shelf/riser pair.
    ledge = smooth(phase/.65)*(1-smooth((phase-.80)/.20))
    strength = .18+.82*(1-smooth((z-profile['massive_above_meters'])/profile['massive_blend_meters']))
    continuity = .4+.6*stone_noise(u, z, 45, seed+10)
    beds = ledge*(.55+.45*hashed(bed, seed))*continuity*strength*profile['bed_recession_meters']
    joint_coordinate = (u+1.2*np.sin(z/37)+2*np.sin(z/103))/profile['joint_spacing_meters']
    joint = np.floor(joint_coordinate)
    local = joint_coordinate-joint
    # Off-centre fractures with variable widths and interrupted exposure.
    centre = .25+.50*hashed(joint, seed+1)
    width = profile['joint_width_meters']/profile['joint_spacing_meters']*(.75+.5*hashed(joint, seed+2))
    fissure = np.exp(-((local-centre)/width)**2)
    exposure = .3+.7*smooth(.5+.45*np.sin(z/61+hashed(joint, seed+3)*6))
    joints = fissure*exposure*profile['joint_recession_meters']
    slabs = .65*(1+np.sin(u/11+np.sin(z/17)))*(.5+.5*np.sin(z/23+u/37))
    # Broken local faces add character to the massive upper pillars as well.
    # Keep the finest scale resolvable by the prepared geometry, not aliased
    # sub-metre noise on three-metre triangles.
    scale = max(profile['surface_scale_meters'], profile['edge_spacing_meters']*3)
    surface = np.zeros(len(world))
    for octave, weight in enumerate((.52,.30,.18)):
        noise = stone_noise(u, z, scale*2**(2-octave), seed+20+octave)
        surface += weight*(1-np.abs(2*noise-1))
    surface *= profile['surface_recession_meters']
    return np.minimum(beds+joints+slabs+surface, profile['maximum_recession_meters'])


def carve(points, normal_prior, faces, profile):
    _, weld = np.unique(np.round(points, 8), axis=0, return_inverse=True)
    base_normals = mesh_normals(points, faces, normal_prior, weld)
    normal_prior = normal_prior/np.maximum(np.linalg.norm(normal_prior, axis=-1, keepdims=True), 1e-12)
    axis=np.asarray(profile['horizontal_axis'],dtype=float);axis/=np.linalg.norm(axis)
    front=np.array([axis[1],-axis[0],0.])
    horizontal=np.broadcast_to(front,points.shape).copy()
    # Blend only on the OUTER perimeter of the whole massif. The former tile
    # boundary is ordinary interior geometry, including its shading normals.
    distance = np.minimum(points[:, :2]-points[:, :2].min(axis=0),
                          points[:, :2].max(axis=0)-points[:, :2]).min(axis=1)
    fade = smooth(distance/profile['outer_blend_meters'])
    rock = (1-smooth((normal_prior[:, 2]-.20)/.45))*smooth((normal_prior@front-.25)/.45)
    depth = recession(points, profile)*fade*rock
    # A common recession direction avoids the spikes created by carving each
    # DEM corner along a different smoothed normal. Facing/slope weights retain
    # the crest, reverse faces and ordinary ground.
    # Duplicated projection UVs must never create independent rock cracks.
    weighted = np.zeros((int(weld.max())+1, 4))
    np.add.at(weighted, weld, np.column_stack([horizontal, depth]))
    weighted /= np.bincount(weld)[:, None]
    horizontal, depth = weighted[weld, :3], weighted[weld, 3]
    horizontal /= np.maximum(np.linalg.norm(horizontal, axis=-1, keepdims=True), 1e-12)
    before = np.cross(points[faces[:, 1]]-points[faces[:, 0]], points[faces[:, 2]]-points[faces[:, 0]])
    area = np.sum(before*before, axis=1)
    scales = np.ones(len(weighted))
    _,unique=np.unique(weld,return_index=True)
    for attempt in range(32):
        changed = points-horizontal*(depth*scales[weld])[:, None]
        after = np.cross(changed[faces[:, 1]]-changed[faces[:, 0]], changed[faces[:, 2]]-changed[faces[:, 0]])
        # Constant-direction recession preserves the projection winding along
        # front exactly. Comparing to the OLD face normal would also reject
        # valid undercuts and shelves; reject only collapsed triangles here.
        bad = np.sum(after*after, axis=1)<area*.04
        if not bad.any(): break
        problem=np.unique(weld[faces[bad]])
        distance=cKDTree(points[unique[problem]]).query(points[unique],workers=1)[0]
        # Reduce a smooth neighbourhood, not isolated vertices that leave
        # needle-like uncarved peaks beside deep recesses.
        scales *= .65+.35*smooth(distance/18)
    else: raise ValueError(f'unable to preserve the rock surface topology: {bad.sum()} faces, minimum base area {np.sqrt(area[bad]).min():.8g}, recession {np.max(depth[faces[bad]]):.4g}')
    current = mesh_normals(changed, faces, base_normals, weld)
    # Rotate source shading by the actual geometric normal change. Adding two
    # normal vectors is only a small-angle approximation and breaks at shelves.
    axis=np.cross(base_normals,current)
    cosine=np.sum(base_normals*current,axis=1)
    cross=np.cross(axis,normal_prior)
    rotated=normal_prior+cross+np.cross(axis,cross)/np.maximum(1+cosine[:,None],1e-8)
    final = normal_prior+(rotated-normal_prior)*fade[:,None]
    final /= np.maximum(np.linalg.norm(final, axis=-1, keepdims=True), 1e-12)
    peak = np.linalg.norm(changed-points, axis=1)
    return changed, final, {'maximum_recession_meters': float(peak.max()),
        'median_rock_recession_meters': float(np.median(peak[rock>.8])),
        'vertices_with_metre_relief': int(np.count_nonzero(peak>1)),
        'locally_damped_vertices': int(np.count_nonzero(scales<1)),
        'maximum_normal_change_degrees': float(np.degrees(np.arccos(np.clip(np.sum(final*normal_prior, axis=1), -1, 1))).max())}


def prepare(sources, output, profile_path):
    profile = json.loads(profile_path.read_text())
    if profile.get('version') != 1 or profile.get('character') != 'compact-limestone-beds-and-joints':
        raise ValueError('unsupported limestone character profile')
    for key in ('bed_spacing_meters','joint_spacing_meters','joint_width_meters','outer_blend_meters','edge_spacing_meters','massive_blend_meters','surface_scale_meters'):
        if type(profile.get(key)) not in (float,int) or not np.isfinite(profile[key]) or profile[key]<=0:
            raise ValueError('invalid '+key)
    if not 0<profile['maximum_recession_meters']<=12: raise ValueError('recession must be within 0..12 m')
    if type(profile.get('seed')) is not int or not 0<=profile['seed']<=2**31-1: raise ValueError('invalid rock seed')
    axis=np.asarray(profile.get('horizontal_axis'),dtype=float)
    if axis.shape!=(2,) or not np.isfinite(axis).all() or np.linalg.norm(axis)<1e-8: raise ValueError('invalid horizontal axis')
    for key in ('bed_recession_meters','joint_recession_meters','surface_recession_meters'):
        if type(profile.get(key)) not in (int,float) or not np.isfinite(profile[key]) or not 0<=profile[key]<=12:
            raise ValueError('invalid '+key)
    if not np.isfinite(profile['massive_above_meters']): raise ValueError('invalid massive bed altitude')
    if not .5<=profile['edge_spacing_meters']<=8: raise ValueError('invalid wall edge spacing')
    if not 1<=len(sources)<=64: raise ValueError('provide 1..64 adjacent source sections')
    all_points, all_normals, all_uvs, all_faces, sections, fingerprints = [], [], [], [], [], []
    first = None; count = 0
    for source in sources:
        info = json.loads((source/'tile-source.json').read_text())
        if (info.get('version')!=1 or info.get('coordinate_system')!='east-south-up-metres'
                or info.get('winding')!='counterclockwise'): raise ValueError('invalid source coordinate system')
        if first is None: first = info
        for key in ('map_id','source_file','source_definition','source_origin_centimeters','sample_step','tile_quads','uv_tile_meters'):
            if first[key] != info[key]: raise ValueError('massif sources do not match')
        if info['source_section'] in sections: raise ValueError('duplicate massif section')
        p = np.round(np.loadtxt(source/'positions.txt').reshape(-1,3)+info['origin_meters'], 8)
        n = np.loadtxt(source/'normals.txt').reshape(-1,3)
        uv = np.loadtxt(source/'uvs.txt').reshape(-1,2)
        f = np.loadtxt(source/'indices.txt',dtype=np.uint32).reshape(-1,3)
        if len(p)!=info['vertices'] or len(f)!=info['triangles'] or f.max()>=len(p): raise ValueError('invalid source buffers')
        if not all(np.isfinite(a).all() for a in (p,n,uv)): raise ValueError('nonfinite source buffers')
        all_points.append(p);all_normals.append(n);all_uvs.append(uv);all_faces.append(f+count)
        sections.append(info['source_section']);count+=len(p)
        fingerprints.append(hashlib.sha256((source/'positions.txt').read_bytes()).hexdigest())
    columns=int(np.ceil((first['source_definition']['vertices'][0]-1)/first['sample_step']/first['tile_quads']))
    cells={(section%columns,section//columns) for section in sections}
    xs,ys=zip(*cells)
    if cells!={(x,y) for x in range(min(xs),max(xs)+1) for y in range(min(ys),max(ys)+1)}:
        raise ValueError('massif source sections must cover a complete rectangle')
    points, prior, uvs, faces = map(np.concatenate,(all_points,all_normals,all_uvs,all_faces))
    points, prior, uvs, faces = refine_walls(points, prior, uvs, faces, profile['edge_spacing_meters'])
    changed, normals, metrics = carve(points, prior, faces, profile)
    origin = (points.min(axis=0)+points.max(axis=0))/2
    r16_sha = hashlib.sha256(Path(first['source_file']).read_bytes()).hexdigest()
    manifest=json.loads(Path(first['source_manifest']).read_text())
    snow_offset=manifest['terrain'].get('runtime',{}).get('snow_offset_centimeters',30)
    if not isinstance(snow_offset,(int,float)) or not np.isfinite(snow_offset) or not 0<=snow_offset<=200:
        raise ValueError('invalid snow shell offset')
    results = []
    for layer in ('terrain','snow'):
        directory = output/layer;directory.mkdir(parents=True,exist_ok=True)
        package = '/Game/CustomMaps/Veymont/Nanite/SM_GrandVeymont'+('Strata' if layer=='terrain' else 'StrataSnow')
        positions = changed-origin
        layer_uvs = uvs
        if layer=='snow':
            positions = positions+np.array([0,0,snow_offset/100])
            layer_uvs = points[:, :2]/first['uv_tile_meters']
        buffers = {}
        for name, value, dtype in [('positions',positions,'<f4'),('normals',normals,'<f4'),('uvs',layer_uvs,'<f4'),('indices',faces,'<u4')]:
            path = directory/(name+'.bin');value.astype(dtype).tofile(path)
            buffers[name]={'file':path.name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        result = dict(first,vertices=len(points),triangles=len(faces),origin_meters=origin.tolist(),
            package=package,buffers=buffers,source_sections=sorted(sections),layer=layer,mesh_algorithm=2,
            source_r16_sha256=r16_sha,source_mesh_sha256=fingerprints,
            profile_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
            snow_offset_centimeters=snow_offset,
            photographic_correction_applied=False,procedural=dict(profile,**metrics),
            tile_edges_unchanged=False,outer_perimeter_unchanged=True,internal_tile_seams=False,nanite_built=False)
        (directory/'mesh.json').write_text(json.dumps(result,indent=2)+'\n');results.append(result)
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources',type=Path,nargs='+');parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True);args=parser.parse_args()
    try: results=prepare(args.sources,args.output_dir,args.profile)
    except (ValueError,OSError,KeyError) as error: parser.error(str(error))
    print(json.dumps([{k:r[k] for k in ('layer','vertices','triangles','procedural')} for r in results],indent=2))


if __name__=='__main__': main()
