#!/usr/bin/env python3
"""Prepare one volumetric cliff patch, independently of UE.

This is a local research prototype. It does not replace entire map sections or
claim unique recovery of real rock depths from the photographs.
The sculpture profile uses visual style references, not inferred photo normals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
from scipy.ndimage import binary_fill_holes, gaussian_filter, label

from tools.implicit_rock import (CliffField, Fracture, ReferenceSurface, make_blocks, make_sculpture,
    poisson_surface, polygonize_tetrahedra, visible_clusters)
from tools.prepare_nanite_tile import mesh_normals
from tools.extract_rock_surface import integrate_correction


def validate_profile(profile):
    if profile.get('version')!=1 or profile.get('model') not in ('fractured-implicit-blocks','sculpted-implicit-rock'):
        raise ValueError('unsupported implicit block profile')
    limits = {'core_recession_meters':(.3,10), 'maximum_outset_meters':(0,2),
        'detail_amplitude_meters':(0,.5),
        'detail_scale_meters':(.5,10), 'edge_fade_meters':(1,15),
        'photographic_detail_scale_meters':(1,15),
        'photographic_displacement_limit_meters':(0,.5),
        'voxel_spacing_meters':(.15,1)}
    if profile['model']=='fractured-implicit-blocks':
        limits.update({'poisson_separation_meters':(.5,4), 'connectivity_radius_meters':(1,10),
            'maximum_block_diameter_meters':(5,80), 'sample_back_meters':(2,12),
            'sample_front_meters':(0,2), 'front_offset_meters':(0,2),
            'rounding_meters':(.01,.5), 'fracture_zone_meters':(.5,8)})
    for name,(low,high) in limits.items():
        value = profile.get(name)
        if type(value) not in (int,float) or not np.isfinite(value) or not low<=value<=high:
            raise ValueError('invalid '+name)
    budgets = {'max_grid_samples':(1000,2000000), 'max_vertices':(100,100000),
        'max_triangles':(100,200000), 'seed':(0,2**31-1)}
    if profile['model']=='fractured-implicit-blocks':
        budgets.update({'poisson_attempts':(100,30000), 'max_blocks':(1,256)})
    for name,(low,high) in budgets.items():
        if type(profile.get(name)) is not int or not low<=profile[name]<=high:
            raise ValueError('invalid '+name)
    if profile['model']=='fractured-implicit-blocks' and profile['core_recession_meters']>=profile['sample_back_meters']:
        raise ValueError('samples must extend behind the solid backing core')
    if profile['detail_scale_meters']<profile['voxel_spacing_meters']*4:
        raise ValueError('microrelief is too fine for the polygonization spacing')
    if profile.get('rounding_meters',0)+profile['detail_amplitude_meters']>profile['core_recession_meters']:
        raise ValueError('block surface detail exceeds the backing depth')
    if profile['model']=='sculpted-implicit-rock':
        settings = profile.get('sculpture')
        if not isinstance(settings,dict):
            raise ValueError('missing sculpture settings')
        for name,(low,high) in {'mass_offset_meters':(0,.5),'edge_rounding_meters':(.01,.15),
                'root_depth_meters':(.5,3),'protrusion_meters':(.2,1.5),
                'protruding_fraction':(0,1),'maximum_detached_volume_m3':(.01,1),
                'maximum_detached_component_volume_m3':(.01,.5),
                'maximum_sealed_cavity_volume_m3':(.01,.2)}.items():
            value = settings.get(name)
            if type(value) not in (int,float) or not np.isfinite(value) or not low<=value<=high:
                raise ValueError('invalid sculpture '+name)
        if type(settings.get('max_volumes')) is not int or not 1<=settings['max_volumes']<=512:
            raise ValueError('invalid sculpture volume budget')
        levels = settings.get('levels')
        if not isinstance(levels,list) or not 1<=len(levels)<=4:
            raise ValueError('invalid sculpture levels')
        for level in levels:
            if not isinstance(level,dict):
                raise ValueError('invalid sculpture level')
            for name,(low,high) in {'spacing_meters':(.5,10),'density':(.05,2),
                    'cut_depth_meters':(.05,2)}.items():
                value = level.get(name)
                if type(value) not in (int,float) or not np.isfinite(value) or not low<=value<=high:
                    raise ValueError('invalid sculpture '+name)
            radii = np.asarray(level.get('radii_meters'),dtype=float)
            if radii.shape!=(3,) or not np.isfinite(radii).all() or (radii<profile['voxel_spacing_meters']).any() or (radii>5).any():
                raise ValueError('sculpture volume radii are unresolved or out of bounds')


def write_obj(path, points, normals, uv, faces):
    with path.open('w') as out:
        out.write('# Portable implicit cliff patch; map metres; CCW fronts\n')
        for p in points:
            out.write('v %.9f %.9f %.9f\n'%tuple(p))
        for p in uv:
            out.write('vt %.9f %.9f\n'%tuple(p))
        for p in normals:
            out.write('vn %.9f %.9f %.9f\n'%tuple(p))
        for face in faces:
            out.write('f '+' '.join(f'{i+1}/{i+1}/{i+1}' for i in face)+'\n')


def consolidate_volume(field, spacing, profile):
    """Discard detached weathering spalls and fill bounded sealed cavities.

    CSG weathering can release actual pieces of stone. Sculpture budgets use
    physical volumes, including a per-fragment cap; the older fracturing
    prototype retains its strict 128-sample numerical consolidation limit.
    """
    solid = field<0
    labels,_ = label(solid)
    anchored = np.unique(labels[:,:,0])
    disconnected = solid & ~np.isin(labels,anchored)
    enclosed_voids = binary_fill_holes(solid) & ~solid
    sizes = np.bincount(labels[disconnected]) if disconnected.any() else np.array([0])
    cell_volume = float(np.prod(spacing))
    removed_volume = float(disconnected.sum())*cell_volume
    largest_fragment = int(sizes.max())*cell_volume
    filled_volume = float(enclosed_voids.sum())*cell_volume
    cleanup = int(disconnected.sum()+enclosed_voids.sum())
    if profile['model']=='sculpted-implicit-rock':
        limits = profile['sculpture']
        if (removed_volume>limits['maximum_detached_volume_m3'] or
                largest_fragment>limits['maximum_detached_component_volume_m3'] or
                filled_volume>limits['maximum_sealed_cavity_volume_m3']):
            raise ValueError('sculpture consolidation volume budget exceeded: '
                f'{removed_volume:.3f} m3 detached, {largest_fragment:.3f} m3 largest fragment, '
                f'{filled_volume:.3f} m3 sealed air')
    elif cleanup>128:
        raise ValueError(f'volumetric detail is unresolved: {cleanup} samples '
                         f'({int(disconnected.sum())} unanchored, {int(enclosed_voids.sum())} enclosed air; '
                         f'largest detached component {int(sizes.max())} samples)')
    field[disconnected] = spacing.min()*.1
    field[enclosed_voids] = -spacing.min()*.1
    return {'unanchored_grid_samples_removed':int(disconnected.sum()),
            'enclosed_grid_samples_filled':int(enclosed_voids.sum()),
            'detached_volume_removed_m3':removed_volume,
            'largest_detached_fragment_m3':largest_fragment,
            'sealed_cavity_volume_filled_m3':filled_volume}


def prepare(features_dir, profile_path, output):
    started = time.monotonic()
    profile = json.loads(profile_path.read_text()); validate_profile(profile)
    info = json.loads((features_dir/'features.json').read_text())
    if info.get('version')!=1 or info.get('coordinate_system')!='east-south-up-metres':
        raise ValueError('invalid feature reference coordinate system')
    if output.resolve()==features_dir.resolve() or features_dir.resolve() in output.resolve().parents:
        raise ValueError('keep derived output outside the photographic reference')
    with np.load(features_dir/'reference.npz', allow_pickle=False) as data:
        reference = ReferenceSurface(data['depth_meters'], info['extent_meters'])
        normal_candidates = data['normals_candidate_local'].copy()
        confidence = data['normal_candidate_valid'].copy()
        prior = data['normals_prior_local'].copy()
    if (normal_candidates.shape!=(*reference.depth.shape,3) or
            confidence.shape!=reference.depth.shape or prior.shape!=normal_candidates.shape or
            not np.isfinite(normal_candidates).all() or not np.isfinite(prior).all()):
        raise ValueError('invalid photographic normal candidates')
    if profile['edge_fade_meters']*2>=reference.extent.min():
        raise ValueError('edge fade consumes the entire patch')
    basis, origin = np.array(info['basis_columns']), np.array(info['origin_meters'])
    if (basis.shape!=(3,3) or not np.isfinite(basis).all() or
            not np.allclose(basis.T@basis,np.eye(3),atol=1e-6) or np.linalg.det(basis)<.999 or
            origin.shape!=(3,) or not np.isfinite(origin).all()):
        raise ValueError('invalid patch transform')
    # Check the local volume budget before building the Poisson graph.
    margin = profile['core_recession_meters']+1
    grid_origin = np.array([0.,0.,reference.depth.min()-margin])
    grid_top = np.r_[reference.extent,reference.depth.max()+profile['maximum_outset_meters']+1]
    size = np.ceil((grid_top-grid_origin)/profile['voxel_spacing_meters']).astype(int)+1
    samples = int(np.prod(size))
    if samples>profile['max_grid_samples']:
        raise ValueError(f'local volume sample budget exceeded: {samples}')
    spacing = (grid_top-grid_origin)/(size-1)
    fractures = []
    if len(info['fractures'])>32:
        raise ValueError('fracture candidate budget exceeded')
    for item in info['fractures']:
        center, normal = np.array(item['center_local_meters']), np.array(item['normal_local'])
        radius = item['radius_meters']
        if (center.shape!=(3,) or normal.shape!=(3,) or not np.isfinite(center).all() or
                not np.isfinite(normal).all() or not .99<np.linalg.norm(normal)<1.01 or
                type(radius) not in (float,int) or not np.isfinite(radius) or not 0<radius<=50):
            raise ValueError('invalid fracture disk')
        trace = np.asarray(item.get('trace_uv_meters'),dtype=float)
        if trace.shape!=(2,2) or not np.isfinite(trace).all() or np.linalg.norm(trace[1]-trace[0])<.1:
            raise ValueError('invalid finite photographic fracture trace')
        fractures.append(Fracture(center,normal,radius,trace))
    sculpture,sculpture_levels = None,[]
    if profile['model']=='sculpted-implicit-rock':
        sculpture,sculpture_levels = make_sculpture(reference,profile)
        points,blocks,unsupported = [],[],0
        print(f'Sculpture: {len(sculpture.chunks)} anchored masses; {len(sculpture.cutters)} finite removal volumes',flush=True)
    else:
        points = poisson_surface(reference, profile['poisson_separation_meters'],
            profile['poisson_attempts'], profile['seed'],
            profile['sample_back_meters'],profile['sample_front_meters'])
        print(f'Poisson samples: {len(points)}; finite fracture candidates: {len(fractures)}', flush=True)
        clusters = visible_clusters(points, fractures, profile['connectivity_radius_meters'],
                                    profile['maximum_block_diameter_meters'])
        blocks, unsupported = make_blocks(clusters, reference, normal_candidates, confidence, profile)
    photo_spacing = reference.extent/np.array([reference.depth.shape[1]-1,reference.depth.shape[0]-1])
    # The integration function uses image rows down; our reference rows go up.
    photo_delta = integrate_correction(prior[::-1],normal_candidates[::-1],confidence[::-1],
        tuple(photo_spacing),profile['photographic_detail_scale_meters'],
        profile['photographic_displacement_limit_meters'],3)[::-1]
    sigma = np.maximum(profile['voxel_spacing_meters']/photo_spacing[::-1],1)
    photo_delta = gaussian_filter(photo_delta,sigma=sigma)
    # Pins remain exact even after filtering the finite photographic patch.
    photo_delta[[0,-1],:] = 0;photo_delta[:,[0,-1]] = 0
    photo_detail = ReferenceSurface(photo_delta,reference.extent)
    cliff = CliffField(reference,blocks,profile,fractures,photo_detail,sculpture)
    if sculpture is None:
        print(f'Supported implicit blocks: {len(blocks)}; discarded unsupported: {unsupported}', flush=True)
    # A narrow volume around this patch, never a voxelization of the map.
    field = np.empty(tuple(size),np.float32)
    # One UV column at a time, plus bounded evaluation batches in CliffField.
    v,d = np.meshgrid(np.arange(size[1])*spacing[1],
                      grid_origin[2]+np.arange(size[2])*spacing[2], indexing='ij')
    slab = np.stack([np.zeros_like(v),v,d],axis=-1)
    for x in range(size[0]):
        slab[...,0] = x*spacing[0]
        field[x] = cliff.signed(slab)
    if not np.all(field[:,:,0]<0) or not np.all(field[:,:,-1]>0):
        raise ValueError('local volume does not enclose the rock surface')
    consolidation = consolidate_volume(field,spacing,profile)
    local, faces = polygonize_tetrahedra(field,grid_origin,spacing,
        profile['max_vertices'],profile['max_triangles'])
    # The four outer edges are an exact reference-surface boundary, including
    # a zero derivative of the block blend. No rear/side cap is generated.
    perimeter = ((local[:,:2]<1e-8) | (local[:,:2]>reference.extent-1e-8)).any(axis=1)
    local[perimeter,2] = reference.sample(local[perimeter,:2])
    before_snap = local[:,2].copy()
    source_depth = reference.sample(local[:,:2])
    # Sampling/interpolation of a curved reference can overshoot its envelope
    # slightly. Enforce the actual metric envelope on the final mesh as well.
    local[:,2] = np.clip(local[:,2], source_depth-profile['core_recession_meters'],
                        source_depth+profile['maximum_outset_meters'])
    envelope_snap = float(np.max(np.abs(local[:,2]-before_snap)))
    if envelope_snap>profile['voxel_spacing_meters']:
        raise ValueError('surface extraction exceeds its envelope error budget')
    n = cliff.normals(local, min(spacing)*.08)
    geometric = np.cross(local[faces[:,1]]-local[faces[:,0]],local[faces[:,2]]-local[faces[:,0]])
    reverse = (geometric*n[faces].mean(axis=1)).sum(axis=1)<0
    faces[reverse] = faces[reverse][:,[0,2,1]]
    world = origin+local@basis.T
    normals = n@basis.T
    uv = local[:,:2]/20
    output.mkdir(parents=True,exist_ok=True)
    write_obj(output/'patch.obj',world,normals,uv,faces)
    # Separate source topology is expected: this model permits undercuts.
    rows,columns = reference.depth.shape
    u,v = np.meshgrid(np.linspace(0,reference.extent[0],columns),
                      np.linspace(0,reference.extent[1],rows))
    baseline = np.stack([u,v,reference.depth],axis=-1).reshape(-1,3)
    start = np.arange(rows*columns).reshape(rows,columns)[:-1,:-1].ravel()
    base_faces = np.column_stack([start,start+1,start+columns,
                                 start+1,start+columns+1,start+columns]).reshape(-1,3)
    base_world = origin+baseline@basis.T
    base_normal = mesh_normals(base_world,base_faces,prior.reshape(-1,3)@basis.T)
    write_obj(output/'patch-base.obj',base_world,base_normal,baseline[:,:2]/20,base_faces)
    buffers = {}
    mesh_origin = (world.min(axis=0)+world.max(axis=0))/2
    for name,array,dtype in [('positions',world-mesh_origin,'<f4'),('normals',normals,'<f4'),
                             ('uvs',uv,'<f4'),('indices',faces,'<u4')]:
        path = output/(name+'.bin'); array.astype(dtype).tofile(path)
        buffers[name] = {'file':path.name,'bytes':path.stat().st_size,
                         'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    np.savez_compressed(output/'geometry.npz',positions_local=local,normals_local=n,faces=faces,
                        source_local=baseline,source_faces=base_faces,field=field,
                        photographic_displacement=photo_delta,
                        grid_origin=grid_origin,grid_spacing=spacing)
    metrics = {'poisson_samples':len(points),'fracture_candidates':len(fractures),
        'supported_blocks':len(blocks),'discarded_unsupported_blocks':unsupported,
        'grid_samples':samples,'grid_size':size.tolist(),'vertices':len(world),'triangles':len(faces),
        'perimeter_vertices':int(perimeter.sum()),
        'maximum_perimeter_error_meters':float(np.max(np.abs(reference.signed(local[perimeter])))),
        'maximum_outset_meters':float(reference.signed(local).max()),
        'maximum_recession_meters':float(-reference.signed(local).min()),
        'maximum_envelope_snap_meters':envelope_snap,
        'maximum_photographic_candidate_displacement_meters':float(np.abs(photo_delta).max()),
        'upward_facing_vertices':int((n[:,1]>.5).sum()),
        'inward_facing_vertices':int((n[:,2]<0).sum()),
        'rays_with_multiple_surface_crossings':int((np.count_nonzero(
            (field[:,:,:-1]<0)!=(field[:,:,1:]<0),axis=2)>1).sum()),
        'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'elapsed_seconds':time.monotonic()-started}
    metrics.update(consolidation)
    if sculpture is not None:
        metrics.update(sculpture_additive_volumes=len(sculpture.chunks),
                       sculpture_subtractive_volumes=len(sculpture.cutters),sculpture_levels=sculpture_levels)
    report = {'version':1,'model':profile['model'],'coordinate_system':info['coordinate_system'],
        'origin_meters':origin.tolist(),'basis_columns':basis.tolist(),
        'size':[columns,rows],'spacing_meters':(reference.extent/[columns-1,rows-1]).tolist(),
        'material':{'albedo_srgb':[.9,.9,.87],'roughness':.85},
        'reference':info,'profile':profile,'metrics':metrics,'topology_changed':True,
        'photographic_colour_used_as_material':False,'installed_in_game':False,
        'photographic_candidate_warp_applied':bool(np.any(photo_delta)),
        'photographic_fracture_candidates_used':sculpture is None,
        'photographic_normals_uniquely_identified':False,
        'source_profile_sha256':hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        'source_features_sha256':hashlib.sha256((features_dir/'features.json').read_bytes()).hexdigest(),
        'source_reference_sha256':hashlib.sha256((features_dir/'reference.npz').read_bytes()).hexdigest(),
        'generator_sha256':{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                            for name in ('implicit_rock.py','prepare_implicit_cliff.py')},
        'method_reference':'https://aparis69.github.io/public_html/projects/paris2020_Blocks.html'}
    (output/'surface.json').write_text(json.dumps(report,indent=2)+'\n')
    mesh = {'version':1,'package':'/Game/CustomMaps/Veymont/Nanite/SM_ImplicitCliffStudy',
        'coordinate_system':info['coordinate_system'],'winding':'counterclockwise',
        'origin_meters':mesh_origin.tolist(),'vertices':len(world),'triangles':len(faces),
        'buffers':buffers,'nanite_built':False,'geological_model':profile['model'],
        'camera_verified':info['camera_verified'],'metric_fracture_depths_measured':False}
    (output/'mesh.json').write_text(json.dumps(mesh,indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('features',type=Path)
    parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args = parser.parse_args()
    # Applied before allocations; a repeat cannot exhaust the workstation.
    resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
    resource.setrlimit(resource.RLIMIT_CPU,(300,305))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    try:
        result = prepare(args.features,args.profile,args.output_dir)
    except (ValueError,KeyError,OSError,MemoryError) as error:
        parser.error(str(error))
    print(json.dumps(result['metrics'],indent=2))


if __name__=='__main__':
    main()
