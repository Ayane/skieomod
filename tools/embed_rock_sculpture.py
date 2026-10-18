#!/usr/bin/env python3
"""Splice portable volumetric rock into the exact native terrain and snow.

The four patch edges are cut into the existing triangles, sampled on their
actual planes and split at identical knots on both sides. This is a local
integration stage; it does not repeat a small sculpture across the mountain.
"""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
from scipy.spatial import cKDTree

from tools.build_nanite_rock import validate_mesh
from tools.implicit_rock import ReferenceSurface, smooth, unit


def clip_polygon(polygon, axis, limit, sign):
    """Clip a convex polygon, interpolating all attributes at intersections."""
    result = []
    for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
        da,db = (a[axis]-limit)*sign,(b[axis]-limit)*sign
        if da>=-1e-10:
            result.append(a)
        if (da>1e-10 and db<-1e-10) or (da<-1e-10 and db>1e-10):
            point = a+(b-a)*(da/(da-db))
            point[axis] = limit
            result.append(point)
    if not result:
        return np.empty((0,polygon.shape[1]))
    result = np.array(result)
    keep = np.linalg.norm(result[:,:3]-np.roll(result[:,:3],1,axis=0),axis=1)>1e-8
    return result[keep]


def polygon_area(polygon):
    if len(polygon)<3:
        return 0.
    cross = np.cross(polygon[1:-1,:3]-polygon[0,:3],polygon[2:,:3]-polygon[0,:3])
    return float(np.linalg.norm(cross,axis=1).sum()/2)


def sample_native(uv, polygons):
    """Use source triangle planes, rather than interpolating a resampled DEM."""
    result = np.zeros((len(uv),8))
    found = np.zeros(len(uv),bool)
    for polygon in polygons:
        for i in range(1,len(polygon)-1):
            triangle = polygon[[0,i,i+1]]
            matrix = (triangle[1:,:2]-triangle[0,:2]).T
            if abs(np.linalg.det(matrix))<1e-12:
                continue
            selected = np.flatnonzero(((uv>=triangle[:,:2].min(0)-1e-7) &
                                        (uv<=triangle[:,:2].max(0)+1e-7)).all(1))
            bary = (uv[selected]-triangle[0,:2])@np.linalg.inv(matrix).T
            valid = (bary>=-1e-7).all(1) & (bary.sum(1)<=1+1e-7)
            selected,bary = selected[valid],bary[valid]
            sampled = triangle[0]+bary@(triangle[1:]-triangle[0])
            if found[selected].any() and np.max(np.abs(result[selected[found[selected]],2]-sampled[found[selected],2]))>1e-5:
                raise ValueError('native terrain folds over the patch projection')
            result[selected] = sampled
            found[selected] = True
    if not found.all():
        raise ValueError(f'patch is not covered by native triangles: {int((~found).sum())} samples')
    return result


def split_polygon(polygon, knots, tree):
    """Propagate new edge nodes to adjacent triangles to avoid T junctions."""
    result = []
    for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
        result.append(a)
        delta = b[:3]-a[:3]
        squared = float(delta@delta)
        if squared<1e-14:
            continue
        candidate = tree.query_ball_point((a[:3]+b[:3])/2,np.sqrt(squared)/2+1e-6)
        if not candidate:
            continue
        p = knots[candidate]
        fraction = ((p-a[:3])@delta)/squared
        distance = np.linalg.norm(p-a[:3]-fraction[:,None]*delta,axis=1)
        length = np.sqrt(squared)
        fraction = np.unique(np.round(fraction[(distance<1e-6) &
            (fraction*length>1e-5) & ((1-fraction)*length>1e-5)],10))
        if len(fraction)>1:
            fraction = fraction[np.r_[True,np.diff(fraction)*length>1e-5]]
        for t in fraction:
            result.append(a+(b-a)*t)
    return np.asarray(result)


def split_boundary(polygon, attributes, extent):
    result=[]
    for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
        result.append(a)
        side = any(abs(a[axis]-limit)<1e-7 and abs(b[axis]-limit)<1e-7
                   for axis,limit in ((0,0),(0,extent[0]),(1,0),(1,extent[1])))
        if not side:
            continue
        delta=b[:2]-a[:2];length=np.linalg.norm(delta)
        if length<1e-10:
            continue
        fraction=((attributes[:,:2]-a[:2])@delta)/(length*length)
        distance=np.linalg.norm(attributes[:,:2]-a[:2]-fraction[:,None]*delta,axis=1)
        selected=np.flatnonzero((distance<1e-7) & (fraction*length>1e-5) & ((1-fraction)*length>1e-5))
        selected=selected[np.argsort(fraction[selected])]
        if len(selected)>1:
            selected=selected[np.r_[True,np.diff(fraction[selected])*length>1e-5]]
        result.extend(attributes[selected])
    return np.asarray(result)


def triangulate(polygons, knots, boundary_attributes=None, extent=None):
    tree = cKDTree(knots)
    vertices,faces = [],[]
    count = 0
    lower,upper = knots.min(0)-1e-6,knots.max(0)+1e-6
    for polygon in polygons:
        if boundary_attributes is not None:
            polygon=split_boundary(polygon,boundary_attributes,extent)
        elif ((polygon[:,:3].max(0)>=lower) & (polygon[:,:3].min(0)<=upper)).all():
            polygon = split_polygon(polygon,knots,tree)
        if len(polygon)==3:
            vertices.extend(polygon)
            faces.append([count,count+1,count+2]);count+=3
        elif len(polygon)>3:
            # A centre fan retains every collinear boundary node; a corner fan
            # would discard zero-area children and reopen the welded interface.
            center = polygon.mean(0)
            vertices.extend(polygon);vertices.append(center)
            for i in range(len(polygon)):
                faces.append([count+i,count+(i+1)%len(polygon),count+len(polygon)])
            count+=len(polygon)+1
    attributes = np.asarray(vertices)
    unique,inverse = np.unique(np.round(attributes,9),axis=0,return_inverse=True)
    faces = inverse[np.asarray(faces)].astype(np.uint32)
    return unique,faces


def audit(points, faces):
    _,weld = np.unique(np.round(points,6),axis=0,return_inverse=True)
    welded = weld[faces]
    edges = np.sort(np.concatenate([welded[:,[0,1]],welded[:,[1,2]],welded[:,[2,0]]]),axis=1)
    _,counts = np.unique(edges,axis=0,return_counts=True)
    area = np.linalg.norm(np.cross(points[faces[:,1]]-points[faces[:,0]],
                                   points[faces[:,2]]-points[faces[:,0]]),axis=1)
    return {'open_edges':int((counts==1).sum()),'nonmanifold_edges':int((counts>2).sum()),
            'degenerate_triangles':int((area<1e-14).sum())}


def boundary_segments(points, faces):
    vertices,weld=np.unique(np.round(points,6),axis=0,return_inverse=True)
    welded=weld[faces]
    edges=np.sort(np.concatenate([welded[:,[0,1]],welded[:,[1,2]],welded[:,[2,0]]]),axis=1)
    unique,count=np.unique(edges,axis=0,return_counts=True)
    return vertices[unique[count==1]]


def same_boundary(before, after):
    if not len(before) or not len(after):
        return len(before)==len(after)
    # Subdividing a boundary edge is legitimate. Its physical curve and total
    # length must remain unchanged; a new interior opening fails this check.
    delta=before[:,1]-before[:,0]
    squared=(delta*delta).sum(1)
    for segment in after:
        middle=segment.mean(0)
        t=np.clip(((middle-before[:,0])*delta).sum(1)/squared,0,1)
        if np.linalg.norm(middle-before[:,0]-t[:,None]*delta,axis=1).min()>3e-6:
            return False
    length_before=np.linalg.norm(delta,axis=1).sum()
    length_after=np.linalg.norm(after[:,1]-after[:,0],axis=1).sum()
    return bool(abs(length_before-length_after)<1e-5+length_before*1e-8)


def orient_consistently(points, faces, native_face_count):
    """Propagate fronts from native triangles, independently of shading normals.

    Interpolated volume gradients can disagree with tiny extracted facets.
    Orienting each face against that gradient creates reversed triangles in an
    otherwise closed surface. Shared-edge parity gives consistent fronts.
    """
    _,weld=np.unique(np.round(points,6),axis=0,return_inverse=True)
    geometry=weld[faces]
    edges=np.stack([geometry[:,[0,1]],geometry[:,[1,2]],geometry[:,[2,0]]],axis=1).reshape(-1,2)
    _,inverse,counts=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True,return_counts=True)
    if (counts>2).any():
        raise ValueError('cannot orient a nonmanifold surface')
    order=np.argsort(inverse,kind='stable')
    start=np.r_[0,np.cumsum(counts[:-1])][counts==2]
    a,b=order[start],order[start+1]
    same=(edges[a,0]<edges[a,1])==(edges[b,0]<edges[b,1])
    neighbours=np.full((len(faces),3),-1,dtype=np.int64)
    parity=np.zeros((len(faces),3),bool)
    neighbours[a//3,a%3]=b//3;neighbours[b//3,b%3]=a//3
    parity[a//3,a%3]=same;parity[b//3,b%3]=same
    flip=np.full(len(faces),-1,dtype=np.int8)
    components=0
    for seed in range(len(faces)):
        if flip[seed]>=0:
            continue
        if seed>=native_face_count:
            raise ValueError('sculpture is disconnected from the native surface')
        components+=1;flip[seed]=0;queue=deque([seed])
        while queue:
            current=queue.popleft()
            for slot,other in enumerate(neighbours[current]):
                if other<0:
                    continue
                expected=flip[current]^int(parity[current,slot])
                if flip[other]<0:
                    flip[other]=expected;queue.append(other)
                elif flip[other]!=expected:
                    raise ValueError('nonorientable sculpture surface')
    if flip[:native_face_count].any():
        raise ValueError('native source has inconsistent triangle fronts')
    repaired=faces.copy();selected=flip==1
    repaired[selected]=repaired[selected][:,[0,2,1]]
    return repaired,{'inconsistent_shared_edges_before':int(same.sum()),
        'inconsistent_shared_edges_after':0,'reoriented_triangles':int(selected.sum()),
        'connected_surface_components':components}


def splice(points, normals, uvs, faces, patch_points, patch_normals, patch_faces,
           native_depth, info):
    basis,origin = np.array(info['basis_columns']),np.array(info['origin_meters'])
    extent = np.array(info['reference']['extent_meters'])
    if (basis.shape!=(3,3) or not np.isfinite(basis).all() or
            not np.allclose(basis.T@basis,np.eye(3),atol=1e-6) or np.linalg.det(basis)<.999 or
            origin.shape!=(3,) or not np.isfinite(origin).all() or extent.shape!=(2,) or
            not np.isfinite(extent).all() or (extent<=0).any()):
        raise ValueError('invalid sculpture transform or extent')
    reference = ReferenceSurface(native_depth,extent)
    local = (points-origin)@basis
    patch = (patch_points-origin)@basis
    plane_bounds = local[faces,:2]
    near = ((plane_bounds.max(1)>=0) & (plane_bounds.min(1)<=extent)).all(1)
    near &= local[faces,2].max(1)>=native_depth.min()-3
    near &= local[faces,2].min(1)<=native_depth.max()+3
    polygons,removed,new_nodes = [],[],[]
    attrs = np.column_stack([local,normals,uvs])
    planes = [(0,0,1),(0,extent[0],-1),(1,0,1),(1,extent[1],-1)]
    for index,face in enumerate(faces):
        triangle = attrs[face]
        if not near[index]:
            polygons.append(triangle);continue
        remaining = triangle.copy();outside = []
        for axis,limit,sign in planes:
            part = clip_polygon(remaining,axis,limit,-sign)
            if polygon_area(part)>1e-10:
                outside.append(part)
            remaining = clip_polygon(remaining,axis,limit,sign)
            if len(remaining)<3:
                break
        if polygon_area(remaining)<=1e-10:
            polygons.append(triangle);continue
        if np.cross(triangle[1,:3]-triangle[0,:3],triangle[2,:3]-triangle[0,:3])[2]<=1e-9:
            raise ValueError('patch projection includes a back-facing native surface')
        polygons.extend(outside);removed.append(remaining)
        new_nodes.extend(p[:3] for polygon in outside+[remaining] for p in polygon)
    if not removed:
        raise ValueError('patch does not intersect the native terrain')
    sampled = sample_native(patch[:,:2],removed)
    correction = sampled[:,2]-reference.sample(patch[:,:2])
    maximum_correction = float(np.abs(correction).max())
    if maximum_correction>.15:
        raise ValueError(f'patch reference differs from the native surface by {maximum_correction:.3f} m')
    patch[:,2] += correction
    edge = np.minimum(patch[:,:2],extent-patch[:,:2]).min(1)
    border = edge<1e-7
    patch[border,2] = sampled[border,2]
    fade = smooth(edge/info['profile']['edge_fade_meters'])
    n = unit(patch_normals*fade[:,None]+unit(sampled[:,3:6])*(1-fade[:,None]))
    # Use the native UV projection at the interface, and on the snow shell.
    patch_attrs = np.column_stack([patch,n,sampled[:,6:8]])
    knots = np.unique(np.round(np.concatenate([np.asarray(new_nodes),patch[border]]),8),axis=0)
    boundary=((knots[:,:2]>=-1e-7) & (knots[:,:2]<=extent+1e-7)).all(1)
    boundary &= np.minimum(np.abs(knots[:,:2]),np.abs(extent-knots[:,:2])).min(1)<1e-7
    boundary_attrs=sample_native(knots[boundary,:2],removed)
    boundary_attrs[:,:2]=knots[boundary,:2]
    # Knots are copied into both sides, with equal depths/normals at the seam.
    attributes,base_faces = triangulate(polygons,knots)
    split,sculpt_faces = triangulate([patch_attrs[face] for face in patch_faces],knots,
                                    boundary_attrs,extent)
    combined = np.concatenate([attributes,split])
    combined_faces = np.concatenate([base_faces,sculpt_faces+len(attributes)])
    world = origin+combined[:,:3]@basis.T
    combined_faces,orientation=orient_consistently(world,combined_faces,len(base_faces))
    before,after = audit(points,faces),audit(world,combined_faces)
    boundary_unchanged=same_boundary(boundary_segments(points,faces),boundary_segments(world,combined_faces))
    if not boundary_unchanged or after['nonmanifold_edges'] or after['degenerate_triangles']:
        raise ValueError(f'patch splicing changed the open boundary or topology: {before} -> {after}')
    return world,unit(combined[:,3:6]),combined[:,6:8],combined_faces,{
        'removed_native_triangles':len(removed),'interface_knots':int(border.sum()),
        'maximum_native_reference_correction_meters':maximum_correction,
        'outer_boundary_unchanged':boundary_unchanged,
        'topology_before':before,'topology_after':after,**orientation}


def prepare(sources, patch_dir, output):
    started = time.monotonic()
    if not 1<=len(sources)<=64:
        raise ValueError('provide 1..64 native source sections')
    if output.resolve()==patch_dir.resolve() or patch_dir.resolve() in output.resolve().parents:
        raise ValueError('keep integrated output outside the original sculpture')
    patch_info = json.loads((patch_dir/'surface.json').read_text())
    if patch_info.get('model')!='eroded-implicit-rock':
        raise ValueError('integration requires an eroded volumetric sculpture')
    validate_mesh(patch_dir/'mesh.json')
    arrays = [[],[],[],[]];sections=[];first=None;count=0;fingerprints=[]
    for source in sources:
        info = json.loads((source/'tile-source.json').read_text())
        if info.get('coordinate_system')!='east-south-up-metres' or info.get('winding')!='counterclockwise':
            raise ValueError('invalid native source coordinates')
        if first is None:
            first=info
        for key in ('map_id','source_file','source_definition','source_origin_centimeters','sample_step','tile_quads','uv_tile_meters'):
            if info[key]!=first[key]:
                raise ValueError('native source sections differ')
        if info['source_section'] in sections:
            raise ValueError('duplicate native section')
        p=np.loadtxt(source/'positions.txt')+info['origin_meters']
        n=np.loadtxt(source/'normals.txt');uv=np.loadtxt(source/'uvs.txt')
        f=np.loadtxt(source/'indices.txt',dtype=np.uint32)
        if len(p)!=info['vertices'] or len(f)!=info['triangles'] or f.max()>=len(p) or not all(np.isfinite(a).all() for a in (p,n,uv)):
            raise ValueError('invalid native buffers')
        for target,value in zip(arrays,(p,n,uv,f+count)):
            target.append(value)
        count+=len(p);sections.append(info['source_section'])
        fingerprints.append(hashlib.sha256((source/'positions.txt').read_bytes()).hexdigest())
    r16_sha = hashlib.sha256(Path(first['source_file']).read_bytes()).hexdigest()
    if r16_sha!=patch_info['reference']['source_r16_sha256']:
        raise ValueError('sculpture was generated from a different heightmap')
    points,normals,uvs,faces = [np.concatenate(a) for a in arrays]
    with np.load(patch_dir/'geometry.npz',allow_pickle=False) as data:
        basis,origin=np.array(patch_info['basis_columns']),np.array(patch_info['origin_meters'])
        rows,columns=patch_info['size'][1],patch_info['size'][0]
        result = splice(points,normals,uvs,faces,
            origin+data['positions_local']@basis.T,data['normals_local']@basis.T,data['faces'],
            data['source_local'][:,2].reshape(rows,columns),patch_info)
    points,normals,uvs,faces,metrics = result
    if len(points)>1_000_000 or len(faces)>2_000_000:
        raise ValueError('integrated mesh budget exceeded')
    # Keep micron-scale sculpture edges close to the float32 buffer origin.
    # The distant native triangles are metres wide and tolerate that origin.
    mesh_origin=np.array(json.loads((patch_dir/'mesh.json').read_text())['origin_meters'])
    # Geometric duplicates may differ by floating-point clipping noise even
    # though their normals/UVs differ legitimately. Share one exact position
    # before float32 conversion and snow translation, preserving those attrs.
    _,representative,weld=np.unique(np.round(points,6),axis=0,return_index=True,return_inverse=True)
    pinned=points[representative][weld]
    metrics['maximum_weld_correction_meters']=float(np.linalg.norm(pinned-points,axis=1).max())
    points=pinned
    manifest=json.loads(Path(first['source_manifest']).read_text())
    snow_offset=manifest['terrain'].get('runtime',{}).get('snow_offset_centimeters',30)
    if type(snow_offset) not in (int,float) or not np.isfinite(snow_offset) or not 0<=snow_offset<=200:
        raise ValueError('invalid snow offset')
    results=[]
    for layer in ('terrain','snow'):
        directory=output/layer;directory.mkdir(parents=True,exist_ok=True)
        positions=points-mesh_origin
        layer_uvs=uvs
        if layer=='snow':
            positions=positions+[0,0,snow_offset/100]
            layer_uvs=(points[:,:2]-np.array(first['source_origin_centimeters'][:2])/100)/first['uv_tile_meters']
        encoded_audit=audit(positions.astype('<f4').astype(float),faces)
        if encoded_audit!=metrics['topology_after']:
            raise ValueError(f'{layer} float32 export changes mesh topology: {encoded_audit}')
        buffers={}
        for name,value,dtype in [('positions',positions,'<f4'),('normals',normals,'<f4'),('uvs',layer_uvs,'<f4'),('indices',faces,'<u4')]:
            path=directory/(name+'.bin');value.astype(dtype).tofile(path)
            buffers[name]={'file':path.name,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        result=dict(first,version=1,package='/Game/CustomMaps/Veymont/Nanite/SM_GrandVeymontSculpture'+layer.title(),
            origin_meters=mesh_origin.tolist(),vertices=len(points),triangles=len(faces),buffers=buffers,
            layer=layer,source_sections=sorted(sections),mesh_algorithm=2,nanite_built=False,
            source_r16_sha256=r16_sha,source_mesh_sha256=fingerprints,snow_offset_centimeters=snow_offset,
            geological_model='eroded-implicit-rock',source_sculpture=str(patch_dir.resolve()),
            source_sculpture_sha256=hashlib.sha256((patch_dir/'mesh.json').read_bytes()).hexdigest(),
            integration_generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            tile_edges_unchanged=True,outer_perimeter_unchanged=True,
            photographic_correction_applied=False,integration=metrics)
        (directory/'mesh.json').write_text(json.dumps(result,indent=2)+'\n');results.append(result)
    metrics.update(vertices=len(points),triangles=len(faces),source_sections=sections,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        elapsed_seconds=time.monotonic()-started)
    (output/'integration-audit.json').write_text(json.dumps(metrics,indent=2)+'\n')
    return metrics


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources',type=Path,nargs='+')
    parser.add_argument('--sculpture',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    resource.setrlimit(resource.RLIMIT_CPU,(120,125))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    try:
        print(json.dumps(prepare(args.sources,args.sculpture,args.output_dir),indent=2))
    except (ValueError,KeyError,OSError,MemoryError) as error:
        parser.error(str(error))


if __name__=='__main__':
    main()
