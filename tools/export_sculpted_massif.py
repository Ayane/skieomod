#!/usr/bin/env python3
"""Audit all streamed interfaces, smooth across parts and export paired meshes."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import resource

import numpy as np
from scipy.spatial import cKDTree

from tools.embed_rock_sculpture import audit
from tools.implicit_rock import unit, smooth
from tools.prepare_sculpted_massif import NativeMassif, FRONT, rock_weight


def geometry_sums(points, baseline, faces):
    geo, representative, weld = np.unique(np.round(points, 9), axis=0, return_index=True, return_inverse=True)
    f = weld[faces]
    directed = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    edges, inverse, counts = np.unique(np.sort(directed, axis=1), axis=0, return_inverse=True, return_counts=True)
    parity = np.bincount(inverse, weights=np.where(directed[:, 0]<directed[:, 1], 1., -1.))
    if np.any(counts>2) or np.any((counts==2) & (parity!=0)):
        raise ValueError('nonmanifold or inconsistent front orientation')
    border = edges[counts==1]
    total, base = np.zeros((len(geo), 3)), np.zeros((len(geo), 3))
    for p, dest in ((points, total), (baseline, base)):
        cross = np.cross(p[faces[:, 1]]-p[faces[:, 0]], p[faces[:, 2]]-p[faces[:, 0]])
        for corner in range(3):
            np.add.at(dest, weld[faces[:, corner]], cross)
    return geo, representative, weld, border, total, base


def simplify(points, uvs, faces, library, error=.04):
    """Index-only reduction: shared boundary positions cannot move or disappear."""
    geo, representative, weld, border, _, _ = geometry_sums(points, points, faces)
    locks = np.zeros(len(geo), dtype=np.uint8)
    locked_geo = np.zeros(len(geo), dtype=bool)
    locked_geo[np.unique(border)] = True
    locks[locked_geo] = 1
    # The simplifier accepts float32. Centre each microvolume so it does not
    # conflate micron-scale crossings merely because the massif is kilometres
    # away from world zero; returned indices retain the original coordinates.
    p = np.ascontiguousarray(geo-(geo.min(0)+geo.max(0))/2, dtype=np.float32)
    # Reduce the welded geometric surface. Terrain projection UV seams are
    # regenerated from the native reference afterwards, so they cannot make
    # duplicate zero-crossing vertices look like torn topology to the reducer.
    uv = np.zeros((len(geo),2),dtype=np.float32)
    indices = np.ascontiguousarray(weld[faces], dtype=np.uint32)
    out = np.empty_like(indices)
    dll = ctypes.CDLL(str(library.resolve()))
    fun = dll.simplify_rock
    fun.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.c_float, ctypes.POINTER(ctypes.c_float)]
    fun.restype = ctypes.c_size_t
    actual = ctypes.c_float()
    count = fun(out.ctypes.data, indices.ctypes.data, indices.size, p.ctypes.data, len(p),
        uv.ctypes.data, locks.ctypes.data, max(3, indices.size//10//3*3), error, ctypes.byref(actual))
    result = representative[out.ravel()[:count].reshape(-1, 3)]
    _,welded=np.unique(np.round(points,9),axis=0,return_inverse=True)
    collapsed=np.sort(welded[result],axis=1)
    result=result[np.all(np.diff(collapsed,axis=1)>0,axis=1)]
    _,unique=np.unique(np.sort(welded[result],axis=1),axis=0,return_index=True)
    result=result[np.sort(unique)]
    try:
        after = geometry_sums(points, points, result)
    except ValueError:
        # Difficult near-tangent CSG intersections can be conflated by the
        # simplifier's float32 input. Retain this bounded microvolume intact;
        # never trade a topological defect for a lower triangle count.
        return faces,dict(input_triangles=len(faces),output_triangles=len(faces),
            absolute_quadric_error_meters=0.,boundary_locked=True,skipped='topology')
    def segments(g, b):
        return {tuple(sorted((tuple(g[a]), tuple(g[z])))) for a,z in b}
    if segments(geo, border)!=segments(after[0], after[3]):
        return faces,dict(input_triangles=len(faces),output_triangles=len(faces),
            absolute_quadric_error_meters=0.,boundary_locked=True,skipped='interface')
    if actual.value>error+1e-6:
        raise ValueError('simplification exceeded its absolute error metric')
    return result, dict(input_triangles=len(faces), output_triangles=len(result),
        absolute_quadric_error_meters=float(actual.value), boundary_locked=True)


def native_uvs(points,prior,faces,baseline,origin,tile):
    cross=np.cross(baseline[faces[:,1]]-baseline[faces[:,0]],baseline[faces[:,2]]-baseline[faces[:,0]])
    tiny=np.linalg.norm(cross,axis=1)<1e-10
    cross[tiny]=prior[faces[tiny]].mean(axis=1)
    direction=np.abs(cross)
    modes=np.where(direction[:,:2].max(axis=1)<=direction[:,2],0,
        np.where(direction[:,0]>=direction[:,1],1,2))
    keys=np.column_stack([faces.ravel(),np.repeat(modes,3)])
    unique,inverse=np.unique(keys,axis=0,return_inverse=True)
    index,mode=unique[:,0],unique[:,1]
    p,n,base=points[index],prior[index],baseline[index]
    uv=(base[:,:2]-origin[:2])/tile
    yz=mode==1;xz=mode==2
    uv[yz]=np.column_stack([(base[yz,1]-origin[1])/tile,base[yz,2]/tile])
    uv[xz]=np.column_stack([(base[xz,0]-origin[0])/tile,base[xz,2]/tile])
    return p,n,uv,inverse.reshape(-1,3).astype(np.uint32),base


def validate_perimeter(opened, references, native, origin):
    """Refinement may subdivide an unchanged native perimeter; prove coverage."""
    g,_,_,border,_,_=geometry_sums(native.points,native.points,native.faces)
    segments=g[border];delta=segments[:,1]-segments[:,0]
    length=np.linalg.norm(delta,axis=1);tree=cKDTree(segments.mean(axis=1))
    intervals=[[] for _ in border]
    for edge in opened:
        reference=np.asarray(references[edge]);points=np.asarray(edge)
        # Every outer point must remain exactly on its encoded native knot.
        encoded=(reference-origin).astype('<f4').astype(float)+origin
        if not np.allclose(points,encoded,rtol=0,atol=1e-8):
            raise ValueError('sculpture displaced the native outer perimeter')
        candidates=tree.query_ball_point(reference.mean(axis=0),length.max()/2+np.linalg.norm(reference[1]-reference[0])/2+1e-6)
        hit=None
        for index in candidates:
            t=(reference-segments[index,0])@delta[index]/length[index]**2
            residual=np.linalg.norm(reference-segments[index,0]-t[:,None]*delta[index],axis=1)
            if residual.max()<1e-6 and t.min()>-1e-8 and t.max()<1+1e-8:
                hit=index;intervals[index].append(tuple(sorted(t)));break
        if hit is None:raise ValueError('an open edge is inside the massif')
    for ranges in intervals:
        end=0.
        for a,b in sorted(ranges):
            if abs(a-end)>1e-7:raise ValueError('native outer perimeter has a gap or overlap')
            end=b
        if abs(end-1)>1e-7:raise ValueError('native outer perimeter is incomplete')
    return len(border)


def interior_backing(native,section,part,depth=2.6):
    """A native rock skin inside the outer envelope hides independent LOD gaps.

    Nanite preserves cluster interfaces within one asset, while exterior
    asset edges can simplify independently. This coarse interior skin remains
    behind even the deepest 2.2 m cut; it never changes terrain collision.
    """
    # One continuous coarse skin, stored in the first rock asset. Dividing the
    # support itself at the visible asset interfaces would reproduce the gap.
    selected=(np.flatnonzero(native.face_normals@FRONT>.12)
        if section==native.sections[0] and part==0 else np.array([],dtype=int))
    used,remap=np.unique(native.faces[selected],return_inverse=True)
    p=native.points[used]-FRONT*depth
    n=native.normals[used];base=native.points[used]
    return native_uvs(p,n,remap.reshape(-1,3).astype(np.uint32),base,
        np.array(native.first['source_origin_centimeters'])/100,native.first['uv_tile_meters'])


class SurfaceTransition:
    """World-space taper shared by every partition and both render layers.

    The zero-weight native knots include the pinned reverse charts and the
    unmodified ground. Measuring in 3D avoids compressing a tall cliff's
    transition into its few metres of DEM XY. Nothing fades at part borders.
    """
    def __init__(self, native, width):
        if not np.isfinite(width) or not 1 <= width <= 100:
            raise ValueError('surface transition width must be 1..100 metres')
        self.width = width
        anchors = native.points[native.weights <= 1e-8]
        if not len(anchors):
            raise ValueError('surface transition needs unchanged native knots')
        self.tree = cKDTree(np.unique(anchors, axis=0))

    def weight(self, baseline):
        distance = self.tree.query(baseline, workers=1)[0]
        return smooth(distance/self.width)


def surface_normals(prior, base, total, weld, transition):
    """Blend lighting continuously; snow retention uses the actual shelf slope."""
    old, new = unit(base)[weld], unit(total)[weld]
    axis = np.cross(old, new)
    cosine = np.sum(old*new, axis=1)
    cross = np.cross(axis, prior)
    rotated = prior+cross+np.cross(axis,cross)/np.maximum(1+cosine[:,None],1e-8)
    rotated[cosine<-.999] = new[cosine<-.999]
    # A displacement threshold switched an entire normal correction on at
    # 2 mm, revealing lines even where the geometry was already tapering.
    w = transition[:, None]
    rock = unit(prior*(1-w)+rotated*w)
    # M_Snow reads VertexNormalWS. Rotating the DEM's smooth shading normal
    # hides some small upward-facing shelves from its retention calculation.
    snow = unit(prior*(1-w)+new*w)
    return rock, snow


def export(sources, geometry, output, library=None, transition_width=24.):
    native = NativeMassif(sources)
    transition = SurfaceTransition(native, transition_width)
    origin = np.array([-1512., 1008., 2000.])
    directories = sorted(geometry.glob('s*-p*'))
    expected = {(section, part) for section in native.sections for part in range(16)}
    got = set()
    edges = {}
    references = {}
    seam_normals = {}
    preparations = []
    r16_sha = hashlib.sha256(Path(native.first['source_file']).read_bytes()).hexdigest()
    manifest = json.loads(Path(native.first['source_manifest']).read_text())
    snow_offset = manifest['terrain'].get('runtime', {}).get('snow_offset_centimeters', 30)
    for directory in directories:
        summary = json.loads((directory/'audit.json').read_text())
        identity = (summary['section'], summary['part'])
        if identity in got:
            raise ValueError('duplicate geometry partition')
        got.add(identity)
        with np.load(directory/'geometry.npz', allow_pickle=False) as data:
            p, n, uv, f, baseline = [data[k].copy() for k in ('points', 'normals', 'uvs', 'faces', 'baseline')]
        fade = transition.weight(baseline)
        p = baseline+(p-baseline)*fade[:, None]
        # All neighbouring assets encode the same tapered knot exactly.
        p = (p-origin).astype('<f4').astype(float)+origin
        detail = None
        if library:
            f, detail = simplify(p-origin, uv, f, library)
        used, remap = np.unique(f, return_inverse=True)
        p,n,uv,baseline = [a[used] for a in (p,n,uv,baseline)]
        f = remap.reshape(-1, 3).astype(np.uint32)
        p,n,uv,f,baseline=native_uvs(p,n,f,baseline,np.array(native.first['source_origin_centimeters'])/100,
            native.first['uv_tile_meters'])
        if len(p)>1_000_000 or len(f)>2_000_000:
            raise ValueError('portable Nanite mesh budget exceeded')
        g, representative, weld, border, total, base = geometry_sums(p, baseline, f)
        for a,b in border:
            key = tuple(sorted((tuple(g[a]), tuple(g[b]))))
            edges[key] = edges.get(key, 0)+1
            references[key]=tuple(tuple(baseline[representative[index]]) for index in (a,b))
        for index in np.unique(border):
            key = tuple(g[index])
            sums = seam_normals.setdefault(key, [np.zeros(3), np.zeros(3)])
            sums[0] += total[index]; sums[1] += base[index]
        stage = output/directory.name
        stage.mkdir(parents=True, exist_ok=True)
        np.savez(stage/'geometry.npz', points=p, normals=n, uvs=uv, faces=f, baseline=baseline)
        preparations.append((stage, summary, detail))
    if got!=expected:
        raise ValueError(f'incomplete geometry coverage: {sorted(expected-got)}')
    # Every internal interface must occur twice. The only remaining border is
    # the original native outer perimeter, encoded with the same float32 origin.
    if any(count>2 for count in edges.values()):
        raise ValueError('overlapping massif partitions')
    opened = {key for key,count in edges.items() if count==1}
    perimeter_edges=validate_perimeter(opened,references,native,origin)
    results = []
    for stage, summary, detail in preparations:
        with np.load(stage/'geometry.npz', allow_pickle=False) as data:
            p, prior, uv, f, baseline = [data[k].copy() for k in ('points','normals','uvs','faces','baseline')]
        g, representative, weld, border, total, base = geometry_sums(p, baseline, f)
        for index in np.unique(border):
            total[index],base[index] = seam_normals[tuple(g[index])]
        fade = transition.weight(baseline)
        normals, snow_normals = surface_normals(prior, base, total, weld, fade)
        for layer in ('terrain','snow'):
            directory = stage/layer; directory.mkdir(exist_ok=True)
            positions = p-origin
            texture = uv
            if layer=='snow':
                positions = positions+[0,0,snow_offset/100]
                texture = (baseline[:,:2]-np.array(native.first['source_origin_centimeters'][:2])/100)/native.first['uv_tile_meters']
            layer_normals = snow_normals if layer=='snow' else normals
            layer_faces=f
            support_triangles=0
            if layer=='terrain':
                bp,bn,buv,bf,_=interior_backing(native,summary['section'],summary['part'])
                support_triangles=len(bf)
                layer_faces=np.concatenate([f,bf+len(p)])
                positions=np.concatenate([positions,bp-origin])
                layer_normals=np.concatenate([normals,bn]);texture=np.concatenate([texture,buv])
            if len(positions)>1_000_000 or len(layer_faces)>2_000_000:
                raise ValueError('portable Nanite mesh budget exceeded with interior support')
            buffers = {}
            for name, value, dtype in [('positions',positions,'<f4'),('normals',layer_normals,'<f4'),('uvs',texture,'<f4'),('indices',layer_faces,'<u4')]:
                path = directory/(name+'.bin');value.astype(dtype).tofile(path)
                buffers[name] = dict(file=path.name,bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            package = f"/Game/CustomMaps/Veymont/Nanite/SM_SculptedMassifS{summary['section']}P{summary['part']:02d}{layer.title()}"
            result = dict(native.first,source_sections=[summary['section']],source_section=summary['section'],
                layer=layer,part=summary['part'],parts=16,mesh_algorithm=3,origin_meters=origin.tolist(),
                vertices=len(positions),triangles=len(layer_faces),package=package,buffers=buffers,source_r16_sha256=r16_sha,
                source_mesh_sha256=native.fingerprints,snow_offset_centimeters=snow_offset,
                geological_model='streamed-eroded-angular-csg',photographic_correction_applied=False,
                outer_perimeter_unchanged=True,internal_tile_seams=False,simplification=detail,nanite_built=False,
                primary_surface_triangles=len(f),interior_backing_triangles=support_triangles,
                interior_backing_meters=2.6 if support_triangles else 0,preserve_partition_fallback=True,
                surface_transition={'width_meters':transition_width,'space':'native-reference-3d',
                    'curve':'smootherstep','partition_borders_faded':False},
                snow_retention_normals='sculpted-geometric-slope-with-native-transition')
            (directory/'mesh.json').write_text(json.dumps(result,indent=2)+'\n')
            results.append(result)
    report = dict(source_sections=native.sections, complete_partitions=len(expected),
        layers=['terrain','snow'],original_outer_boundary_edges=perimeter_edges,
        transition_width_meters=transition_width,
        snow_retention_normals='sculpted-geometric-slope-with-native-transition',
        refined_outer_boundary_edges=len(opened),
        internal_interfaces_closed=True,
        primary_surface_triangles_per_layer=sum(r['primary_surface_triangles'] for r in results if r['layer']=='terrain'),
        terrain_vertices=sum(r['vertices'] for r in results if r['layer']=='terrain'),
        terrain_triangles=sum(r['triangles'] for r in results if r['layer']=='terrain'),
        snow_vertices=sum(r['vertices'] for r in results if r['layer']=='snow'),
        snow_triangles=sum(r['triangles'] for r in results if r['layer']=='snow'),
        interior_backing_triangles=sum(r['interior_backing_triangles'] for r in results),
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    (output/'export-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources',type=Path,nargs='+')
    parser.add_argument('--geometry-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--simplifier',type=Path)
    parser.add_argument('--transition-width',type=float,default=24.,
        help='world-space fade towards unchanged native ground, in metres')
    args=parser.parse_args()
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    print(json.dumps(export(args.sources,args.geometry_dir,args.output_dir,args.simplifier,args.transition_width),indent=2))


if __name__=='__main__': main()
