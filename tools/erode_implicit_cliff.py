#!/usr/bin/env python3
"""Erode an existing sculpted rock volume, without rebuilding its CSG shapes.

This is procedural exposure/curvature weathering, not a calibrated geological
or hydraulic simulation. Material is removed from the completed 3D volume.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import resource
import shutil
import time

import numpy as np
from scipy.ndimage import (binary_dilation, distance_transform_edt, gaussian_filter,
                           generate_binary_structure, map_coordinates)
from scipy.spatial import cKDTree

from tools.build_nanite_rock import validate_mesh
from tools.implicit_rock import ReferenceSurface, polygonize_tetrahedra, smooth, unit
from tools.prepare_implicit_cliff import consolidate_volume, write_obj


def validate_erosion(profile):
    if profile.get('version')!=1 or profile.get('model')!='exposure-curvature-erosion':
        raise ValueError('unsupported erosion profile')
    limits = {'depth_meters':(0,.6),'curvature_radius_meters':(.1,1),
              'face_rate':(0,1),'exposure_floor':(0,1),
              'maximum_removed_volume_m3':(.01,50)}
    for name,(low,high) in limits.items():
        value = profile.get(name)
        if type(value) not in (int,float) or not np.isfinite(value) or not low<=value<=high:
            raise ValueError('invalid erosion '+name)
    if type(profile.get('iterations')) is not int or not 1<=profile['iterations']<=64:
        raise ValueError('invalid erosion iteration budget')
    direction = profile.get('weather_direction_local')
    if (not isinstance(direction,list) or len(direction)!=3 or
            any(type(v) not in (int,float) or not np.isfinite(v) for v in direction) or
            np.linalg.norm(direction)<1e-6):
        raise ValueError('invalid erosion weather direction')


def erode_field(field, spacing, profile, fade=None):
    """Inward level-set evolution; convex exposed edges lose more material.

    The input is not assumed to be an SDF: velocity is multiplied by the
    field gradient. A conservative initial distance band protects the core;
    an initial-gradient cap also limits scalar advance. These are discrete
    bounds, not claims of exact geological retreat in metres.
    """
    validate_erosion(profile)
    spacing = np.asarray(spacing,dtype=float)
    field = np.asarray(field)
    if (field.ndim!=3 or min(field.shape)<3 or field.size>2_000_000 or
            not np.isfinite(field).all() or spacing.shape!=(3,) or
            not np.isfinite(spacing).all() or (spacing<=0).any()):
        raise ValueError('invalid or excessive erosion volume')
    if profile['curvature_radius_meters']<spacing.max():
        raise ValueError('erosion curvature scale is unresolved')
    weight = np.ones(field.shape[:2],dtype=np.float32) if fade is None else np.asarray(fade)
    if weight.shape!=field.shape[:2] or not np.isfinite(weight).all() or (weight<0).any() or (weight>1).any():
        raise ValueError('invalid erosion boundary weight')
    original = field.astype(np.float32)
    current = original.copy()
    depth = profile['depth_meters']
    if depth==0:
        return current,{'iterations':0,'grid_estimated_removed_volume_m3':0.,'maximum_scalar_advance':0.}
    steps = max(profile['iterations'],int(np.ceil(depth/(spacing.min()*.25))))
    if steps>128:
        raise ValueError('erosion CFL iteration budget exceeded')
    gradient = np.gradient(original,*spacing,edge_order=2)
    original_length = np.sqrt(sum(g*g for g in gradient))
    upper = original+depth*original_length*weight[:,:,None]
    # EDT measures distances between sample centres. Add one voxel diagonal
    # to the protected band to account for an interpolated sub-voxel surface.
    protected = distance_transform_edt(original<0,sampling=spacing)>depth+np.linalg.norm(spacing)
    sigma = profile['curvature_radius_meters']*.5/spacing
    direction = unit(np.asarray(profile['weather_direction_local'],dtype=float))
    dt = depth/steps
    air_neighbours = generate_binary_structure(3,1)
    for _ in range(steps):
        gradient = np.gradient(current,*spacing,edge_order=2)
        length = np.sqrt(sum(g*g for g in gradient))
        normal = [gaussian_filter(g/np.maximum(length,1e-10),sigma=sigma,mode='nearest') for g in gradient]
        normal_length = np.sqrt(sum(n*n for n in normal))
        normal = [n/np.maximum(normal_length,1e-10) for n in normal]
        curvature = sum(np.gradient(n,spacing[axis],axis=axis,edge_order=2) for axis,n in enumerate(normal))
        convex = np.clip(curvature*profile['curvature_radius_meters'],0,1)
        exposure = profile['exposure_floor']+(1-profile['exposure_floor'])*np.clip(
            sum(direction[axis]*n for axis,n in enumerate(normal)),0,1)
        rate = exposure*(profile['face_rate']+(1-profile['face_rate'])*convex)
        # Only the exposed interface and its immediate neighbours evolve.
        # This prevents a positive-curvature pocket from starting inside rock.
        # Use face neighbours, matching the connected-component/cavity audit.
        # Corner-only contacts can seed closed air voxels inside the mass.
        near_air = binary_dilation(current>=0,structure=air_neighbours)
        increment = dt*rate*length*weight[:,:,None]*near_air
        increment[protected] = 0
        current = np.minimum(current+increment,upper).astype(np.float32)
        current = np.maximum(current,original)
    removed = (original<0) & (current>=0)
    volume = float(removed.sum()*np.prod(spacing))
    if volume>profile['maximum_removed_volume_m3']:
        raise ValueError(f'erosion removed-volume budget exceeded: {volume:.3f} m3')
    return current,{'iterations':steps,'grid_estimated_removed_volume_m3':volume,
                    'maximum_scalar_advance':float((current-original).max()),
                    'material_added_by_erosion':False}


def sample_field(field, points, origin, spacing):
    return map_coordinates(field,((points-origin)/spacing).T,order=1,mode='nearest')


def prepare(source, profile_path, output):
    started = time.monotonic()
    source,output = source.resolve(),output.resolve()
    if output==source or source in output.parents:
        raise ValueError('keep erosion output outside the original sculpture')
    settings = json.loads(profile_path.read_text());validate_erosion(settings)
    info = json.loads((source/'surface.json').read_text())
    if info.get('model')!='sculpted-implicit-rock' or info.get('coordinate_system')!='east-south-up-metres':
        raise ValueError('erosion requires an existing portable sculpted rock volume')
    validate_mesh(source/'mesh.json')
    with np.load(source/'geometry.npz',allow_pickle=False) as data:
        original,grid_origin,spacing = [data[name].copy() for name in ('field','grid_origin','grid_spacing')]
        before_points,before_normals = [data[name].copy() for name in ('positions_local','normals_local')]
        native,native_faces = [data[name].copy() for name in ('source_local','source_faces')]
    extent = np.array(info['reference']['extent_meters'])
    u,v = np.meshgrid(grid_origin[0]+np.arange(original.shape[0])*spacing[0],
                      grid_origin[1]+np.arange(original.shape[1])*spacing[1],indexing='ij')
    edge = np.minimum.reduce([u,v,extent[0]-u,extent[1]-v])
    fade = smooth(edge/info['profile']['edge_fade_meters'])
    field,erosion_metrics = erode_field(original,spacing,settings,fade)
    consolidation = consolidate_volume(field,spacing,info['profile'])
    if np.any((original>=0) & (field<0)):
        raise ValueError('consolidation would add rock outside the original sculpture')
    local,faces = polygonize_tetrahedra(field,grid_origin,spacing,
        info['profile']['max_vertices'],info['profile']['max_triangles'])
    rows,columns = info['size'][1],info['size'][0]
    reference = ReferenceSurface(native[:,2].reshape(rows,columns),extent)
    perimeter = ((local[:,:2]<1e-8) | (local[:,:2]>extent-1e-8)).any(axis=1)
    local[perimeter,2] = reference.sample(local[perimeter,:2])
    displacement = reference.signed(local)
    if (displacement.max()>info['profile']['maximum_outset_meters']+spacing.max() or
            displacement.min()<-info['profile']['core_recession_meters']-spacing.max()):
        raise ValueError('eroded surface exceeds the original macro envelope')
    gradient = np.gradient(field,*spacing,edge_order=2)
    normal = unit(np.stack([sample_field(g,local,grid_origin,spacing) for g in gradient],axis=-1))
    if settings['depth_meters']==0:
        # Disabling the phase also preserves the source's continuous-field
        # normals, instead of changing its shading through grid differentiation.
        all_distance,all_index = cKDTree(before_points).query(local)
        if all_distance.max()>1e-7:
            raise ValueError('disabled erosion changed the original geometry')
        normal = before_normals[all_index].copy()
    distance,index = cKDTree(before_points).query(local[perimeter])
    if distance.max()>1e-7:
        raise ValueError('erosion changed the original boundary vertices')
    normal[perimeter] = before_normals[index]
    geometric = np.cross(local[faces[:,1]]-local[faces[:,0]],local[faces[:,2]]-local[faces[:,0]])
    reverse = (geometric*normal[faces].mean(axis=1)).sum(axis=1)<0
    faces[reverse] = faces[reverse][:,[0,2,1]]
    basis,origin = np.array(info['basis_columns']),np.array(info['origin_meters'])
    world,normals = origin+local@basis.T,normal@basis.T
    uv = local[:,:2]/20
    output.mkdir(parents=True,exist_ok=True)
    write_obj(output/'patch.obj',world,normals,uv,faces)
    shutil.copyfile(source/'patch.obj',output/'patch-base.obj')
    mesh_origin = (world.min(axis=0)+world.max(axis=0))/2
    buffers = {}
    for name,array,dtype in [('positions',world-mesh_origin,'<f4'),('normals',normals,'<f4'),
                             ('uvs',uv,'<f4'),('indices',faces,'<u4')]:
        path = output/(name+'.bin');array.astype(dtype).tofile(path)
        buffers[name] = {'file':path.name,'bytes':path.stat().st_size,
                         'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    np.savez_compressed(output/'geometry.npz',positions_local=local,normals_local=normal,faces=faces,
        source_local=native,source_faces=native_faces,field=field,comparison_field=original,
        grid_origin=grid_origin,grid_spacing=spacing)
    metrics = {'grid_samples':int(field.size),'grid_size':list(field.shape),
        'vertices':len(local),'triangles':len(faces),'perimeter_vertices':int(perimeter.sum()),
        'maximum_perimeter_error_meters':float(distance.max()),
        'maximum_outset_meters':float(displacement.max()),'maximum_recession_meters':float(-displacement.min()),
        'inward_facing_vertices':int((normal[:,2]<0).sum()),
        'rays_with_multiple_surface_crossings':int((np.count_nonzero(
            (field[:,:,:-1]<0)!=(field[:,:,1:]<0),axis=2)>1).sum()),
        'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        'elapsed_seconds':time.monotonic()-started,**consolidation}
    report = copy.deepcopy(info)
    report.update(model='eroded-implicit-rock',metrics=metrics,erosion=erosion_metrics,
        erosion_profile=settings,comparison_reference='original-uneroded-sculpture',
        source_sculpture=str(source),installed_in_game=False,
        source_sculpture_mesh_sha256=hashlib.sha256((source/'mesh.json').read_bytes()).hexdigest(),
        source_erosion_profile_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        erosion_generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (output/'surface.json').write_text(json.dumps(report,indent=2)+'\n')
    mesh = {'version':1,'package':'/Game/CustomMaps/Veymont/Nanite/SM_ErodedCliffStudy',
        'coordinate_system':info['coordinate_system'],'winding':'counterclockwise',
        'origin_meters':mesh_origin.tolist(),'vertices':len(local),'triangles':len(faces),'buffers':buffers,
        'nanite_built':False,'geological_model':'eroded-implicit-rock','camera_verified':False,
        'metric_fracture_depths_measured':False}
    (output/'mesh.json').write_text(json.dumps(mesh,indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
    resource.setrlimit(resource.RLIMIT_CPU,(120,125))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    try:
        report = prepare(args.source,args.profile,args.output_dir)
    except (ValueError,KeyError,OSError,MemoryError) as error:
        parser.error(str(error))
    print(json.dumps({'erosion':report['erosion'],'geometry':report['metrics']},indent=2))


if __name__=='__main__':
    main()
