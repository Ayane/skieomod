#!/usr/bin/env python3
"""Inspect mesh topology and render scientific field previews outside Unreal.

These previews are not screenshots of the game and do not test its materials.
Fixed-step volume rays are used because our scalar field is not an exact SDF.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import resource

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import map_coordinates
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


def sample(field, points, origin, spacing):
    return map_coordinates(field, ((points-origin)/spacing).T, order=1,
                           mode='constant',cval=1e3)


def render(field, origin, spacing, extent, light, azimuth=0):
    width,height = 400,540
    center = np.array([extent[0]/2,extent[1]/2,
                      (origin[2]+origin[2]+spacing[2]*(field.shape[2]-1))/2])
    direction = np.array([np.sin(azimuth),0,-np.cos(azimuth)])
    right, up = np.array([np.cos(azimuth),0,np.sin(azimuth)]), np.array([0.,1,0])
    span = max(extent[0]*1.18,extent[1]*width/height*1.12)
    x,y = np.meshgrid(np.linspace(-span/2,span/2,width),
                      np.linspace(span/2*height/width,-span/2*height/width,height))
    base = center+x.reshape(-1,1)*right+y.reshape(-1,1)*up-direction*60
    lower,upper = origin,origin+spacing*(np.array(field.shape)-1)
    inverse = np.divide(1,direction,out=np.full(3,np.inf),where=np.abs(direction)>1e-8)
    near,far = (lower-base)*inverse,(upper-base)*inverse
    # Parallel axes are handled explicitly to avoid 0*inf at a box boundary.
    for axis in range(3):
        if abs(direction[axis])<1e-8:
            inside = (base[:,axis]>=lower[axis]) & (base[:,axis]<=upper[axis])
            near[:,axis],far[:,axis] = np.where(inside,-np.inf,np.inf),np.where(inside,np.inf,-np.inf)
    enter = np.minimum(near,far).max(axis=1)
    leave = np.maximum(near,far).min(axis=1)
    valid = np.isfinite(enter) & (leave>enter)
    active = np.flatnonzero(valid)
    distance = enter[active]+1e-5
    previous = sample(field,base[active]+distance[:,None]*direction,origin,spacing)
    points = np.zeros_like(base)
    hits = np.zeros(len(base),bool)
    step = float(spacing.min()/2)
    count = int(np.ceil(np.linalg.norm(upper-lower)/step))+2
    for _ in range(count):
        if not len(active):
            break
        next_distance = distance+step
        p = base[active]+next_distance[:,None]*direction
        value = sample(field,p,origin,spacing)
        crossing = (previous>=0) & (value<0)
        fraction = np.divide(previous,previous-value,out=np.zeros_like(value),
                             where=np.abs(previous-value)>1e-12)
        t = distance+fraction*step
        points[active[crossing]] = base[active[crossing]]+t[crossing,None]*direction
        hits[active[crossing]] = True
        remaining = ~crossing & (next_distance<leave[active])
        active,distance,previous = active[remaining],next_distance[remaining],value[remaining]
    normal = []
    epsilon = spacing.min()*.1
    for offset in np.eye(3)*epsilon:
        normal.append(sample(field,points[hits]+offset,origin,spacing)-
                      sample(field,points[hits]-offset,origin,spacing))
    normal = np.stack(normal,axis=-1)
    normal /= np.maximum(np.linalg.norm(normal,axis=1,keepdims=True),1e-12)
    light = np.asarray(light,dtype=float);light /= np.linalg.norm(light)
    shade = .18+.82*np.maximum(normal@light,0)
    rgb = np.full((len(base),3),.22)
    rgb[hits] = np.clip(shade[:,None]*np.array([.94,.93,.89]),0,1)
    return Image.fromarray(np.rint(rgb.reshape(height,width,3)*255).astype('uint8'))


def inspect(directory):
    report = json.loads((directory/'surface.json').read_text())
    with np.load(directory/'geometry.npz',allow_pickle=False) as data:
        p,n,f = [data[name].copy() for name in ['positions_local','normals_local','faces']]
        source = data['source_local'].copy()
        field,origin,spacing = [data[name].copy() for name in ['field','grid_origin','grid_spacing']]
        comparison = data['comparison_field'].copy() if 'comparison_field' in data.files else None
    extent = np.array(report['reference']['extent_meters'])
    if not np.isfinite(p).all() or not np.isfinite(n).all() or not np.allclose(np.linalg.norm(n,axis=1),1,atol=1e-6):
        raise ValueError('non-finite geometry or invalid normals')
    area = np.linalg.norm(np.cross(p[f[:,1]]-p[f[:,0]],p[f[:,2]]-p[f[:,0]]),axis=1)
    if (area<1e-12).any():
        raise ValueError('degenerate triangles after envelope clamping')
    edges = np.sort(np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]),axis=1)
    unique,counts = np.unique(edges,axis=0,return_counts=True)
    boundary = unique[counts==1]
    boundary_points = p[boundary,:2]
    # Both endpoints must share an outer U or V edge, not merely lie on
    # different edges at opposite sides of a triangle.
    same_edge = np.any(np.all(np.isclose(boundary_points,0,atol=1e-8),axis=1) |
                       np.all(np.isclose(boundary_points,extent,atol=1e-8),axis=1),axis=1)
    nonmanifold = int((counts>2).sum())
    interior_open = int((~same_edge).sum())
    graph = coo_matrix((np.ones(len(unique)),(unique[:,0],unique[:,1])),shape=(len(p),len(p)))
    components,_ = connected_components(graph,directed=False)
    audit = {'vertex_components':components,'nonmanifold_edges':nonmanifold,
             'interior_open_edges':interior_open,'outer_boundary_edges':len(boundary),
             'degenerate_triangles':0,'finite_unit_normals':True}
    if components!=1 or nonmanifold or interior_open:
        (directory/'topology-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
        raise ValueError('patch has disconnected fragments or interior mesh holes: '+str(audit))
    rows,columns = report['size'][1],report['size'][0]
    depth = source[:,2].reshape(rows,columns)
    u,v = np.meshgrid(origin[0]+np.arange(field.shape[0])*spacing[0],
                      origin[1]+np.arange(field.shape[1])*spacing[1],indexing='ij')
    b = map_coordinates(depth,[v/extent[1]*(rows-1),u/extent[0]*(columns-1)],order=1,mode='nearest')
    baseline_field = origin[2]+np.arange(field.shape[2])[None,None,:]*spacing[2]-b[:,:,None]
    if comparison is not None:
        if comparison.shape!=field.shape:
            raise ValueError('invalid erosion comparison field')
        baseline_field = comparison
    for name,volume,angle,light in [('base',baseline_field,0,[.5,.6,1]),
                                  ('volume',field,0,[.5,.6,1]),
                                  ('volume-oblique',field,.45,[-.6,.55,1])]:
        render(volume,origin,spacing,extent,light,angle).save(directory/(name+'-preview.png'))
    canvas = Image.new('RGB',(1200,595),'#e6e6e6'); draw = ImageDraw.Draw(canvas)
    volume_title = {'sculpted-implicit-rock':'Rock sculpture','eroded-implicit-rock':'After erosion'}.get(report['model'],'Blocks and fractures')
    base_title = 'Sculpture before erosion' if comparison is not None else 'Source terrain'
    for number,(name,title) in enumerate([('base',base_title),('volume',volume_title),
                                        ('volume-oblique','Oblique view, reversed sunlight')]):
        canvas.paste(Image.open(directory/(name+'-preview.png')),(number*400,25))
        draw.text((number*400+12,8),title,fill='black')
    source = 'procedural profile, unmeasured dimensions' if report['model'] in ('sculpted-implicit-rock','eroded-implicit-rock') else 'candidate photographic constraints'
    draw.text((15,575),f'Geometry study outside the engine - {extent[0]:g} x {extent[1]:g} m - {source}',fill='black')
    canvas.save(directory/'comparison.png')
    audit.update({'preview_is_game_capture':False,
                  'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024})
    (directory/'topology-audit.json').write_text(json.dumps(audit,indent=2)+'\n')
    print(json.dumps(audit,indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
    resource.setrlimit(resource.RLIMIT_CPU,(120,125))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    inspect(args.directory)


if __name__=='__main__':
    main()
